"""XIT001 取引価格レスポンスを municipality_stats 列に集計。

入力: client.fetch_trades_4quarters() で取れた raw records (取引 1 件 = 1 dict)
出力: dict[str, Any] (BQ municipality_stats の列値)
    - used_apartment_median_price_man_yen
    - used_apartment_sample_size
    - used_apartment_median_unit_price_yen
    - used_apartment_avg_building_age
"""

from __future__ import annotations

import logging
import re
import statistics
from typing import Any

logger = logging.getLogger(__name__)

USED_APARTMENT_TYPE = "中古マンション等"
CURRENT_YEAR = 2024


def _parse_int(value: Any) -> int | None:
    """文字列/None から int を取り出す。"カンマ区切り/全角" を許容。"""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    s = str(value).replace(",", "").strip()
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _parse_building_year(value: Any) -> int | None:
    """'1981年' / '平成12年' / '令和2年' を西暦に変換。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # 西暦年
    m = re.match(r"(\d{4})年", s)
    if m:
        return int(m.group(1))
    # 平成
    m = re.match(r"平成(\d+)年", s)
    if m:
        return 1988 + int(m.group(1))
    # 令和
    m = re.match(r"令和(\d+)年", s)
    if m:
        return 2018 + int(m.group(1))
    # 昭和
    m = re.match(r"昭和(\d+)年", s)
    if m:
        return 1925 + int(m.group(1))
    return None


def aggregate_used_apartments(
    records: list[dict[str, Any]],
    current_year: int = CURRENT_YEAR,
) -> dict[str, Any]:
    """中古マンション等のみを抽出して中央値・サンプル数・築年数平均を計算。

    Args:
        records: XIT001 raw レコード list
        current_year: 築年数計算の基準年

    Returns:
        {
            'used_apartment_median_price_man_yen': int | None,  # 中央値 (万円)
            'used_apartment_sample_size': int,                    # サンプル数
            'used_apartment_median_unit_price_yen': int | None,   # ㎡単価中央値 (円/㎡)
            'used_apartment_avg_building_age': float | None,      # 築年数平均
        }
    """
    apts = [r for r in records if r.get("Type") == USED_APARTMENT_TYPE]
    prices: list[int] = []
    unit_prices: list[float] = []
    building_ages: list[int] = []

    for r in apts:
        price = _parse_int(r.get("TradePrice"))
        area = _parse_int(r.get("Area"))
        if price and price > 0:
            prices.append(price)
            if area and area > 0:
                unit_prices.append(price / area)
        bldg_year = _parse_building_year(r.get("BuildingYear"))
        if bldg_year and bldg_year > 1900:
            age = current_year - bldg_year
            if 0 <= age <= 120:
                building_ages.append(age)

    sample_size = len(prices)
    median_man_yen = int(statistics.median(prices) / 10000) if prices else None  # 円 → 万円
    median_unit_price = int(statistics.median(unit_prices)) if unit_prices else None
    avg_age = round(statistics.mean(building_ages), 1) if building_ages else None

    logger.info(
        "xit001.aggregate n_total=%d n_used_apt=%d median_man_yen=%s sample=%d",
        len(records),
        len(apts),
        median_man_yen,
        sample_size,
    )

    return {
        "used_apartment_median_price_man_yen": median_man_yen,
        "used_apartment_sample_size": sample_size,
        "used_apartment_median_unit_price_yen": median_unit_price,
        "used_apartment_avg_building_age": avg_age,
    }
