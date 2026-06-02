"""Phase 0 検証 (TASK-POPTREND) — XKT013 の実レスポンスを調べる。

確認項目:
  1. PT00_YYYY の実在年次 (2020〜2070 か) + HITOKU{year} の実フィールド名
  2. SHICODE 絞り込みの実挙動 (対象自治体 vs 近隣のメッシュ数)
  3. 広域自治体 (高山市) で radius=1 が取りこぼさないか (radius=1 vs 2 の対象メッシュ数比較)
  4. aggregate_population_series が正しい人口時系列を返すか

使い方 (REINFOLIB_API_KEY が必要なので人間が実行):
    cd ~/projects/citify
    set -a; source .env; set +a          # .env から REINFOLIB_API_KEY を環境へ
    apps/api/.venv/bin/python -m scrapers.reinfolib.phase0_xkt013_check
"""

from __future__ import annotations

import os
import re
import sys
from collections import Counter

from .client import ReinfolibClient
from .parsers.xkt013 import aggregate_population_series

# (code, name, center_lat, center_lng) — targets_full.csv より
TARGETS = [
    ("13104", "新宿区(小区)", 35.7011, 139.7090),
    ("21203", "高山市(広域)", 36.1318, 137.2858),
    ("01100", "札幌市(北海道01xxx)", 43.0642, 141.3469),  # 中心座標を札幌駅付近に補正
]

_PT00_RE = re.compile(r"^PT00_(\d{4})$")


def _inspect(client: ReinfolibClient, code: str, name: str, lat: float, lng: float) -> None:
    print("=" * 72)
    print(f"■ {code} {name}  center=(lat={lat}, lng={lng})")
    print("=" * 72)

    for radius in (1, 2):
        feats = client.fetch_geojson_tiles("XKT013", lng, lat, z=11, radius=radius)
        # SHICODE 分布
        shicodes = Counter(
            str((f or {}).get("properties", {}).get("SHICODE", "")).zfill(5) for f in feats
        )
        target_meshes = shicodes.get(code.zfill(5), 0)
        # PT00 年次 / HITOKU フィールド名 (先頭の対象メッシュから)
        pt_years: set[int] = set()
        hitoku_fields: set[str] = set()
        for f in feats:
            props = (f or {}).get("properties", {}) or {}
            if str(props.get("SHICODE", "")).zfill(5) != code.zfill(5):
                continue
            for k in props:
                m = _PT00_RE.match(str(k))
                if m:
                    pt_years.add(int(m.group(1)))
                if str(k).startswith("HITOKU"):
                    hitoku_fields.add(str(k))

        series = aggregate_population_series(feats, code)
        print(
            f"  [radius={radius}] total_features={len(feats)} "
            f"distinct_shicode={len(shicodes)} target_meshes={target_meshes}"
        )
        print(f"    PT00 years        = {sorted(pt_years)}")
        print(f"    HITOKU fields     = {sorted(hitoku_fields)}")
        print(f"    population_series = {series}")
        # 近隣自治体の混入度 (上位5)
        top = shicodes.most_common(5)
        print(f"    top SHICODE(mesh) = {top}")
        print()


def main() -> int:
    api_key = os.getenv("REINFOLIB_API_KEY")
    if not api_key:
        print(
            "ERROR: REINFOLIB_API_KEY 未設定。`set -a; source .env; set +a` 後に実行してください。",
            file=sys.stderr,
        )
        return 1

    with ReinfolibClient(rate_limit_sec=1.0) as client:
        for code, name, lat, lng in TARGETS:
            try:
                _inspect(client, code, name, lat, lng)
            except Exception as exc:  # noqa: BLE001
                print(f"  ❌ {code} {name} 失敗: {exc}\n")

    print("=" * 72)
    print("判定ポイント:")
    print("  - PT00 years が 2020..2070 を含むか (将来カーブの点数)")
    print("  - 高山市(広域) で radius=1→2 で target_meshes が大きく増えるなら radius 動的化が必要")
    print("  - population_series が実人口オーダー (新宿~34万, 高山~8万) に近いか")
    return 0


if __name__ == "__main__":
    sys.exit(main())
