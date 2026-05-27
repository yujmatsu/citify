"""Phase F Step 0 v2 — 8 API 全部の sample call で city= / area= 動作を一括検証。

v1 (sample_call.py) で判明: XIT001 は都道府県 (XX000) と政令市親 (XX100) では
city= が 404 を返す。area= (2桁) や政令市区 (XX1NN, NN!=00) では 200。
他 7 API (XPT002/XGT001/XKT013/etc.) も同様の制約があるか不明なので、
本スクリプトで一気に検証して client.py / parsers の設計を確定する。

使用方法:
    export REINFOLIB_API_KEY="<your_api_key>"
    cd /home/yujmatsu/projects/citify
    python -m scrapers.reinfolib.sample_call_v2

検証対象 (8 API × 2-3 パラメータ案 = 約 20 call、rate 1/sec で 20 秒):
    XIT001  city=27127 (大阪市北区, 既に v1 で成功)、 area=27 (大阪府)
    XPT002  city=13104 (新宿区), area=13 (東京都), year=2024
    XGT001  city=13104 (新宿区, v1 で 400), area=13, パラメータ無し
    XKT013  city=13104, response_format=geojson
    XKT015  city=13104
    XKT007  city=13104 (保育園・幼稚園)
    XKT010  city=13104 (医療機関)
    XKT004  city=13104 (小学校区)
    XKT005  city=13104 (中学校区)

結果は v0.3.2 §改訂履歴 に記録、各 API の正しいパラメータが判明したら
parsers の実装に反映する。
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

API_BASE = "https://www.reinfolib.mlit.go.jp/ex-api/external"
RATE_LIMIT_SEC = 1.0


def _call(api_id: str, params: dict[str, Any], api_key: str) -> tuple[int, Any]:
    url = f"{API_BASE}/{api_id}"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.get(url, params=params, headers=headers)
            if res.status_code != 200:
                return res.status_code, {"_error_body": res.text[:400]}
            return 200, res.json()
    except httpx.HTTPError as exc:
        return -1, {"_exception": str(exc)}


# 各 API のテストケース (api_id, params, label, expected_kind)
TEST_CASES = [
    # XIT001 — v1 で確認、area= でも取れるか追加検証
    ("XIT001", {"year": "2024", "quarter": "3", "city": "27127"}, "城下市区 city=", "trade"),
    ("XIT001", {"year": "2024", "quarter": "3", "area": "27"}, "都道府県 area=", "trade"),
    # XPT002 地価公示
    ("XPT002", {"year": "2024", "city": "13104"}, "city=", "landprice"),
    ("XPT002", {"year": "2024", "area": "13"}, "area=", "landprice"),
    # XGT001 指定緊急避難場所 (v1 で city=400)
    ("XGT001", {"city": "13104"}, "city= (v1で400)", "shelter"),
    ("XGT001", {"area": "13"}, "area=", "shelter"),
    # XKT013 将来推計人口
    ("XKT013", {"city": "13104"}, "city=", "future_pop"),
    ("XKT013", {"area": "13"}, "area=", "future_pop"),
    # XKT015 駅別乗降客数
    ("XKT015", {"city": "13104"}, "city=", "station"),
    # XKT007 保育園・幼稚園
    ("XKT007", {"city": "13104"}, "city=", "childcare"),
    # XKT010 医療機関
    ("XKT010", {"city": "13104"}, "city=", "medical"),
    # XKT004 小学校区
    ("XKT004", {"city": "13104"}, "city=", "elem_school"),
    # XKT005 中学校区
    ("XKT005", {"city": "13104"}, "city=", "jr_school"),
]


def _summarize_body(body: Any) -> dict[str, Any]:
    """レスポンス body の構造を要約。"""
    if not isinstance(body, dict):
        return {"type": type(body).__name__, "preview": str(body)[:200]}
    keys = sorted(body.keys())
    n = 0
    sample_record = None
    if "data" in body and isinstance(body["data"], list):
        n = len(body["data"])
        sample_record = body["data"][0] if n > 0 else None
    elif "features" in body and isinstance(body["features"], list):
        n = len(body["features"])
        sample_record = body["features"][0] if n > 0 else None
    return {
        "top_keys": keys[:10],
        "n_records": n,
        "sample_record_keys": sorted(sample_record.keys())[:15]
        if isinstance(sample_record, dict)
        else None,
        "sample_record_preview": json.dumps(sample_record, ensure_ascii=False)[:400]
        if sample_record
        else None,
    }


def main() -> int:
    api_key = os.getenv("REINFOLIB_API_KEY")
    if not api_key:
        print("ERROR: REINFOLIB_API_KEY 環境変数が未設定です", file=sys.stderr)
        return 1

    print("=" * 80)
    print("Phase F Step 0 v2 — 8 API × city/area sample call")
    print("=" * 80)
    print()

    results = []
    for api_id, params, label, kind in TEST_CASES:
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        print(f"--- {api_id} [{kind}] {label}  ({param_str}) ---")
        status, body = _call(api_id, params, api_key)
        summary = _summarize_body(body) if status == 200 else {"error": body}
        result = {
            "api": api_id,
            "kind": kind,
            "label": label,
            "params": params,
            "status": status,
            "summary": summary,
        }
        results.append(result)
        if status == 200:
            print(f"  ✅ status=200, n={summary.get('n_records', '?')}")
            print(f"     top_keys={summary.get('top_keys')}")
            if summary.get("sample_record_keys"):
                print(f"     sample fields={summary['sample_record_keys']}")
        else:
            err_preview = str(summary.get("error", {}).get("_error_body", ""))[:200]
            print(f"  ❌ status={status}")
            print(f"     error={err_preview}")
        print()
        time.sleep(RATE_LIMIT_SEC)

    # サマリ表
    print("=" * 80)
    print("API × パラメータ 動作確認サマリ")
    print("=" * 80)
    print(f"{'API':<8} {'kind':<12} {'params':<30} {'status':<8} {'n':<6}")
    print("-" * 80)
    for r in results:
        params_str = " ".join(f"{k}={v}" for k, v in r["params"].items())[:28]
        n = r["summary"].get("n_records", 0) if r["status"] == 200 else "-"
        mark = "✅" if r["status"] == 200 else "❌"
        print(f"{mark} {r['api']:<6} {r['kind']:<12} {params_str:<30} {r['status']:<8} {n}")

    print()
    print("=" * 80)
    print("各 API の sample record 詳細 (parsers 設計用)")
    print("=" * 80)
    for r in results:
        if r["status"] == 200 and r["summary"].get("sample_record_preview"):
            print(f"\n[{r['api']} {r['label']}]")
            print(f"  {r['summary']['sample_record_preview']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
