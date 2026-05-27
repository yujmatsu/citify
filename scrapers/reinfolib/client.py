"""Reinfolib (不動産情報ライブラリ) API クライアント。

Phase F v0.3.2 採用:
    - XIT001 不動産取引価格 (city= / area= / 政令市区合算 の hybrid)
    - XGT001 指定緊急避難場所 (z=11 タイル処理)

仕様書: docs/PHASE_F_REINFOLIB_v0.3.1.md (+ v0.3.2 patch in progress)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from .tile_utils import tiles_around

logger = logging.getLogger(__name__)

API_BASE = "https://www.reinfolib.mlit.go.jp/ex-api/external"
DEFAULT_RATE_LIMIT_SEC = 1.0
DEFAULT_TIMEOUT_SEC = 30.0


class ReinfolibClient:
    """同期 httpx + Ocp-Apim-Subscription-Key + rate_limit。

    Args:
        api_key: Reinfolib API キー (環境変数 REINFOLIB_API_KEY で渡すことを推奨)
        rate_limit_sec: 連続リクエスト間隔 (Reinfolib 利用規約)
    """

    def __init__(
        self,
        api_key: str | None = None,
        rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ):
        self.api_key = api_key or os.getenv("REINFOLIB_API_KEY")
        if not self.api_key:
            raise ValueError(
                "REINFOLIB_API_KEY is not set. Set environment variable or pass api_key argument."
            )
        self.rate_limit_sec = rate_limit_sec
        self.timeout_sec = timeout_sec
        self._last_call_ts = 0.0
        self._client = httpx.Client(timeout=timeout_sec)

    def __enter__(self) -> ReinfolibClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self._client.close()

    def close(self) -> None:
        self._client.close()

    def _rate_limit(self) -> None:
        """前回 call から rate_limit_sec 経過するまで sleep。"""
        elapsed = time.monotonic() - self._last_call_ts
        if elapsed < self.rate_limit_sec:
            time.sleep(self.rate_limit_sec - elapsed)
        self._last_call_ts = time.monotonic()

    def _call(self, api_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """Reinfolib API 1 call。失敗時は例外。"""
        self._rate_limit()
        url = f"{API_BASE}/{api_id}"
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        res = self._client.get(url, params=params, headers=headers)
        if res.status_code != 200:
            raise ReinfolibAPIError(
                f"{api_id} returned {res.status_code}: {res.text[:300]}",
                status_code=res.status_code,
                api_id=api_id,
                params=params,
            )
        return res.json()

    # ------------------------------------------------------------------
    # XIT001 — 不動産取引価格 (hybrid: city / area / 政令市区合算)
    # ------------------------------------------------------------------

    def fetch_trades(
        self,
        method: str,
        param: str,
        year: int = 2024,
        quarter: int = 3,
    ) -> list[dict[str, Any]]:
        """XIT001 取引価格データ取得。

        Args:
            method: "city" / "area" / "city_sum" のいずれか
            param: method に応じた値
                - city: 市区町村コード 5 桁 (例: "13104" 新宿区)
                - area: 都道府県コード 2 桁 (例: "14" 神奈川県)
                - city_sum: "01101-01110" 形式 (政令市の区コード範囲)
            year: 取引年 (default 2024)
            quarter: 四半期 (default 3)

        Returns:
            取引データの list (全件)
        """
        if method == "city":
            return self._fetch_trades_one({"city": param, "year": year, "quarter": quarter})
        if method == "area":
            return self._fetch_trades_one({"area": param, "year": year, "quarter": quarter})
        if method == "city_sum":
            # "01101-01110" を 01101..01110 に展開して各 city= で fetch
            start_str, end_str = param.split("-")
            start_int, end_int = int(start_str), int(end_str)
            all_records: list[dict[str, Any]] = []
            for code_int in range(start_int, end_int + 1):
                code = f"{code_int:05d}"
                try:
                    records = self._fetch_trades_one(
                        {"city": code, "year": year, "quarter": quarter}
                    )
                    all_records.extend(records)
                except ReinfolibAPIError as exc:
                    # 404 はその区にデータがないだけなので継続
                    if exc.status_code == 404:
                        logger.info("reinfolib.xit001.skip city=%s status=404", code)
                        continue
                    raise
            return all_records
        raise ValueError(f"unknown method: {method!r}, expected city/area/city_sum")

    def _fetch_trades_one(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        """XIT001 を 1 リクエスト分 fetch。"""
        body = self._call("XIT001", params)
        records = body.get("data", []) if isinstance(body, dict) else []
        logger.info(
            "reinfolib.xit001.fetch_done params=%s n=%d",
            params,
            len(records),
        )
        return records

    def fetch_trades_4quarters(
        self,
        method: str,
        param: str,
        latest_year: int = 2024,
    ) -> list[dict[str, Any]]:
        """過去 4 四半期 (1 年分) の取引データを集約。

        中央値計算用の十分なサンプル数を確保。
        """
        all_records: list[dict[str, Any]] = []
        for offset in range(4):
            year = latest_year - (offset // 4)
            quarter = 4 - (offset % 4)
            try:
                records = self.fetch_trades(method, param, year=year, quarter=quarter)
                all_records.extend(records)
            except ReinfolibAPIError as exc:
                logger.warning(
                    "reinfolib.xit001.quarter_failed method=%s param=%s y=%d q=%d err=%s",
                    method,
                    param,
                    year,
                    quarter,
                    exc,
                )
        return all_records

    # ------------------------------------------------------------------
    # XGT001 — 指定緊急避難場所 (z=11 タイル処理)
    # ------------------------------------------------------------------

    def fetch_shelters_around(
        self,
        center_lng: float,
        center_lat: float,
        z: int = 11,
        radius: int = 1,
    ) -> list[dict[str, Any]]:
        """自治体中心座標の周辺 (3x3 タイル = z=11 で ~36km四方) で避難所を取得。

        Args:
            center_lng: 自治体中心経度
            center_lat: 自治体中心緯度
            z: ズームレベル (XGT001 は 11-15)
            radius: 中心タイルから何個拡張するか (1 = 3x3)
        """
        tile_list = tiles_around(center_lng, center_lat, z, radius=radius)
        features: list[dict[str, Any]] = []
        for x, y in tile_list:
            params = {"response_format": "geojson", "z": z, "x": x, "y": y}
            try:
                body = self._call("XGT001", params)
            except ReinfolibAPIError as exc:
                # タイル内にデータなし (204 / 空 GeoJSON) も考慮
                if exc.status_code in (204, 404):
                    continue
                logger.warning("reinfolib.xgt001.tile_failed z=%d x=%d y=%d err=%s", z, x, y, exc)
                continue
            tile_features = body.get("features", []) if isinstance(body, dict) else []
            features.extend(tile_features)
        logger.info(
            "reinfolib.xgt001.fetch_done center=(%.4f,%.4f) z=%d tiles=%d n_features=%d",
            center_lat,
            center_lng,
            z,
            len(tile_list),
            len(features),
        )
        return features


class ReinfolibAPIError(Exception):
    """Reinfolib API 呼び出しエラー (4xx/5xx)。"""

    def __init__(
        self,
        message: str,
        status_code: int = 0,
        api_id: str = "",
        params: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.api_id = api_id
        self.params = params or {}
