"""XKT010 医療機関 → 自治体集計。

入力: client.fetch_geojson_tiles("XKT010", lng, lat, z=13, radius=2) の features
出力:
    - medical_facility_count       周辺地域の医療機関数 (重複除外)
    - medical_hospital_count       うち病院 (P04_001=1)
    - medical_clinic_count         うち診療所 (P04_001=2)

注意: P04_001 の値は実データで 1=病院 / 2=診療所 が確認できている (sample call)。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

HOSPITAL_CODE = 1
CLINIC_CODE = 2


def aggregate_medical(features: list[dict[str, Any]]) -> dict[str, Any]:
    """医療機関の種別別カウント。施設名 (P04_002_ja) で重複除外。"""
    seen: set[str] = set()
    hospital = 0
    clinic = 0
    other = 0
    for f in features:
        props = (f or {}).get("properties", {})
        name = props.get("P04_002_ja") or ""
        addr = props.get("P04_003_ja") or ""
        # 名前 + 住所 で同一施設を識別 (タイル境界で重複出現するため)
        key = f"{name}|{addr}"
        if key in seen or not name:
            continue
        seen.add(key)
        kind = props.get("P04_001")
        if kind == HOSPITAL_CODE:
            hospital += 1
        elif kind == CLINIC_CODE:
            clinic += 1
        else:
            other += 1
    total = hospital + clinic + other

    logger.info(
        "xkt010.aggregate n_features=%d total=%d hospital=%d clinic=%d other=%d",
        len(features),
        total,
        hospital,
        clinic,
        other,
    )

    return {
        "medical_facility_count": total if total > 0 else None,
        "medical_hospital_count": hospital if total > 0 else None,
        "medical_clinic_count": clinic if total > 0 else None,
    }
