"""XKT013 将来推計人口 250m メッシュ → 自治体集計。

入力: client.fetch_geojson_tiles("XKT013", lng, lat, z=11, radius=...) の features
出力:
    - aggregate_population_series(features, shicode) → dict[int, int]  (推奨、TASK-POPTREND)
        SHICODE == 対象自治体のメッシュのみを各 PT00_YYYY 年次で合算した人口時系列
    - aggregate_future_population(features)  (旧・非推奨、TASK-POPFIX で BQ 投入経路から除外済)

TASK-POPTREND の核心:
    旧実装は z=11 3x3 タイル (~50km四方) の **全メッシュを SHICODE で絞らず合算**していたため、
    全国 88% で実人口の 2 倍超 (最悪 2870 倍) になっていた。SHICODE フィルタで対象自治体の
    メッシュだけを合算することで正しい人口になる (250m メッシュは SHICODE 属性を持つ)。

    カバレッジ注意: SHICODE フィルタは fetch された box 内メッシュにしか効かないため、
    広域自治体では呼び出し側で radius を十分大きく取り、自治体全域のメッシュを確保すること。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

# 旧実装が参照していた固定フィールド (aggregate_future_population 用に残置)
CURRENT_YEAR_FIELD = "PT00_2025"
FUTURE_YEAR_FIELD = "PT00_2050"
HITOKU_2025_FIELD = "HITOKU2025"
HITOKU_2050_FIELD = "HITOKU2050"

SHICODE_FIELD = "SHICODE"
# PT00_YYYY (YYYY 年男女計総人口) を動的検出するパターン
_PT00_YEAR_RE = re.compile(r"^PT00_(\d{4})$")


def _norm_code(value: Any) -> str:
    """市区町村コードを 5 桁ゼロ埋め文字列に正規化 (北海道 01xxx の先頭ゼロ落ち対策)。"""
    s = str(value).strip()
    # 小数や余分な装飾を除去 (int 由来の "1100" や "1100.0" を想定)
    if s.endswith(".0"):
        s = s[:-2]
    return s.zfill(5)


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def aggregate_population_series(
    features: list[dict[str, Any]],
    target_shicode: str | Iterable[str],
) -> dict[int, int]:
    """SHICODE が target に一致するメッシュのみを各 PT00_YYYY 年次で合算した人口時系列を返す。

    Args:
        features: XKT013 GeoJSON features
        target_shicode: 対象自治体コード。単一 (例 "13104") または複数 (政令市の区コード集合、
            例 {"01101", ..., "01110"} で札幌市)。Phase 0 検証で判明: 250m メッシュの SHICODE は
            政令市の **区コード** であり親コード (XX100) のメッシュは存在しないため、政令市は
            区コード集合を渡して合算する。

    Returns:
        {year: population} (year 昇順)。秘匿 (HITOKU{year}=1) のメッシュは当該年で除外。
        一致 SHICODE のメッシュが無ければ空 dict。
    """
    if isinstance(target_shicode, str):
        targets = {_norm_code(target_shicode)}
    else:
        targets = {_norm_code(c) for c in target_shicode}
    totals: dict[int, int] = {}

    for f in features:
        props = (f or {}).get("properties", {}) or {}
        if _norm_code(props.get(SHICODE_FIELD)) not in targets:
            continue
        # この feature が持つ PT00_YYYY 年次を動的に検出
        for key, raw in props.items():
            m = _PT00_YEAR_RE.match(str(key))
            if not m:
                continue
            year = int(m.group(1))
            # 秘匿フラグ (HITOKU{year}) が 1 のメッシュは当該年除外
            if props.get(f"HITOKU{year}") == 1:
                continue
            pop = _to_int(raw)
            if pop is None:
                continue
            totals[year] = totals.get(year, 0) + pop

    series = dict(sorted(totals.items()))
    logger.info(
        "xkt013.series shicodes=%s years=%s",
        sorted(targets),
        list(series.keys()),
    )
    return series


def _sum_population(features: list[dict[str, Any]], field: str, hitoku_field: str) -> int:
    """指定 field の人口値を合算。秘匿 (HITOKU=1) は除外。(旧実装用)"""
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
