"""プレスリリース RSS スクレイパー本体。

httpx async + feedparser で robust に RSS/Atom をパース。
レート制限: 自治体ごとに 1 sec 間隔 (国会 API と同じ紳士運用)。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from time import struct_time
from typing import TYPE_CHECKING

import httpx

from .schema import PressItem

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

USER_AGENT = "Citify-Hackathon/0.1 (+https://github.com/yujmatsu/citify)"
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_RATE_LIMIT_SEC = 1.0
MAX_RETRIES = 3


def _struct_time_to_dt(t: struct_time | None) -> datetime | None:
    """feedparser の time.struct_time (UTC) を timezone-aware datetime に。"""
    if t is None:
        return None
    try:
        # feedparser は published_parsed を UTC の struct_time で返す
        return datetime(*t[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _entry_id(entry: dict, fallback_url: str) -> str:
    """RSS entry から一意 ID を抽出。guid > id > link > hash の順。"""
    for key in ("guid", "id"):
        v = entry.get(key)
        if v:
            return str(v)
    link = entry.get("link")
    if link:
        return str(link)
    # 最終手段: title + pubDate のハッシュ
    raw = f"{entry.get('title', '')}|{entry.get('published', '')}|{fallback_url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _entry_to_press_item(
    entry: dict,
    *,
    municipality_code: str,
    source_url: str,
) -> PressItem:
    """feedparser の entry dict から PressItem を構築。"""
    pub_dt = _struct_time_to_dt(entry.get("published_parsed")) or _struct_time_to_dt(
        entry.get("updated_parsed")
    )
    # category: feedparser は tags リスト or category 文字列を返す
    category: str | None = None
    if entry.get("tags"):
        first = entry["tags"][0]
        if isinstance(first, dict):
            category = first.get("term") or first.get("label")
        else:
            category = str(first)
    elif entry.get("category"):
        category = str(entry["category"])

    return PressItem(
        id=_entry_id(entry, source_url),
        municipality_code=municipality_code,
        title=str(entry.get("title", "(無題)")).strip(),
        link=str(entry.get("link", "")),
        description=(entry.get("summary") or entry.get("description") or None),
        pub_date=pub_dt,
        category=category,
        source_url=source_url,
        fetched_at=datetime.now(UTC),
    )


class PressRssClient:
    """RSS/Atom フィードを取得 + feedparser でパース。

    Usage:
        async with PressRssClient() as c:
            items = await c.fetch_feed(
                rss_url="https://www.metro.tokyo.lg.jp/.../rss.xml",
                municipality_code="13000",
            )

    Args:
        timeout_sec: HTTP タイムアウト
        rate_limit_sec: 連続 fetch 間隔 (バッチ取得時に同一サーバに連打しない)
        transport: テスト用 (httpx.MockTransport)
    """

    def __init__(
        self,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
        rate_limit_sec: float = DEFAULT_RATE_LIMIT_SEC,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.timeout_sec = timeout_sec
        self.rate_limit_sec = rate_limit_sec
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
            timeout=timeout_sec,
            follow_redirects=True,
            transport=transport,
        )

    async def __aenter__(self) -> PressRssClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self._client.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_feed(
        self,
        rss_url: str,
        municipality_code: str,
        max_items: int | None = None,
    ) -> list[PressItem]:
        """RSS feed を取得して PressItem list を返す。

        Args:
            rss_url: RSS feed URL (https://...)
            municipality_code: 5 桁自治体コード
            max_items: 取得上限 (None で feed の全件)
        """
        content = await self._get_bytes(rss_url)

        # 遅延 import: テストで mock 注入時に feedparser 不要
        import feedparser

        feed = feedparser.parse(content)

        if getattr(feed, "bozo", False) and getattr(feed, "bozo_exception", None):
            logger.warning(
                "press_rss.bozo url=%s exc=%s entries=%d",
                rss_url,
                feed.bozo_exception,
                len(feed.entries),
            )

        entries = list(feed.entries)
        if max_items is not None:
            entries = entries[:max_items]

        items = [
            _entry_to_press_item(entry, municipality_code=municipality_code, source_url=rss_url)
            for entry in entries
        ]
        logger.info(
            "press_rss.fetch_done url=%s muni=%s n=%d (feed_title=%r)",
            rss_url,
            municipality_code,
            len(items),
            getattr(feed.feed, "title", "") if hasattr(feed, "feed") else "",
        )
        return items

    async def _get_bytes(self, url: str) -> bytes:
        """指定 URL を GET、retry 付きで bytes を返す。"""
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.get(url)
                response.raise_for_status()
                content = response.content
                await asyncio.sleep(self.rate_limit_sec)
                return content
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning(
                    "press_rss.retry attempt=%d/%d url=%s exc=%s",
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
            f"press_rss GET failed after {MAX_RETRIES} retries: {last_exc}"
        ) from last_exc
