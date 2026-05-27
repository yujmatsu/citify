"""Web メルカトル投影のタイル ID 計算 (mercantile 不要、自前)。

Reinfolib GIS API (XGT001/XPT002 等) は z/x/y タイル座標が必須なので、
緯度経度から該当タイルを計算するための最小実装。

参考: https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames
"""

from __future__ import annotations

import math


def lonlat_to_tile(lng: float, lat: float, z: int) -> tuple[int, int]:
    """緯度経度を z レベルのタイル X/Y に変換。

    Args:
        lng: 経度 (例: 139.7029)
        lat: 緯度 (例: 35.5308)
        z: ズームレベル (XGT001 は 11-15、XPT002 は 13-15)

    Returns:
        (x, y) タイル座標
    """
    n = 2**z
    x = int((lng + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


def tiles_around(lng: float, lat: float, z: int, radius: int = 1) -> list[tuple[int, int]]:
    """指定座標を中心に ±radius 個のタイルを返す (3x3=9 / 5x5=25 等)。

    自治体の代表座標が中心の場合、その周辺タイルを取得することで
    自治体全域をカバーできる (z=11 で radius=1 なら 9 タイル = ~36km四方)。

    Args:
        lng: 経度
        lat: 緯度
        z: ズームレベル
        radius: 中心タイルから何個拡張するか (1 = 3x3, 2 = 5x5)
    """
    cx, cy = lonlat_to_tile(lng, lat, z)
    return [
        (cx + dx, cy + dy) for dx in range(-radius, radius + 1) for dy in range(-radius, radius + 1)
    ]
