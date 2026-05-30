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
from urllib.parse import urljoin

import httpx

from .schema import PressItem

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# User-Agent はブラウザ互換形式 + Bot 明示 (一部自治体サイトが厳格な UA フィルタを持つため、
# Mozilla 5.0 prefix がないと 403 を返す。例: 東村山市 13213)
USER_AGENT = "Mozilla/5.0 (compatible; CitifyBot/0.1; +https://github.com/yujmatsu/citify)"
DEFAULT_TIMEOUT_SEC = 30.0
DEFAULT_RATE_LIMIT_SEC = 1.0
MAX_RETRIES = 3

# 自治体サイトの SSL 証明書が SAN 不備 / 共有 SSL で hostname mismatch なケースが多発。
# このエラー文言を含む例外は 1 回限り verify=False で fallback する (warning ログ付き)。
_SSL_VERIFY_ERROR_MARKERS = (
    "CERTIFICATE_VERIFY_FAILED",
    "Hostname mismatch",
    "no alternative certificate",
)


def _is_ssl_verification_error(exc: Exception) -> bool:
    """httpx の SSL verification 失敗を文字列ベースで判定。"""
    s = str(exc)
    return any(marker in s for marker in _SSL_VERIFY_ERROR_MARKERS)


def _struct_time_to_dt(t: struct_time | None) -> datetime | None:
    """feedparser の time.struct_time (UTC) を timezone-aware datetime に。"""
    if t is None:
        return None
    try:
        # feedparser は published_parsed を UTC の struct_time で返す
        return datetime(*t[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def _absolutize_url(maybe_relative: str, base_url: str) -> str:
    """相対 URL を絶対 URL に変換。

    feedparser は相対 URL (`/news/1.html`) を自動で絶対化しないため、
    publish 前にここで正規化する。空文字や絶対 URL はそのまま返す。

    Examples:
        >>> _absolutize_url("/news/1.html", "https://example.lg.jp/rss.xml")
        'https://example.lg.jp/news/1.html'
        >>> _absolutize_url("https://other.com/x", "https://example.lg.jp/rss.xml")
        'https://other.com/x'
        >>> _absolutize_url("", "https://example.lg.jp/rss.xml")
        ''
    """
    if not maybe_relative:
        return ""
    return urljoin(base_url, maybe_relative)


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

    # detail_url normalize: feedparser は相対 URL を自動絶対化しないため
    # source_url (RSS feed の URL) をベースに urljoin する。
    # 一部自治体 RSS で `/news/1.html` のような相対 link が観測されており、
    # publish 時に絶対 URL でないと frontend クリック時に 404 になる。
    raw_link = str(entry.get("link", ""))
    absolute_link = _absolutize_url(raw_link, source_url)

    return PressItem(
        id=_entry_id(entry, source_url),
        municipality_code=municipality_code,
        title=str(entry.get("title", "(無題)")).strip(),
        link=absolute_link,
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
        self._headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        }
        self._transport = transport
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=timeout_sec,
            follow_redirects=True,
            transport=transport,
        )
        # SSL verify=False fallback 用 client (遅延初期化、自治体 SSL 不備対応専用)
        self._insecure_client: httpx.AsyncClient | None = None

    def _ensure_insecure_client(self) -> httpx.AsyncClient:
        """SSL verify=False fallback 用 client を遅延初期化。"""
        if self._insecure_client is None:
            self._insecure_client = httpx.AsyncClient(
                headers=self._headers,
                timeout=self.timeout_sec,
                follow_redirects=True,
                transport=self._transport,
                verify=False,
            )
        return self._insecure_client

    async def __aenter__(self) -> PressRssClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()
        if self._insecure_client is not None:
            await self._insecure_client.aclose()
            self._insecure_client = None

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
        """指定 URL を GET、retry 付きで bytes を返す。

        SSL verification 失敗 (自治体サイトの SAN 不備等) の場合のみ、
        1 回限り verify=False の insecure client で fallback (warning ログ付き)。
        """
        delay = 1.0
        last_exc: Exception | None = None
        tried_insecure_fallback = False

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.get(url)
                response.raise_for_status()
                content = response.content
                await asyncio.sleep(self.rate_limit_sec)
                return content
            except httpx.HTTPError as exc:
                last_exc = exc

                # SSL verification error は 1 回限り verify=False で fallback
                if _is_ssl_verification_error(exc) and not tried_insecure_fallback:
                    tried_insecure_fallback = True
                    logger.warning(
                        "press_rss.ssl_fallback url=%s exc=%s (verify=False で 1 回 retry)",
                        url,
                        exc,
                    )
                    try:
                        insecure_client = self._ensure_insecure_client()
                        response = await insecure_client.get(url)
                        response.raise_for_status()
                        content = response.content
                        await asyncio.sleep(self.rate_limit_sec)
                        return content
                    except httpx.HTTPError as fb_exc:
                        last_exc = fb_exc
                        logger.warning(
                            "press_rss.ssl_fallback_failed url=%s exc=%s",
                            url,
                            fb_exc,
                        )

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
