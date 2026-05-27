"""Phase F v3 — 3 API (XKT013/XKT010/XKT007) の動作確認用 sample call。

仕様書から判明した z 範囲:
    XKT013 将来推計人口 — z=11-15 (z=11 で 9 タイル / 1 自治体)
    XKT010 医療機関     — z=13-15 (z=13 で 25 タイル / 1 自治体)
    XKT007 保育園・幼稚園 — z=13-15 (z=13 で 25 タイル / 1 自治体)

新宿区周辺 (139.7034, 35.6938) で 1 タイルだけ叩いてレスポンス構造を確認する。

使用方法:
    export REINFOLIB_API_KEY="<your_api_key>"
    cd /home/yujmatsu/projects/citify
    python -m scrapers.reinfolib.sample_call_v3
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

from .tile_utils import lonlat_to_tile

API_BASE = "https://www.reinfolib.mlit.go.jp/ex-api/external"
RATE_LIMIT_SEC = 1.0

# 新宿区中心
CENTER_LNG = 139.7034
CENTER_LAT = 35.6938


def _call(api_id: str, params: dict[str, Any], api_key: str) -> tuple[int, Any]:
    url = f"{API_BASE}/{api_id}"
    headers = {"Ocp-Apim-Subscription-Key": api_key.strip()}
    try:
        with httpx.Client(timeout=30.0) as client:
            res = client.get(url, params=params, headers=headers)
            if res.status_code != 200:
                return res.status_code, {"_error_body": res.text[:400]}
            return 200, res.json()
    except httpx.HTTPError as exc:
        return -1, {"_exception": str(exc)}


def sample_geojson_tile(
    api_id: str,
    z: int,
    api_key: str,
    label: str,
) -> dict[str, Any]:
    """指定 API + z で新宿区中心の 1 タイルを取得しレスポンス要約。"""
    x, y = lonlat_to_tile(CENTER_LNG, CENTER_LAT, z)
    params = {"response_format": "geojson", "z": z, "x": x, "y": y}
    status, body = _call(api_id, params, api_key)
    summary: dict[str, Any] = {
        "api": api_id,
        "label": label,
        "z": z,
        "x": x,
        "y": y,
        "status": status,
    }
    if status == 200 and isinstance(body, dict):
        features = body.get("features", [])
        summary["n_features"] = len(features)
        summary["top_keys"] = sorted(body.keys())[:8]
        if features:
            sample = features[0]
            props = sample.get("properties", {})
            summary["sample_property_keys"] = sorted(props.keys())[:20]
            summary["sample_property_preview"] = json.dumps(props, ensure_ascii=False)[:400]
    else:
        summary["error_body"] = body.get("_error_body") if isinstance(body, dict) else str(body)
    return summary


def main() -> int:
    api_key = os.getenv("REINFOLIB_API_KEY")
    if not api_key:
        print("ERROR: REINFOLIB_API_KEY is not set", file=sys.stderr)
        return 1

    print("=" * 70)
    print("Phase F v3 — XKT013/XKT010/XKT007 sample call (新宿区中心)")
    print(f"  center=(lng={CENTER_LNG}, lat={CENTER_LAT})")
    print("=" * 70)
    print()

    tests = [
        ("XKT013", 11, "将来推計人口 250m メッシュ"),
        ("XKT010", 13, "医療機関"),
        ("XKT007", 13, "保育園・幼稚園"),
    ]
    results = []
    for api_id, z, label in tests:
        print(f"--- {api_id} z={z} ({label}) ---")
        result = sample_geojson_tile(api_id, z, api_key, label)
        results.append(result)
        if result["status"] == 200:
            print(f"  ✅ status=200 n_features={result.get('n_features', 0)}")
            print(f"     top_keys={result.get('top_keys')}")
            if result.get("sample_property_keys"):
                print(f"     sample property keys={result['sample_property_keys']}")
                print(
                    f"     sample property preview:\n     {result.get('sample_property_preview', '')}"
                )
        else:
            print(f"  ❌ status={result['status']}")
            print(f"     error={str(result.get('error_body', ''))[:200]}")
        print()
        time.sleep(RATE_LIMIT_SEC)

    print("=" * 70)
    print("判定")
    print("=" * 70)
    for r in results:
        ok = r["status"] == 200 and r.get("n_features", 0) > 0
        mark = "✅" if ok else ("⚠️" if r["status"] == 200 else "❌")
        print(
            f"{mark} {r['api']:<8} z={r['z']:<3} status={r['status']:<4}"
            f"n_features={r.get('n_features', '-'):<4} {r['label']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
