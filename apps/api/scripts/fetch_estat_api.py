"""Plan A Phase D v2 — e-Stat API 経由で 世帯/2015人口/出生数 を取得。

e-Stat API 3.0 の getStatsData を使い、3 統計表から市区町村別データを取得して
prep_estat_csv.py 互換の CSV を出力する (load_estat_stats.py で BQ 投入可)。

使用方法:
    export ESTAT_APP_ID="<your_app_id>"
    cd /home/yujmatsu/projects/citify/apps/api

    # 統計表 ID を検索 (利用前に一度実行して正しい statsDataId を確認)
    .venv/bin/python -m scripts.fetch_estat_api list \\
        --search-word "国勢調査 世帯数 市区町村"

    # 1 統計表 sample 取得 (動作確認)
    .venv/bin/python -m scripts.fetch_estat_api fetch \\
        --stats-data-id 0003445245 \\
        --limit 10 \\
        --dry-run

    # 3 統計表すべて取得 → prep_estat_csv.py v2 互換 CSV に集約
    .venv/bin/python -m scripts.fetch_estat_api fetch-all \\
        --households-id <id> --pop2015-id <id> --births-id <id> \\
        --output ../../infra/seed/estat_v2_normalized.csv

ステータス: TODO (appId 取得後に statsDataId 検索 → 実装完了)
"""

from __future__ import annotations

import argparse
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
DEFAULT_RATE_LIMIT_SEC = 1.0


def _api_call(
    endpoint: str,
    params: dict[str, Any],
    app_id: str,
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
) -> dict[str, Any]:
    """e-Stat API を 1 回叩く (失敗時は例外)。"""
    # 環境変数貼り付け時の改行混入を吸収 (URL エンコードで %0A になり認証失敗するため)
    app_id = (app_id or "").strip()
    url = f"{API_BASE}/{endpoint}"
    params = {"appId": app_id, **params}
    time.sleep(rate_limit_sec)
    with httpx.Client(timeout=30.0) as client:
        res = client.get(url, params=params)
        res.raise_for_status()
        body = res.json()
    # RESULT block を確認
    result = body.get("GET_STATS_DATA", {}).get("RESULT") or body.get("GET_STATS_LIST", {}).get(
        "RESULT", {}
    )
    status = result.get("STATUS", -1)
    if status != 0:
        raise RuntimeError(
            f"e-Stat API error endpoint={endpoint} status={status} message={result.get('ERROR_MSG')}"
        )
    return body


def cmd_list(args: argparse.Namespace) -> int:
    """getStatsList で統計表 ID を検索 (statsDataId 特定用)。"""
    app_id = os.getenv("ESTAT_APP_ID")
    if not app_id:
        print("ERROR: ESTAT_APP_ID is not set", file=sys.stderr)
        return 1

    params = {
        "searchWord": args.search_word,
        "limit": 30,
    }
    body = _api_call("getStatsList", params, app_id)
    table_inf = body.get("GET_STATS_LIST", {}).get("DATALIST_INF", {}).get("TABLE_INF", [])
    if isinstance(table_inf, dict):
        table_inf = [table_inf]

    print(f"# 検索結果 {len(table_inf)} 件 (search='{args.search_word}')")
    print(f"# {'@id':<12} {'統計名':<40} {'表番号':<10} 表題")
    print("-" * 100)
    for t in table_inf[:30]:
        stats_data_id = t.get("@id", "?")
        stat_name = t.get("STAT_NAME", {}).get("$", "?")[:40]
        title_no = t.get("TITLE", {}).get("@no", "?") if isinstance(t.get("TITLE"), dict) else "?"
        title = (
            t.get("TITLE", {}).get("$", t.get("TITLE", "?"))
            if isinstance(t.get("TITLE"), dict)
            else t.get("TITLE", "?")
        )
        print(f"  {stats_data_id:<12} {stat_name:<40} {title_no:<10} {str(title)[:60]}")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """getStatsData で 1 統計表を取得 (sample / 動作確認)。"""
    app_id = os.getenv("ESTAT_APP_ID")
    if not app_id:
        print("ERROR: ESTAT_APP_ID is not set", file=sys.stderr)
        return 1

    params = {
        "statsDataId": args.stats_data_id,
        "limit": args.limit,
        "lang": "J",
    }
    body = _api_call("getStatsData", params, app_id)
    stats_data = body.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})

    # CLASS_INF — メタデータ
    class_inf = stats_data.get("CLASS_INF", {}).get("CLASS_OBJ", [])
    print(f"# CLASS_INF (メタデータ階層): {len(class_inf)} 件")
    for c in class_inf[:5]:
        print(
            f"  - {c.get('@id', '?')} / {c.get('@name', '?')} (children={len(c.get('CLASS', []))})"
        )

    # DATA_INF — 実データ
    values = stats_data.get("DATA_INF", {}).get("VALUE", [])
    if isinstance(values, dict):
        values = [values]
    print(f"\n# DATA_INF.VALUE: {len(values)} レコード (limit={args.limit})")
    for v in values[:5]:
        print(f"  - {json.dumps(v, ensure_ascii=False)[:200]}")

    if args.dry_run:
        print("\n# (dry-run) 終了")
        return 0

    # output: 全データを JSON で保存 (デバッグ用)
    if args.output:
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
        logger.info("saved raw response to %s", args.output)
    return 0


def _is_municipality_code(code: str) -> bool:
    """5 桁の市区町村コード (XX0NN where NN != 00) を識別。

    e-Stat の area コードは:
      - 00000: 全国
      - 00001: 全国・市部
      - 00002: 全国・郡部
      - XX000: 都道府県 (XX = 01-47)
      - XX001: 都道府県・市部
      - XX002: 都道府県・郡部
      - XX100, XX130, XX140, XX150: 政令市 (親コード)
      - XXNNN (NNN != 000, 001, 002): 市区町村
    Phase D v2 では市区町村 + 都道府県 + 政令市 (親コード) を採用。
    """
    if not code or len(code) != 5 or not code.isdigit():
        return False
    if code == "00000":
        return False
    suffix = code[2:]
    # 市部・郡部 集約 (XX001/XX002) は除外
    return suffix not in ("001", "002")


def _fetch_all_paged(
    app_id: str,
    stats_data_id: str,
    extra_params: dict[str, Any],
    rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
) -> list[dict[str, Any]]:
    """getStatsData をページング込みで全件取得。"""
    all_values: list[dict[str, Any]] = []
    start_position = 1
    page_size = 100000
    while True:
        params = {
            "statsDataId": stats_data_id,
            "limit": page_size,
            "startPosition": start_position,
            "lang": "J",
            **extra_params,
        }
        body = _api_call("getStatsData", params, app_id, rate_limit_sec=rate_limit_sec)
        stats_data = body.get("GET_STATS_DATA", {}).get("STATISTICAL_DATA", {})
        result_inf = stats_data.get("RESULT_INF", {})
        values = stats_data.get("DATA_INF", {}).get("VALUE", [])
        if isinstance(values, dict):
            values = [values]
        all_values.extend(values)
        logger.info(
            "estat.page id=%s start=%d got=%d total=%d",
            stats_data_id,
            start_position,
            len(values),
            len(all_values),
        )
        next_key = result_inf.get("NEXT_KEY")
        if not next_key:
            break
        start_position = int(next_key)
    return all_values


def _values_to_dict(
    values: list[dict[str, Any]],
    area_field: str = "@area",
    value_field: str = "$",
) -> dict[str, int]:
    """{area_code: value} dict に正規化 (市区町村コードのみ)。"""
    out: dict[str, int] = {}
    for v in values:
        code = v.get(area_field, "")
        raw = v.get(value_field, "")
        if not _is_municipality_code(code):
            continue
        try:
            out[code] = int(str(raw).replace(",", ""))
        except ValueError:
            continue
    return out


def cmd_fetch_all(args: argparse.Namespace) -> int:
    """3 統計表 (世帯/2015人口/出生数) を取得 → CSV 出力。

    出力 CSV 列: municipality_code, households_total, population_2015, births_annual
    """
    app_id = os.getenv("ESTAT_APP_ID")
    if not app_id:
        print("ERROR: ESTAT_APP_ID is not set", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # 1) 2015 市区町村別人口 (0003148500)
    #    tab=020 (人口), cat01=00710 (全域), time=2015000000
    # ------------------------------------------------------------------
    logger.info("estat.fetch_all step=1/3 2015_population statsDataId=%s", args.pop2015_id)
    pop2015_values = _fetch_all_paged(
        app_id,
        args.pop2015_id,
        extra_params={"cdTab": "020", "cdCat01": "00710", "cdTime": "2015000000"},
    )
    pop2015_dict = _values_to_dict(pop2015_values)
    logger.info("estat.pop2015 n_munis=%d", len(pop2015_dict))

    # ------------------------------------------------------------------
    # 2) 2020 市区町村別世帯数 (0003445098)
    #    tab で「総世帯数」を識別、cat 系で「総数」を指定。フィルタは
    #    --households-cd-tab / --households-cd-cat オプションで上書き可能。
    # ------------------------------------------------------------------
    logger.info("estat.fetch_all step=2/3 2020_households statsDataId=%s", args.households_id)
    hh_extra: dict[str, Any] = {"cdTime": "2020000000"}
    if args.households_cd_tab:
        hh_extra["cdTab"] = args.households_cd_tab
    if args.households_cd_cat:
        hh_extra["cdCat01"] = args.households_cd_cat
    hh_values = _fetch_all_paged(app_id, args.households_id, extra_params=hh_extra)
    hh_dict = _values_to_dict(hh_values)
    logger.info("estat.households n_munis=%d", len(hh_dict))

    # ------------------------------------------------------------------
    # 3) 2023 市区町村別出生数 (0003412057)
    #    tab=10040 (出生数), cat01=00100 (総数), cat02=000000 (全場所), time=2023000000
    # ------------------------------------------------------------------
    logger.info("estat.fetch_all step=3/3 2023_births statsDataId=%s", args.births_id)
    births_values = _fetch_all_paged(
        app_id,
        args.births_id,
        extra_params={
            "cdTab": "10040",
            "cdCat01": "00100",
            "cdCat02": "000000",
            "cdTime": "2023000000",
        },
    )
    births_dict = _values_to_dict(births_values)
    logger.info("estat.births n_munis=%d", len(births_dict))

    # ------------------------------------------------------------------
    # 3 dict を merge → CSV 出力
    # ------------------------------------------------------------------
    import csv as _csv

    all_codes = sorted(set(pop2015_dict) | set(hh_dict) | set(births_dict))
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = _csv.writer(f)
        writer.writerow(
            ["municipality_code", "households_total", "population_2015", "births_annual"]
        )
        for code in all_codes:
            writer.writerow(
                [
                    code,
                    hh_dict.get(code, ""),
                    pop2015_dict.get(code, ""),
                    births_dict.get(code, ""),
                ]
            )
    logger.info("estat.fetch_all done output=%s n_codes=%d", args.output, len(all_codes))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.fetch_estat_api")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="getStatsList で統計表 ID 検索")
    p_list.add_argument(
        "--search-word", required=True, help="検索キーワード (例: '国勢調査 世帯数')"
    )
    p_list.set_defaults(func=cmd_list)

    p_fetch = sub.add_parser("fetch", help="getStatsData で 1 統計表 sample 取得")
    p_fetch.add_argument("--stats-data-id", required=True, help="統計表 ID (例: 0003445245)")
    p_fetch.add_argument("--limit", type=int, default=10)
    p_fetch.add_argument("--output", type=Path, default=None, help="raw JSON 保存先")
    p_fetch.add_argument("--dry-run", action="store_true")
    p_fetch.set_defaults(func=cmd_fetch)

    p_all = sub.add_parser("fetch-all", help="3 統計表すべて取得 → CSV 出力")
    p_all.add_argument("--households-id", required=True, help="令和2年 世帯数 (例: 0003445098)")
    p_all.add_argument(
        "--households-cd-tab",
        default=None,
        help="世帯数 表章項目コード (CLASS_INF.tab、未指定なら全 tab)",
    )
    p_all.add_argument(
        "--households-cd-cat",
        default=None,
        help="世帯数 cat01 コード (世帯の種類「総数」、未指定なら全 cat)",
    )
    p_all.add_argument("--pop2015-id", required=True, help="平成27年 人口 (例: 0003148500)")
    p_all.add_argument("--births-id", required=True, help="人口動態 出生数 (例: 0003412057)")
    p_all.add_argument(
        "--output",
        type=Path,
        default=Path("infra/seed/estat_v2_normalized.csv"),
    )
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
