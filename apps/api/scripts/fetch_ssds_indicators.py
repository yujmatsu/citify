"""TASK-FISCAL — e-Stat 社会・人口統計体系(統計でみる市区町村のすがた)から
街選び判断軸の5指標を取得して正規化 CSV を出力する。

対象 (政府統計コード statsCode=00200502 / 統計でみる市区町村のすがた 基礎データ):
    財政力指数 / 実質公債費比率   … D 行政基盤
    1人当たり課税対象所得          … C 経済基盤 (課税対象所得 ÷ 納税義務者数)
    持ち家比率                     … H 居住 (持ち家数 ÷ 居住世帯あり住宅数)
    刑法犯認知件数(人口千対)       … K 安全 (刑法犯認知件数 ÷ 人口 × 1000)

設計: fetch_estat_api.py の e-Stat 3.0 クライアント(_api_call / ページング /
市区町村コード判定)を踏襲。statsDataId と項目コード(cdCat01)は時点で変わるため、
ハードコードせず discover で特定 → fetch に渡す方式。

使い方 (要 ESTAT_APP_ID、実環境で実行):
    export ESTAT_APP_ID="<your_app_id>"
    cd /home/yujmatsu/projects/citify/apps/api

    # 1) 市区町村「基礎データ」分野別の statsDataId を一覧 (C/D/H/K を特定)
    .venv/bin/python -m scripts.fetch_ssds_indicators list \\
        --search-word "統計でみる市区町村のすがた 基礎データ"

    # 2) ある分野表の項目コード(cdCat01)を keyword で探す (財政力指数=D2201 系 等)
    .venv/bin/python -m scripts.fetch_ssds_indicators meta \\
        --stats-data-id <D行政基盤の表ID> --grep 財政力 実質公債費

    # 3) 5指標を取得 → 正規化 CSV (discover で判明した id/code を JSON config で渡す)
    .venv/bin/python -m scripts.fetch_ssds_indicators fetch \\
        --config scripts/ssds_config.json \\
        --output ../../infra/seed/ssds_indicators_normalized.csv
"""

from __future__ import annotations

import argparse
import csv as _csv
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.e-stat.go.jp/rest/3.0/app/json"
STATS_CODE_SSDS = "00200502"  # 社会・人口統計体系
DEFAULT_RATE_LIMIT_SEC = 1.0


# ============================================================================
# e-Stat 3.0 クライアント (fetch_estat_api.py と同方式)
# ============================================================================
def _api_call(
    endpoint: str,
    params: dict[str, Any],
    app_id: str,
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
) -> dict[str, Any]:
    app_id = (app_id or "").strip()
    url = f"{API_BASE}/{endpoint}"
    params = {"appId": app_id, **params}
    time.sleep(rate_limit_sec)
    with httpx.Client(timeout=30.0) as client:
        res = client.get(url, params=params)
        res.raise_for_status()
        body = res.json()
    # 各 endpoint の RESULT ブロックを確認。
    # STATUS=0: 正常 / STATUS=1: 正常だが該当データ無し(エラー扱いしない) / その他: エラー
    root = next((v for v in body.values() if isinstance(v, dict)), {})
    result = root.get("RESULT", {})
    status = result.get("STATUS", -1)
    # API仕様 v3.0: STATUS 0〜2 は正常終了、100以上がエラー
    if status not in (0, 1, 2):
        raise RuntimeError(
            f"e-Stat API error endpoint={endpoint} status={status} msg={result.get('ERROR_MSG')}"
        )
    return body


def _require_app_id() -> str | None:
    app_id = os.getenv("ESTAT_APP_ID")
    if not app_id:
        print("ERROR: ESTAT_APP_ID is not set", file=sys.stderr)
        return None
    return app_id


def _is_municipality_code(code: str) -> bool:
    """5 桁市区町村コードを識別 (全国/都道府県/市部郡部 集約は除外)。"""
    if not code or len(code) != 5 or not code.isdigit():
        return False
    if code == "00000":
        return False
    return code[2:] not in ("000", "001", "002")


# ============================================================================
# discover: list / meta
# ============================================================================
def _field(obj: Any) -> str:
    """e-Stat の {'$': '値'} or 文字列フィールドを文字列化。"""
    if isinstance(obj, dict):
        return str(obj.get("$", ""))
    return str(obj) if obj is not None else ""


def cmd_list(args: argparse.Namespace) -> int:
    """getStatsList で SSDS(00200502) 配下の統計表を検索し statsDataId を表示。

    DB 上の表名は「市区町村データ 基礎データ」/ TITLE が「Ｄ 行政基盤」等。
    searchWord 省略時は statsCode のみで取得し、--contains 語(default 市区町村/基礎データ)で
    クライアント側フィルタする。
    """
    app_id = _require_app_id()
    if not app_id:
        return 1
    params: dict[str, Any] = {"statsCode": STATS_CODE_SSDS, "limit": args.limit}
    if args.search_word:
        params["searchWord"] = args.search_word
    body = _api_call("getStatsList", params, app_id)
    tables = body.get("GET_STATS_LIST", {}).get("DATALIST_INF", {}).get("TABLE_INF", [])
    if isinstance(tables, dict):
        tables = [tables]

    contains = args.contains or []

    def hit(t: dict[str, Any]) -> bool:
        hay = f"{_field(t.get('STATISTICS_NAME'))} {_field(t.get('TITLE'))} {_field(t.get('STAT_NAME'))}"
        return all(c in hay for c in contains)

    filtered = [t for t in tables if hit(t)]
    print(
        f"# SSDS 検索 {len(tables)} 件中 {len(filtered)} 件 "
        f"(search='{args.search_word or ''}' contains={contains})"
    )
    print(f"# {'@id':<12} {'STATISTICS_NAME':<30} TITLE")
    print("-" * 100)
    for t in filtered[: args.limit]:
        sid = t.get("@id", "?")
        sname = _field(t.get("STATISTICS_NAME"))[:30]
        title = _field(t.get("TITLE"))
        print(f"  {sid:<12} {sname:<30} {title[:50]}")
    if not filtered:
        print("  (該当なし — --search-word を外す / --contains を緩める / limit を上げる)")
    print("\n# → 市区町村データ かつ TITLE が C/D/H/K 分野の @id を fetch config に使う")
    return 0


def cmd_meta(args: argparse.Namespace) -> int:
    """getMetaInfo で 1 統計表の項目(cat01)/地域/時点コードを表示 (項目コード特定用)。"""
    app_id = _require_app_id()
    if not app_id:
        return 1
    body = _api_call("getMetaInfo", {"statsDataId": args.stats_data_id}, app_id)
    class_objs = (
        body.get("GET_META_INFO", {})
        .get("METADATA_INF", {})
        .get("CLASS_INF", {})
        .get("CLASS_OBJ", [])
    )
    if isinstance(class_objs, dict):
        class_objs = [class_objs]
    grep = [g for g in (args.grep or [])]
    for obj in class_objs:
        oid, oname = obj.get("@id", "?"), obj.get("@name", "?")
        items = obj.get("CLASS", [])
        if isinstance(items, dict):
            items = [items]
        print(f"\n## CLASS @id={oid} ({oname}) — {len(items)} 項目")
        shown = 0
        for it in items:
            name = str(it.get("@name", ""))
            if grep and not any(g in name for g in grep):
                continue
            print(f"   code={it.get('@code', '?'):<14} {name}")
            shown += 1
            if not grep and shown >= 20:
                print("   ... (先頭20件のみ。--grep で絞り込み可)")
                break
    return 0


# ============================================================================
# fetch: config 駆動で 5 指標 → 正規化 CSV
# ============================================================================
def _fetch_indicator(app_id: str, spec: dict[str, Any]) -> dict[str, float]:
    """1 指標を取得 → {municipality_code: value}。spec は config の 1 エントリ。

    spec 例: {"stats_data_id": "...", "cd_cat01": "D2201...", "cd_time": "2024..."}
    cd_time 省略時は最新時点を自動採用 (各市区町村の最大 @time)。
    """
    sid = spec["stats_data_id"]
    extra: dict[str, Any] = {"cdCat01": spec["cd_cat01"], "lang": "J"}
    if spec.get("cd_time"):
        extra["cdTime"] = spec["cd_time"]
    if spec.get("cd_tab"):
        extra["cdTab"] = spec["cd_tab"]

    all_values: list[dict[str, Any]] = []
    start = 1
    while True:
        params = {"statsDataId": sid, "limit": 100000, "startPosition": start, **extra}
        body = _api_call("getStatsData", params, app_id)
        sd = body.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})
        vals = sd.get("DATA_INF", {}).get("VALUE", [])
        if isinstance(vals, dict):
            vals = [vals]
        all_values.extend(vals)
        nxt = sd.get("RESULT_INF", {}).get("NEXT_KEY")
        if not nxt:
            break
        start = int(nxt)

    # cd_time 未指定なら各市区町村の最新 @time を採用
    by_code: dict[str, tuple[str, float]] = {}
    for v in all_values:
        code = v.get("@area", "")
        if not _is_municipality_code(code):
            continue
        raw = str(v.get("$", "")).replace(",", "")
        try:
            num = float(raw)
        except ValueError:
            continue
        t = str(v.get("@time", ""))
        if code not in by_code or t > by_code[code][0]:
            by_code[code] = (t, num)
    return {code: val for code, (_, val) in by_code.items()}


def cmd_fetch(args: argparse.Namespace) -> int:
    """config の指標を取得し、派生指標を計算して正規化 CSV を出力。

    config(JSON) 構造:
    {
      "data_year": 2025,
      "source_url": "https://www.e-stat.go.jp/...",
      "indicators": {
        "financial_capability_index": {"stats_data_id": "...", "cd_cat01": "..."},
        "real_debt_service_ratio_pct": {...},
        "taxable_income_total": {...},          # 課税対象所得 (千円 等)
        "taxpayers": {...},                      # 納税義務者数
        "owned_homes": {...},                    # 持ち家数
        "dwellings": {...},                      # 居住世帯あり住宅数
        "crime_count": {...},                    # 刑法犯認知件数
        "population": {...}                      # 総人口 (千対計算用)
      }
    }
    出力列: municipality_code, financial_capability_index, real_debt_service_ratio_pct,
            taxable_income_per_capita_yen, homeownership_rate_pct, crime_rate_per_1000,
            ssds_data_year, ssds_source_url
    """
    app_id = _require_app_id()
    if not app_id:
        return 1
    config = json.loads(args.config.read_text(encoding="utf-8"))
    inds: dict[str, dict[str, Any]] = config["indicators"]

    fetched: dict[str, dict[str, float]] = {}
    for key, spec in inds.items():
        logger.info(
            "ssds.fetch indicator=%s id=%s cat01=%s", key, spec["stats_data_id"], spec["cd_cat01"]
        )
        fetched[key] = _fetch_indicator(app_id, spec)
        logger.info("ssds.fetched indicator=%s n_munis=%d", key, len(fetched[key]))

    def g(key: str, code: str) -> float | None:
        return fetched.get(key, {}).get(code)

    all_codes = sorted({c for d in fetched.values() for c in d})
    year = config.get("data_year", "")
    src = config.get("source_url", "")

    rows: list[list[Any]] = []
    for code in all_codes:
        fci = g("financial_capability_index", code)
        rdsr = g("real_debt_service_ratio_pct", code)
        # 1人当たり課税対象所得 = 課税対象所得 / 納税義務者数
        income_total, taxpayers = g("taxable_income_total", code), g("taxpayers", code)
        income_pc = (
            round(income_total * 1000 / taxpayers)
            if income_total is not None and taxpayers
            else None
        )  # 課税対象所得が千円単位の場合 ×1000 (単位は meta で確認し config 注記)
        # 持ち家比率 = 持ち家数 / 住宅数 × 100
        owned, dwellings = g("owned_homes", code), g("dwellings", code)
        own_rate = round(owned / dwellings * 100, 1) if owned is not None and dwellings else None
        # 刑法犯認知件数(人口千対) = 刑法犯 / 人口 × 1000
        crime, pop = g("crime_count", code), g("population", code)
        crime_rate = round(crime / pop * 1000, 2) if crime is not None and pop else None

        # TASK-CITYDATA 追加8指標 (派生は分母0/欠損で None)
        doctors, hospitals = g("doctors", code), g("hospitals", code)
        doctors_per_100k = round(doctors / pop * 100000, 1) if doctors is not None and pop else None
        labor_force, unemployed = g("labor_force", code), g("unemployed", code)
        unemployment_rate = (
            round(unemployed / labor_force * 100, 1)
            if unemployed is not None and labor_force
            else None
        )
        employed, tertiary = g("employed", code), g("tertiary_workers", code)
        tertiary_pct = (
            round(tertiary / employed * 100, 1) if tertiary is not None and employed else None
        )
        dwelling_area = g("dwelling_area", code)
        day_night = g("day_night_pop_ratio", code)
        elem, junior = g("elementary_schools", code), g("junior_high_schools", code)
        school_count = (
            int((elem or 0) + (junior or 0)) if (elem is not None or junior is not None) else None
        )
        nursery_children = g("nursery_children", code)

        rows.append(
            [
                code,
                fci,
                rdsr,
                income_pc,
                own_rate,
                crime_rate,
                doctors_per_100k,
                int(hospitals) if hospitals is not None else None,
                unemployment_rate,
                tertiary_pct,
                dwelling_area,
                day_night,
                school_count,
                int(nursery_children) if nursery_children is not None else None,
                year,
                src,
            ]
        )

    with args.output.open("w", encoding="utf-8", newline="") as f:
        w = _csv.writer(f)
        w.writerow(
            [
                "municipality_code",
                "financial_capability_index",
                "real_debt_service_ratio_pct",
                "taxable_income_per_capita_yen",
                "homeownership_rate_pct",
                "crime_rate_per_1000",
                "doctors_per_100k",
                "ssds_hospital_count",
                "unemployment_rate_pct",
                "tertiary_industry_pct",
                "dwelling_area_sqm",
                "day_night_pop_ratio",
                "school_count",
                "nursery_children",
                "ssds_data_year",
                "ssds_source_url",
            ]
        )
        w.writerows(rows)
    logger.info("ssds.fetch done output=%s n_codes=%d", args.output, len(all_codes))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.fetch_ssds_indicators")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="SSDS の統計表 ID を検索")
    p_list.add_argument(
        "--search-word",
        default=None,
        help="e-Stat searchWord (省略推奨。statsCode のみで取得し --contains で絞る)",
    )
    p_list.add_argument(
        "--contains",
        nargs="*",
        default=["基礎データ"],
        help="表示する表のフィルタ語 (AND一致、default: 基礎データ)。例: --contains 市区町村 基礎データ",
    )
    p_list.add_argument("--limit", type=int, default=100, help="取得件数 (default 100)")
    p_list.set_defaults(func=cmd_list)

    p_meta = sub.add_parser("meta", help="統計表の項目/地域/時点コードを表示")
    p_meta.add_argument("--stats-data-id", required=True)
    p_meta.add_argument("--grep", nargs="*", help="項目名フィルタ (例: 財政力 実質公債費)")
    p_meta.set_defaults(func=cmd_meta)

    p_fetch = sub.add_parser("fetch", help="config の5指標を取得 → 正規化 CSV")
    p_fetch.add_argument(
        "--config", type=Path, required=True, help="指標→statsDataId/cat01 の JSON"
    )
    p_fetch.add_argument(
        "--output", type=Path, default=Path("infra/seed/ssds_indicators_normalized.csv")
    )
    p_fetch.set_defaults(func=cmd_fetch)

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
