"""XGT001 指定緊急避難場所レスポンスを municipality_stats 列に集計。

入力: client.fetch_shelters_around() で取れた GeoJSON features list
出力: dict[str, Any]
    - emergency_shelter_count            自治体周辺 (3x3 タイル z=11) の避難所数
    - emergency_shelter_official_link    国土地理院ハザードマップポータル URL
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def aggregate_shelters(
    features: list[dict[str, Any]],
    center_lat: float,
    center_lng: float,
) -> dict[str, Any]:
    """避難所 features を集計。

    本来は自治体ポリゴン内のみカウントすべきだが、ハッカソンスコープでは
    「自治体中心周辺タイル (z=11、3x3 ≈ 36km四方)」の合計をそのまま採用。
    結果として隣接市の避難所も含まれるが、「街全体の防災レイヤー充実度」
    を粗く示す指標として使う (倫理ガード UI で「Citify 集計値」と明示)。

    Args:
        features: GeoJSON Feature list (XGT001 レスポンス)
        center_lat / center_lng: 自治体中心座標 (ハザードマップ link 用)

    Returns:
        {
            'emergency_shelter_count': int,
            'emergency_shelter_official_link': str,  # 国土地理院ポータル
        }
    """
    # XGT001 features は { "type": "Feature", "properties": {...}, "geometry": {...} }
    count = sum(1 for f in features if isinstance(f, dict) and f.get("type") == "Feature")

    # 国土地理院ハザードマップポータルサイトの自治体検索 URL
    # 中心座標 + z=12 で開く (各自治体の表示)
    portal_url = (
        f"https://disaportal.gsi.go.jp/hazardmapportal/hazardmap/maps/index.html"
        f"?ll={center_lat},{center_lng}&z=12"
    )

    logger.info(
        "xgt001.aggregate n_features=%d count=%d center=(%.4f,%.4f)",
        len(features),
        count,
        center_lat,
        center_lng,
    )

    return {
        "emergency_shelter_count": count,
        "emergency_shelter_official_link": portal_url,
    }
