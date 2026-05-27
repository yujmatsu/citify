"""XKT013 将来推計人口 250m メッシュ → 自治体集計。

入力: client.fetch_geojson_tiles("XKT013", lng, lat, z=11, radius=1) の features
出力: dict[str, Any]
    - population_2025_estimated
    - population_2050_estimated
    - population_change_2025_2050_pct  (= (2050 - 2025) / 2025 * 100)

注意: 周辺地域 (z=11 3x3 タイル ~50km四方) のメッシュを合算するので、
本来の自治体ポリゴンとは厳密に一致しない。「Citify 集計値」として UI 表示。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

CURRENT_YEAR_FIELD = "PT00_2025"
FUTURE_YEAR_FIELD = "PT00_2050"
HITOKU_2025_FIELD = "HITOKU2025"
HITOKU_2050_FIELD = "HITOKU2050"


def _sum_population(features: list[dict[str, Any]], field: str, hitoku_field: str) -> int:
    """指定 field の人口値を合算。秘匿 (HITOKU=1) は除外。"""
    total = 0
    for f in features:
        props = (f or {}).get("properties", {})
        if props.get(hitoku_field) == 1:
            continue
        v = props.get(field)
        if v is None:
            continue
        try:
            total += int(float(v))
        except (ValueError, TypeError):
            continue
    return total


def aggregate_future_population(features: list[dict[str, Any]]) -> dict[str, Any]:
    """周辺地域メッシュから 2025/2050 年人口を集計。"""
    pop_2025 = _sum_population(features, CURRENT_YEAR_FIELD, HITOKU_2025_FIELD)
    pop_2050 = _sum_population(features, FUTURE_YEAR_FIELD, HITOKU_2050_FIELD)
    change_pct: float | None = (
        round((pop_2050 - pop_2025) / pop_2025 * 100.0, 2) if pop_2025 > 0 else None
    )

    logger.info(
        "xkt013.aggregate n_features=%d pop2025=%d pop2050=%d change=%s",
        len(features),
        pop_2025,
        pop_2050,
        change_pct,
    )

    return {
        "population_2025_estimated": pop_2025 if pop_2025 > 0 else None,
        "population_2050_estimated": pop_2050 if pop_2050 > 0 else None,
        "population_change_2025_2050_pct": change_pct,
    }
