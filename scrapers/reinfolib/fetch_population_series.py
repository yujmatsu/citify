"""TASK-POPTREND Phase 4a — XKT013 将来推計人口を SHICODE 絞り込みで全自治体 fetch。

reinfolib_targets_full.csv の各自治体について XKT013 (z=11) を取得し、SHICODE で
対象自治体 (政令市は区コード集合) のメッシュだけを各 PT00_YYYY 年次で合算、
long-format CSV (municipality_code, year, population) を出力する。

出力は後段の loader で municipality_population_series (source='projection') に投入。

使い方 (REINFOLIB_API_KEY が必要、人間が実行):
    cd ~/projects/citify
    set -a; source .env; set +a
    apps/api/.venv/bin/python -m scrapers.reinfolib.fetch_population_series \\
        --targets-csv infra/seed/reinfolib_targets_full.csv \\
        --output infra/seed/population_series_projection.csv \\
        [--region kanto] [--resume] [--radius 1]

注意 (Phase 0 知見):
    - PT00 年次は 2025-2070 の 5 年刻み
    - 政令市 (xit001_method=city_sum) は区コード範囲を SHICODE 集合として合算
    - radius=1 (~36km) は最大面積自治体 (高山等) で約 -1.7% 取りこぼすが減少率の形は不変
    - center 座標が不正だと target メッシュ 0 件 → WARNING を出すので後で座標修正
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

from .client import ReinfolibClient
from .parsers.xkt013 import aggregate_population_series
from .regions import REGION_MAP, is_in_region, list_regions

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS = ("municipality_code", "year", "population")


def _shicode_set(target: dict[str, str]) -> set[str]:
    """対象自治体の SHICODE 集合を決定。政令市 (city_sum) は区コード範囲を展開。"""
    code = target["municipality_code"]
    if target.get("xit001_method") == "city_sum":
        param = target.get("xit001_param", "")
        if "-" in param:
            start_s, end_s = param.split("-")
            return {f"{n:05d}" for n in range(int(start_s), int(end_s) + 1)}
    return {code.zfill(5)}


def _load_targets(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fetch_one_series(
    client: ReinfolibClient, target: dict[str, str], radius: int
) -> dict[int, int]:
    """1 自治体の XKT013 人口時系列 {year: pop} を取得。"""
    lat = float(target["center_lat"])
    lng = float(target["center_lng"])
    feats = client.fetch_geojson_tiles("XKT013", lng, lat, z=11, radius=radius)
    return aggregate_population_series(feats, _shicode_set(target))


def cmd_fetch_all(args: argparse.Namespace) -> int:
    targets = _load_targets(args.targets_csv)

    if args.region:
        if args.region not in REGION_MAP:
            print(f"ERROR: unknown --region={args.region!r}", file=sys.stderr)
            return 1
        targets = [t for t in targets if is_in_region(t["municipality_code"], args.region)]

    completed: set[str] = set()
    if args.resume and args.output.exists():
        with args.output.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                completed.add(row["municipality_code"])
    todo = [t for t in targets if t["municipality_code"] not in completed]

    logger.info(
        "poptrend.fetch start n_total=%d n_todo=%d region=%s radius=%d",
        len(targets),
        len(todo),
        args.region or "(all)",
        args.radius,
    )

    empty_codes: list[str] = []
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
            try:
                series = fetch_one_series(client, target, args.radius)
            except Exception as exc:  # noqa: BLE001
                logger.error("poptrend.fetch_failed code=%s err=%s", code, exc)
                continue
            if not series:
                empty_codes.append(code)
                logger.warning(
                    "poptrend.empty code=%s name=%s (center座標が不正/カバレッジ不足の可能性)",
                    code,
                    target.get("name", ""),
                )
            for year, pop in series.items():
                writer.writerow({"municipality_code": code, "year": year, "population": pop})
            f.flush()
            if i % 50 == 0:
                logger.info("poptrend.progress %d/%d", i, len(todo))

    logger.info(
        "poptrend.fetch done output=%s empty=%d %s",
        args.output,
        len(empty_codes),
        empty_codes[:20],
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m scrapers.reinfolib.fetch_population_series")
    p.add_argument(
        "--targets-csv", type=Path, default=Path("infra/seed/reinfolib_targets_full.csv")
    )
    p.add_argument(
        "--output", type=Path, default=Path("infra/seed/population_series_projection.csv")
    )
    p.add_argument("--region", default=None, choices=list_regions())
    p.add_argument("--resume", action="store_true")
    p.add_argument(
        "--radius", type=int, default=1, help="z=11 タイル拡張 (1=3x3, 2=5x5。広域は2推奨)"
    )
    p.add_argument("--rate-limit-sec", type=float, default=1.0)
    p.set_defaults(func=cmd_fetch_all)
    args = p.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
