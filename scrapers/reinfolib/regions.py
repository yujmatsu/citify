"""日本の地方区分 (8 region + 北陸を分離した 9 region 版) — 都道府県コード prefix のマッピング。

ローカル + Colab で並行実行する際、地方単位でジョブを分割して
重複なく Reinfolib バッチを進めるための辞書。

順番:
    1. hokkaido_tohoku  — 北海道・東北 (7 県)
    2. kanto            — 関東 (7 都県)
    3. koshinetsu       — 甲信越 (3 県、新潟・山梨・長野)
    4. hokuriku         — 北陸 (3 県、富山・石川・福井)
    5. tokai            — 東海 (4 県、岐阜・静岡・愛知・三重)
    6. kinki            — 近畿 (6 府県)
    7. chugoku          — 中国 (5 県)
    8. shikoku          — 四国 (4 県)
    9. kyushu_okinawa   — 九州・沖縄 (8 県)

各値は都道府県コード 2 桁 (01-47) の list。
"""

from __future__ import annotations

REGION_MAP: dict[str, list[str]] = {
    "hokkaido_tohoku": ["01", "02", "03", "04", "05", "06", "07"],
    "kanto": ["08", "09", "10", "11", "12", "13", "14"],
    "koshinetsu": ["15", "19", "20"],
    "hokuriku": ["16", "17", "18"],
    "tokai": ["21", "22", "23", "24"],
    "kinki": ["25", "26", "27", "28", "29", "30"],
    "chugoku": ["31", "32", "33", "34", "35"],
    "shikoku": ["36", "37", "38", "39"],
    "kyushu_okinawa": ["40", "41", "42", "43", "44", "45", "46", "47"],
}

REGION_LABELS: dict[str, str] = {
    "hokkaido_tohoku": "北海道・東北",
    "kanto": "関東",
    "koshinetsu": "甲信越",
    "hokuriku": "北陸",
    "tokai": "東海",
    "kinki": "近畿",
    "chugoku": "中国",
    "shikoku": "四国",
    "kyushu_okinawa": "九州・沖縄",
}


def list_regions() -> list[str]:
    """全 region 名を順序通り (北→南) で返す。"""
    return list(REGION_MAP.keys())


def is_in_region(municipality_code: str, region: str) -> bool:
    """municipality_code (5 桁) が指定 region に属するか判定。"""
    if region not in REGION_MAP:
        raise ValueError(f"unknown region: {region!r}. valid={list_regions()}")
    prefix = (municipality_code or "")[:2]
    return prefix in REGION_MAP[region]
