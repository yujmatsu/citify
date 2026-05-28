"""Phase F CLI — Reinfolib API から取得 → municipality_stats_reinfolib_normalized.csv へ出力。

使用方法:
    export REINFOLIB_API_KEY="<your_api_key>"
    cd /home/yujmatsu/projects/citify

    # 1 自治体 dry-run (動作確認)
    python -m scrapers.reinfolib fetch \\
        --code 13104 \\
        --dry-run

    # 45 自治体全部 → CSV (BQ ロード用)
    python -m scrapers.reinfolib fetch-all \\
        --targets-csv infra/seed/reinfolib_targets.csv \\
        --output infra/seed/reinfolib_normalized.csv

出力 CSV 列:
    municipality_code, used_apartment_median_price_man_yen,
    used_apartment_sample_size, used_apartment_median_unit_price_yen,
    used_apartment_avg_building_age, emergency_shelter_count,
    emergency_shelter_official_link, reinfolib_loaded_at, reinfolib_source_url
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from .client import ReinfolibAPIError, ReinfolibClient
from .parsers.xgt001 import aggregate_shelters
from .parsers.xit001 import aggregate_used_apartments
from .parsers.xkt007 import aggregate_childcare
from .parsers.xkt010 import aggregate_medical
from .parsers.xkt013 import aggregate_future_population
from .regions import REGION_LABELS, REGION_MAP, is_in_region, list_regions

logger = logging.getLogger(__name__)

SOURCE_URL = "https://www.reinfolib.mlit.go.jp/"

OUTPUT_COLUMNS = (
    "municipality_code",
    # XIT001 取引価格
    "used_apartment_median_price_man_yen",
    "used_apartment_sample_size",
    "used_apartment_median_unit_price_yen",
    "used_apartment_avg_building_age",
    # XGT001 避難所
    "emergency_shelter_count",
    "emergency_shelter_official_link",
    # Phase F v3: XKT013 将来推計人口
    "population_2025_estimated",
    "population_2050_estimated",
    "population_change_2025_2050_pct",
    # Phase F v3: XKT010 医療機関
    "medical_facility_count",
    "medical_hospital_count",
    "medical_clinic_count",
    # Phase F v3: XKT007 保育園・幼稚園
    "childcare_facility_count",
    "kindergarten_count",
    "nursery_count",
    # メタ
    "reinfolib_loaded_at",
    "reinfolib_source_url",
)


def _load_targets(targets_csv: Path) -> list[dict[str, str]]:
    """reinfolib_targets.csv を読み込む。"""
    with targets_csv.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_one(
    client: ReinfolibClient,
    target: dict[str, str],
) -> dict[str, object]:
    """1 自治体分の XIT001 + XGT001 を fetch & aggregate。

    target は reinfolib_targets.csv の 1 行 (dict)。
    """
    code = target["municipality_code"]
    method = target["xit001_method"]
    param = target["xit001_param"]
    lat = float(target["center_lat"])
    lng = float(target["center_lng"])

    # XIT001 取引価格
    try:
        trades = client.fetch_trades_4quarters(method, param)
        xit001 = aggregate_used_apartments(trades)
    except ReinfolibAPIError as exc:
        logger.error("xit001.failed code=%s err=%s", code, exc)
        xit001 = {
            "used_apartment_median_price_man_yen": None,
            "used_apartment_sample_size": 0,
            "used_apartment_median_unit_price_yen": None,
            "used_apartment_avg_building_age": None,
        }

    # XGT001 避難所
    try:
        features = client.fetch_shelters_around(lng, lat, z=11, radius=1)
        xgt001 = aggregate_shelters(features, lat, lng)
    except Exception as exc:  # noqa: BLE001
        logger.error("xgt001.failed code=%s err=%s", code, exc)
        xgt001 = {
            "emergency_shelter_count": 0,
            "emergency_shelter_official_link": (
                f"https://disaportal.gsi.go.jp/hazardmap/maps/index.html?ll={lat},{lng}&z=12"
            ),
        }

    # Phase F v3: XKT013 将来推計人口 (z=11、9 タイル)
    try:
        xkt013_features = client.fetch_geojson_tiles("XKT013", lng, lat, z=11, radius=1)
        xkt013 = aggregate_future_population(xkt013_features)
    except Exception as exc:  # noqa: BLE001
        logger.error("xkt013.failed code=%s err=%s", code, exc)
        xkt013 = {
            "population_2025_estimated": None,
            "population_2050_estimated": None,
            "population_change_2025_2050_pct": None,
        }

    # Phase F v3: XKT010 医療機関 (z=13、25 タイル ~25 秒)
    try:
        xkt010_features = client.fetch_geojson_tiles("XKT010", lng, lat, z=13, radius=2)
        xkt010 = aggregate_medical(xkt010_features)
    except Exception as exc:  # noqa: BLE001
        logger.error("xkt010.failed code=%s err=%s", code, exc)
        xkt010 = {
            "medical_facility_count": None,
            "medical_hospital_count": None,
            "medical_clinic_count": None,
        }

    # Phase F v3: XKT007 保育園・幼稚園 (z=13、25 タイル ~25 秒)
    # 政令市親 (XX100) は子区合算が必要なので、xit001_method を見て判定
    try:
        xkt007_features = client.fetch_geojson_tiles("XKT007", lng, lat, z=13, radius=2)
        # 政令市親 (city_sum) の場合は administrativeAreaCode フィルタを使わず全件採用
        # その他 (city/area) は厳密に自治体コードでフィルタ
        if method == "city_sum":
            xkt007 = aggregate_childcare(xkt007_features, municipality_code=None)
        else:
            xkt007 = aggregate_childcare(xkt007_features, municipality_code=code)
    except Exception as exc:  # noqa: BLE001
        logger.error("xkt007.failed code=%s err=%s", code, exc)
        xkt007 = {
            "childcare_facility_count": None,
            "kindergarten_count": None,
            "nursery_count": None,
        }

    return {
        "municipality_code": code,
        **xit001,
        **xgt001,
        **xkt013,
        **xkt010,
        **xkt007,
        "reinfolib_loaded_at": dt.datetime.now(dt.UTC).isoformat(),
        "reinfolib_source_url": SOURCE_URL,
    }


def cmd_fetch(args: argparse.Namespace) -> int:
    """1 自治体を fetch して結果を stdout に print (動作確認用)。"""
    targets = _load_targets(args.targets_csv)
    target = next((t for t in targets if t["municipality_code"] == args.code), None)
    if not target:
        print(f"ERROR: code={args.code} not found in {args.targets_csv}", file=sys.stderr)
        return 1

    with ReinfolibClient(rate_limit_sec=args.rate_limit_sec) as client:
        result = fetch_one(client, target)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_fetch_all(args: argparse.Namespace) -> int:
    """全自治体を fetch → CSV 出力 (--region で地方フィルタ、--resume で append 続行)。"""
    targets = _load_targets(args.targets_csv)

    # 地方フィルタ
    if args.region:
        if args.region not in REGION_MAP:
            print(
                f"ERROR: unknown --region={args.region!r}, valid={list_regions()}",
                file=sys.stderr,
            )
            return 1
        before = len(targets)
        targets = [t for t in targets if is_in_region(t["municipality_code"], args.region)]
        logger.info(
            "reinfolib.fetch_all region_filter region=%s (%s) %d -> %d",
            args.region,
            REGION_LABELS.get(args.region, args.region),
            before,
            len(targets),
        )

    # resume: 既存 CSV から完了 code を読み取って skip
    completed_codes: set[str] = set()
    if args.resume and args.output.exists():
        with args.output.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                completed_codes.add(row["municipality_code"])
        logger.info("reinfolib.fetch_all resume: %d 完了済 skip", len(completed_codes))
    todo = [t for t in targets if t["municipality_code"] not in completed_codes]
    logger.info(
        "reinfolib.fetch_all start n_total=%d n_todo=%d region=%s",
        len(targets),
        len(todo),
        args.region or "(all)",
    )

    # resume の場合は append、新規の場合は write
    mode = "a" if (args.resume and args.output.exists()) else "w"
    with (
        ReinfolibClient(rate_limit_sec=args.rate_limit_sec) as client,
        args.output.open(mode, encoding="utf-8", newline="") as f,
    ):
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        if mode == "w":
            writer.writeheader()
        for i, target in enumerate(todo, 1):
            code = target["municipality_code"]
            logger.info(
                "reinfolib.fetch_one %d/%d code=%s name=%s",
                i,
                len(todo),
                code,
                target.get("name", ""),
            )
            try:
                result = fetch_one(client, target)
                writer.writerow(result)
                f.flush()
            except Exception as exc:  # noqa: BLE001
                logger.error("reinfolib.fetch_one_failed code=%s err=%s", code, exc)

    logger.info("reinfolib.fetch_all done output=%s", args.output)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scrapers.reinfolib")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="1 自治体を fetch (動作確認)")
    p_fetch.add_argument("--code", required=True, help="5 桁市区町村コード")
    p_fetch.add_argument(
        "--targets-csv",
        type=Path,
        default=Path("infra/seed/reinfolib_targets.csv"),
    )
    p_fetch.add_argument("--rate-limit-sec", type=float, default=1.0)
    p_fetch.add_argument(
        "--dry-run", action="store_true", help="(現状は print のみで dry-run と等価)"
    )
    p_fetch.set_defaults(func=cmd_fetch)

    p_all = sub.add_parser("fetch-all", help="全自治体 fetch → CSV (--region で地方フィルタ可)")
    p_all.add_argument(
        "--targets-csv",
        type=Path,
        default=Path("infra/seed/reinfolib_targets.csv"),
        help="targets CSV (Phase F v4 で全自治体 → reinfolib_targets_full.csv 推奨)",
    )
    p_all.add_argument(
        "--output",
        type=Path,
        default=Path("infra/seed/reinfolib_normalized.csv"),
    )
    p_all.add_argument(
        "--region",
        default=None,
        choices=list_regions(),
        help="地方フィルタ (hokkaido_tohoku / kanto / koshinetsu / hokuriku / tokai / kinki / chugoku / shikoku / kyushu_okinawa)",
    )
    p_all.add_argument(
        "--resume",
        action="store_true",
        help="既存 --output から完了 code を読み取って続きから (append モード)",
    )
    p_all.add_argument("--rate-limit-sec", type=float, default=1.0)
    p_all.set_defaults(func=cmd_fetch_all)

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
