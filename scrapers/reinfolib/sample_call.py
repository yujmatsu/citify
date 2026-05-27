"""Phase F Step 0 — Reinfolib API の政令市区単位データ取得可否を検証する最小スクリプト。

仕様書 v0.3.1 §4.2 で「政令市の区単位 (例: 27127 大阪市北区) で XIT001 が取れるか」を
着手前 30 分以内に sample call で確認することが Must。本スクリプトはその実行用。

使用方法:
    export REINFOLIB_API_KEY="<your_api_key>"
    cd /home/yujmatsu/projects/citify
    python -m scrapers.reinfolib.sample_call

確認内容:
    1. 都道府県単位 (14000 神奈川県) — XIT001 取引価格
    2. 政令市親 (27100 大阪市)        — XIT001 取引価格
    3. 政令市区 (27127 大阪市北区)    — XIT001 取引価格 ← 採否の決定要因
    4. 中核市 (29201 奈良市)           — XIT001 取引価格
    5. XGT001 避難所 (13104 新宿区)    — レスポンス形式確認

結果は v0.3.1 §改訂履歴 に記録する。
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

# 検証対象 (code, name, kind)
TARGETS = [
    ("14000", "神奈川県", "都道府県"),
    ("27100", "大阪市", "政令市親"),
    ("27127", "大阪市北区", "政令市区"),
    ("29201", "奈良市", "中核市"),
    ("13104", "新宿区", "特別区"),
]


def _call(api_id: str, params: dict[str, Any], api_key: str) -> tuple[int, dict | None]:
    """Reinfolib API を 1 回叩く。(status, json or None) を返す。"""
    url = f"{API_BASE}/{api_id}"
    headers = {"Ocp-Apim-Subscription-Key": api_key}
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.get(url, params=params, headers=headers)
            if res.status_code != 200:
                return res.status_code, {"_error_body": res.text[:300]}
            return 200, res.json()
    except httpx.HTTPError as exc:
        return -1, {"_exception": str(exc)}


def sample_xit001(code: str, name: str, kind: str, api_key: str) -> dict[str, Any]:
    """XIT001 取引価格 sample call。"""
    params = {"year": "2024", "quarter": "3", "city": code}
    status, body = _call("XIT001", params, api_key)
    n_records = len(body.get("data", [])) if (body and "data" in body) else 0
    types_seen = sorted({r.get("Type") for r in (body or {}).get("data", []) if r.get("Type")})
    return {
        "api": "XIT001",
        "code": code,
        "name": name,
        "kind": kind,
        "status": status,
        "n_records": n_records,
        "types_seen": types_seen[:5],
        "sample_record": (body or {}).get("data", [{}])[0] if n_records > 0 else None,
    }


def sample_xgt001(code: str, name: str, kind: str, api_key: str) -> dict[str, Any]:
    """XGT001 指定緊急避難場所 sample call (新宿区固定)。"""
    params = {"city": code}
    status, body = _call("XGT001", params, api_key)
    # XGT001 は GeoJSON 形式の可能性、または features 配列
    n_records = 0
    if body:
        if "features" in body:
            n_records = len(body["features"])
        elif "data" in body:
            n_records = len(body["data"])
    return {
        "api": "XGT001",
        "code": code,
        "name": name,
        "kind": kind,
        "status": status,
        "n_records": n_records,
        "body_keys": sorted((body or {}).keys())[:10],
    }


def main() -> int:
    api_key = os.getenv("REINFOLIB_API_KEY")
    if not api_key:
        print("ERROR: REINFOLIB_API_KEY 環境変数が未設定です", file=sys.stderr)
        print("  export REINFOLIB_API_KEY='<your_api_key>'", file=sys.stderr)
        return 1

    print("=" * 70)
    print("Phase F Step 0 — Reinfolib API sample call (政令市区単位 検証)")
    print(f"API_BASE: {API_BASE}")
    print(f"RATE_LIMIT_SEC: {RATE_LIMIT_SEC}")
    print("=" * 70)
    print()

    results = []

    # 1-4: XIT001 取引価格 (都道府県/政令市親/政令市区/中核市/特別区)
    for code, name, kind in TARGETS:
        print(f"--- XIT001 {kind}: {code} {name} ---")
        result = sample_xit001(code, name, kind, api_key)
        results.append(result)
        print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
        print()
        time.sleep(RATE_LIMIT_SEC)

    # 5: XGT001 避難所 (新宿区)
    print("--- XGT001 特別区: 13104 新宿区 ---")
    result = sample_xgt001("13104", "新宿区", "特別区", api_key)
    results.append(result)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
    print()

    # サマリ判定
    print("=" * 70)
    print("判定")
    print("=" * 70)
    for r in results:
        ok = r["status"] == 200 and r["n_records"] > 0
        mark = "✅" if ok else ("⚠️" if r["status"] == 200 else "❌")
        print(
            f"{mark} {r['api']} {r['kind']:<10} {r['code']} {r['name']:<10}"
            f"  status={r['status']}  n_records={r['n_records']}"
        )

    # 政令市区の採否
    seirei_ku_result = next((r for r in results if r["code"] == "27127"), None)
    if seirei_ku_result:
        print()
        if seirei_ku_result["status"] == 200 and seirei_ku_result["n_records"] > 0:
            print("→ ✅ 政令市の区単位データが取れる → 区も対象に含める方針で OK")
        elif seirei_ku_result["status"] == 200 and seirei_ku_result["n_records"] == 0:
            print("→ ⚠️ 政令市の区は status=200 だが n=0 → 親市 (27100) で集計するfallback 必要")
        else:
            print("→ ❌ 政令市の区は 200 以外 → 親市集計 fallback 必須、v0.3.1 §2 を更新")

    return 0


if __name__ == "__main__":
    sys.exit(main())
