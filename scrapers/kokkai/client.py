"""国会会議録 検索 API クライアント (httpx async + pagination + rate limit)。

- 認証不要、レート制限明示なし (推奨 1 秒以上)
- ページング: startRecord + maximumRecords (最大 100/page)
- 失敗時 exponential backoff (最大 3 回)
- User-Agent ヘッダで連絡先を明示 (DATA_SOURCES.md §0.2 準拠)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import date

import httpx

from .schema import SearchResponse, SpeechRecord

logger = logging.getLogger(__name__)

USER_AGENT = "Citify-Hackathon/0.1 (+https://github.com/yujmatsu/citify)"
BASE_URL = "https://kokkai.ndl.go.jp/api"
DEFAULT_RATE_LIMIT_SEC = 1.0
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_PAGE_SIZE = 30  # API max=100、レート制限とのバランスで 30
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 1.0


class KokkaiClient:
    """国会会議録 API クライアント。

    Args:
        base_url: API ベース URL (テスト時にモックサーバへ向けるため上書き可能)
        user_agent: User-Agent ヘッダ値 (倫理: 連絡先を含める)
        rate_limit_sec: ページ間の最小待機秒数 (default 1.0、test は 0 推奨)
        timeout_sec: HTTP タイムアウト
        transport: httpx の transport (テスト時に httpx.MockTransport を注入)
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        user_agent: str = USER_AGENT,
        rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.rate_limit_sec = rate_limit_sec
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent},
            timeout=timeout_sec,
            transport=transport,
        )

    async def __aenter__(self) -> KokkaiClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_speeches(
        self,
        from_date: date,
        until_date: date,
        keyword: str | None = None,
        speaker: str | None = None,
        name_of_house: str | None = None,
        name_of_meeting: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_total: int | None = None,
    ) -> AsyncIterator[SpeechRecord]:
        """期間内の発言を非同期 generator で yield する。

        Args:
            from_date: 取得開始日 (含む)
            until_date: 取得終了日 (含む)
            keyword: フリーキーワード絞り込み (API `any` パラメタ)
            speaker: 発言者名で絞り込み
            name_of_house: 衆議院 / 参議院 で絞り込み
            name_of_meeting: 本会議 / 予算委員会 等で絞り込み
            page_size: 1 ページあたり取得件数 (1-100、default 30)
            max_total: 取得上限件数 (None なら全件)

        Yields:
            SpeechRecord: 発言レコード (Pydantic でバリデート済)

        Raises:
            RuntimeError: 全リトライが失敗した場合
        """
        if not 1 <= page_size <= 100:
            raise ValueError(f"page_size must be 1-100, got {page_size}")
        if from_date > until_date:
            raise ValueError(f"from_date ({from_date}) > until_date ({until_date})")

        start = 1
        yielded = 0

        while True:
            params: dict[str, object] = {
                "recordPacking": "json",
                "from": from_date.isoformat(),
                "until": until_date.isoformat(),
                "maximumRecords": page_size,
                "startRecord": start,
            }
            if keyword:
                params["any"] = keyword
            if speaker:
                params["speaker"] = speaker
            if name_of_house:
                params["nameOfHouse"] = name_of_house
            if name_of_meeting:
                params["nameOfMeeting"] = name_of_meeting

            data = await self._get_with_retry(f"{self.base_url}/speech", params)
            response = SearchResponse.model_validate(data)

            logger.info(
                "kokkai.fetch_page start=%d returned=%d total=%d next=%s",
                response.start_record,
                response.number_of_return,
                response.number_of_records,
                response.next_record_position,
            )

            for record in response.speech_record:
                yield record
                yielded += 1
                if max_total is not None and yielded >= max_total:
                    return

            # 次ページ判定: nextRecordPosition が None / 0 / 欠落なら終了
            if not response.next_record_position or response.number_of_return == 0:
                return

            start = response.next_record_position
            await asyncio.sleep(self.rate_limit_sec)

    async def _get_with_retry(
        self,
        url: str,
        params: dict[str, object],
    ) -> dict:
        """GET リクエスト + exponential backoff (1s → 2s → 4s)。"""
        delay = INITIAL_BACKOFF_SEC
        last_exc: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "kokkai.retry attempt=%d/%d url=%s exc=%s",
                    attempt,
                    MAX_RETRIES,
                    url,
                    exc,
                )
                if attempt == MAX_RETRIES:
                    break
                await asyncio.sleep(delay)
                delay *= 2

        raise RuntimeError(
            f"kokkai API failed after {MAX_RETRIES} retries: {last_exc}"
        ) from last_exc
