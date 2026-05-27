"""XKT007 保育園・幼稚園 → 自治体集計。

入力: client.fetch_geojson_tiles("XKT007", lng, lat, z=13, radius=2) の features
出力:
    - childcare_facility_count   自治体内の合計施設数
    - kindergarten_count          うち幼稚園
    - nursery_count               うち保育園・認定こども園

特徴: features.properties.administrativeAreaCode に自治体コード (5桁) があるので、
**周辺地域全体ではなく、対象自治体のみ正確にフィルタ可能**。

注意: 政令市の場合、子区コード (XX1NN) で集計されるので、政令市親 (XX100) を
渡すと結果が 0 になる可能性。fetch_one 側で区コード合算する設計を推奨。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

KINDERGARTEN_NAME = "幼稚園"


def aggregate_childcare(
    features: list[dict[str, Any]],
    municipality_code: str | None = None,
) -> dict[str, Any]:
    """保育園・幼稚園の集計。

    Args:
        features: XKT007 GeoJSON features
        municipality_code: 指定時は administrativeAreaCode で完全一致のものだけ採用
    """
    seen: set[str] = set()
    kindergarten = 0
    nursery = 0
    for f in features:
        props = (f or {}).get("properties", {})
        admin_code = str(props.get("administrativeAreaCode") or "").strip()
        if municipality_code and admin_code != municipality_code:
            continue
        name = props.get("preSchoolName_ja") or ""
        if not name or name in seen:
            continue
        seen.add(name)
        kind_label = props.get("schoolClassCode_name_ja") or ""
        if KINDERGARTEN_NAME in kind_label:
            kindergarten += 1
        else:
            # 保育園・認定こども園・その他は nursery にまとめる (ハッカソンスコープ)
            nursery += 1
    total = kindergarten + nursery

    logger.info(
        "xkt007.aggregate code=%s n_features=%d total=%d kindergarten=%d nursery=%d",
        municipality_code,
        len(features),
        total,
        kindergarten,
        nursery,
    )

    return {
        "childcare_facility_count": total if total > 0 else None,
        "kindergarten_count": kindergarten if total > 0 else None,
        "nursery_count": nursery if total > 0 else None,
    }
