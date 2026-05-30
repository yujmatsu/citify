"""press_rss スクレイパーのテスト (fixture RSS XML + httpx.MockTransport)。"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from scrapers.press_rss.client import (
    PressRssClient,
    _absolutize_url,
    _entry_id,
    _entry_to_press_item,
    _struct_time_to_dt,
)
from scrapers.press_rss.schema import SOURCE_NAME, PressItem

# ============================================================================
# Helpers
# ============================================================================

_FIXTURE_RSS_2_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>港区 新着情報</title>
    <link>https://www.city.minato.tokyo.jp/</link>
    <description>港区公式 RSS</description>
    <language>ja</language>
    <item>
      <title>令和8年度予算案を公表しました</title>
      <link>https://www.city.minato.tokyo.jp/news/r8_budget.html</link>
      <description>港区の令和8年度予算案 (一般会計総額 1,500 億円) について</description>
      <pubDate>Tue, 15 Apr 2026 09:00:00 +0900</pubDate>
      <category>お知らせ</category>
      <guid>https://www.city.minato.tokyo.jp/news/r8_budget.html</guid>
    </item>
    <item>
      <title>子育て支援センターの新設について</title>
      <link>https://www.city.minato.tokyo.jp/news/childcare.html</link>
      <description>新設予定の子育て支援センター 3 拠点</description>
      <pubDate>Mon, 14 Apr 2026 10:30:00 +0900</pubDate>
      <category>子育て</category>
      <guid>https://www.city.minato.tokyo.jp/news/childcare.html</guid>
    </item>
  </channel>
</rss>
"""
FIXTURE_RSS_2 = _FIXTURE_RSS_2_TEMPLATE.encode("utf-8")

_FIXTURE_ATOM_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>札幌市議会 お知らせ</title>
  <link href="https://www.city.sapporo.jp/gikai/" />
  <updated>2026-04-15T09:00:00+09:00</updated>
  <id>tag:city.sapporo.jp,2026:gikai/feed</id>
  <entry>
    <title>令和8年第1回定例会のお知らせ</title>
    <link href="https://www.city.sapporo.jp/gikai/teireikai.html" />
    <id>tag:city.sapporo.jp,2026:gikai/teireikai-r8-1</id>
    <updated>2026-04-15T09:00:00+09:00</updated>
    <summary>令和8年第1回定例会の日程について</summary>
    <category term="議会"/>
  </entry>
</feed>
"""
FIXTURE_ATOM = _FIXTURE_ATOM_TEMPLATE.encode("utf-8")


def _make_transport(body_bytes: bytes, *, content_type: str = "application/rss+xml"):
    """fixture を 200 OK で返す MockTransport。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body_bytes, headers={"content-type": content_type})

    return httpx.MockTransport(handler)


# ============================================================================
# Schema
# ============================================================================


def test_source_name_constant():
    assert SOURCE_NAME == "press_rss"


def test_press_item_minimal():
    item = PressItem(
        id="abc",
        municipality_code="13103",
        title="t",
        link="https://x",
        source_url="https://x/rss.xml",
        fetched_at=datetime(2026, 4, 15, tzinfo=UTC),
    )
    assert item.description is None
    assert item.pub_date is None
    assert item.category is None


# ============================================================================
# struct_time → datetime
# ============================================================================


def test_struct_time_to_dt_returns_utc():
    import time

    t = time.struct_time((2026, 4, 15, 9, 0, 0, 0, 0, 0))
    dt = _struct_time_to_dt(t)
    assert dt == datetime(2026, 4, 15, 9, 0, 0, tzinfo=UTC)


def test_struct_time_to_dt_none():
    assert _struct_time_to_dt(None) is None


# ============================================================================
# Entry ID 抽出
# ============================================================================


def test_entry_id_prefers_guid():
    entry = {"guid": "g-123", "id": "i-456", "link": "https://x"}
    assert _entry_id(entry, "https://feed.xml") == "g-123"


def test_entry_id_falls_back_to_id():
    entry = {"id": "i-456", "link": "https://x"}
    assert _entry_id(entry, "https://feed.xml") == "i-456"


def test_entry_id_falls_back_to_link():
    entry = {"link": "https://x"}
    assert _entry_id(entry, "https://feed.xml") == "https://x"


def test_entry_id_falls_back_to_hash():
    entry = {"title": "t", "published": "2026"}
    eid = _entry_id(entry, "https://feed.xml")
    assert len(eid) == 32  # sha256[:32]
    assert eid.isalnum()


# ============================================================================
# Feed パース (RSS 2.0)
# ============================================================================


@pytest.mark.asyncio
async def test_fetch_feed_rss2_minato():
    transport = _make_transport(FIXTURE_RSS_2)
    async with PressRssClient(rate_limit_sec=0, transport=transport) as c:
        items = await c.fetch_feed(
            rss_url="https://www.city.minato.tokyo.jp/rss.xml",
            municipality_code="13103",
        )

    assert len(items) == 2
    assert items[0].title == "令和8年度予算案を公表しました"
    assert items[0].municipality_code == "13103"
    assert items[0].link == "https://www.city.minato.tokyo.jp/news/r8_budget.html"
    assert items[0].category == "お知らせ"
    # pubDate が UTC datetime に変換されていること
    assert items[0].pub_date is not None
    assert items[0].pub_date.tzinfo is not None
    assert items[1].category == "子育て"


@pytest.mark.asyncio
async def test_fetch_feed_max_items():
    transport = _make_transport(FIXTURE_RSS_2)
    async with PressRssClient(rate_limit_sec=0, transport=transport) as c:
        items = await c.fetch_feed(
            rss_url="https://x/rss.xml", municipality_code="13103", max_items=1
        )
    assert len(items) == 1


@pytest.mark.asyncio
async def test_fetch_feed_atom_sapporo():
    transport = _make_transport(FIXTURE_ATOM, content_type="application/atom+xml")
    async with PressRssClient(rate_limit_sec=0, transport=transport) as c:
        items = await c.fetch_feed(
            rss_url="https://www.city.sapporo.jp/gikai/feed.atom",
            municipality_code="01100",
        )
    assert len(items) == 1
    assert items[0].title == "令和8年第1回定例会のお知らせ"
    assert items[0].link == "https://www.city.sapporo.jp/gikai/teireikai.html"
    assert items[0].category == "議会"


@pytest.mark.asyncio
async def test_fetch_feed_empty():
    empty_rss = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>empty</title></channel></rss>'
    )
    transport = _make_transport(empty_rss)
    async with PressRssClient(rate_limit_sec=0, transport=transport) as c:
        items = await c.fetch_feed(rss_url="https://x", municipality_code="13103")
    assert items == []


@pytest.mark.asyncio
async def test_fetch_feed_fetched_at_is_recent():
    transport = _make_transport(FIXTURE_RSS_2)
    before = datetime.now(UTC)
    async with PressRssClient(rate_limit_sec=0, transport=transport) as c:
        items = await c.fetch_feed(rss_url="https://x", municipality_code="13103")
    after = datetime.now(UTC)
    assert before <= items[0].fetched_at <= after


# ============================================================================
# _entry_to_press_item
# ============================================================================


def test_entry_to_press_item_fills_defaults():
    entry = {"title": "t", "link": "https://x/news/1", "tags": [{"term": "お知らせ"}]}
    item = _entry_to_press_item(entry, municipality_code="13103", source_url="https://x/rss")
    assert item.title == "t"
    assert item.category == "お知らせ"
    assert item.municipality_code == "13103"
    assert item.pub_date is None  # 提供なし


# ============================================================================
# detail_url normalize (相対 URL → 絶対 URL)
# ============================================================================


def test_absolutize_url_relative_path():
    """相対 path は base_url で絶対化される。"""
    result = _absolutize_url("/news/1.html", "https://example.lg.jp/rss.xml")
    assert result == "https://example.lg.jp/news/1.html"


def test_absolutize_url_already_absolute_unchanged():
    """既に絶対 URL ならそのまま返す。"""
    result = _absolutize_url("https://other.com/news", "https://example.lg.jp/rss.xml")
    assert result == "https://other.com/news"


def test_absolutize_url_protocol_relative():
    """`//host/path` のような protocol-relative も base のスキームで補完。"""
    result = _absolutize_url("//other.host/news/2.html", "https://example.lg.jp/rss.xml")
    assert result == "https://other.host/news/2.html"


def test_absolutize_url_empty_returns_empty():
    """空文字 → 空文字 (urljoin は base を返すので明示的に空に)。"""
    assert _absolutize_url("", "https://example.lg.jp/rss.xml") == ""


def test_absolutize_url_relative_dot_path():
    """`./news/1.html` のような同一ディレクトリ参照も解決。"""
    result = _absolutize_url("./news/1.html", "https://example.lg.jp/feed/rss.xml")
    assert result == "https://example.lg.jp/feed/news/1.html"


@pytest.mark.asyncio
async def test_fetch_feed_normalizes_relative_links_in_publish_payload():
    """RSS に相対 URL の <link> がある場合、PressItem.link は絶対 URL になる (detail_url normalize)。"""
    relative_rss = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<rss version="2.0"><channel>'
        b"<title>x</title><link>https://example.lg.jp/</link><description>x</description>"
        b"<item>"
        b"<title>news_with_relative_link</title>"
        b"<link>/news/relative-path.html</link>"
        b"<guid>news_1</guid>"
        b"</item>"
        b"</channel></rss>"
    )
    client = PressRssClient(rate_limit_sec=0.0, transport=_make_transport(relative_rss))
    try:
        items = await client.fetch_feed("https://example.lg.jp/rss.xml", municipality_code="13103")
    finally:
        await client.aclose()

    assert len(items) == 1
    assert items[0].link == "https://example.lg.jp/news/relative-path.html"
    # source_url はそのまま absolute
    assert items[0].source_url == "https://example.lg.jp/rss.xml"


# ============================================================================
# UA / SSL fallback (9 自治体 SSL/403 対応)
# ============================================================================


def test_user_agent_is_browser_compatible():
    """User-Agent が `Mozilla/5.0` prefix で始まる (一部自治体 UA フィルタ対応)。"""
    from scrapers.press_rss.client import USER_AGENT

    assert USER_AGENT.startswith("Mozilla/5.0"), (
        "東村山市 13213 のような UA フィルタ自治体に 403 されないよう、ブラウザ互換 prefix が必須"
    )
    assert "CitifyBot" in USER_AGENT  # bot 名乗りも維持


def test_is_ssl_verification_error_detects_hostname_mismatch():
    """`_is_ssl_verification_error` が hostname mismatch 文言を検出。"""
    from scrapers.press_rss.client import _is_ssl_verification_error

    # 実 publish-all で観測された文言
    exc = httpx.ConnectError(
        "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
        "Hostname mismatch, certificate is not valid for 'example.lg.jp'."
    )
    assert _is_ssl_verification_error(exc) is True


def test_is_ssl_verification_error_detects_no_alt_certificate():
    from scrapers.press_rss.client import _is_ssl_verification_error

    exc = httpx.ConnectError("SSL: no alternative certificate subject name matches")
    assert _is_ssl_verification_error(exc) is True


def test_is_ssl_verification_error_returns_false_for_403():
    """SSL 系判定が他エラー (403 等) を誤検出しない。"""
    from scrapers.press_rss.client import _is_ssl_verification_error

    exc = httpx.HTTPStatusError(
        "Client error '403 Forbidden'",
        request=httpx.Request("GET", "https://x/"),
        response=httpx.Response(403),
    )
    assert _is_ssl_verification_error(exc) is False


def test_is_ssl_verification_error_returns_false_for_timeout():
    from scrapers.press_rss.client import _is_ssl_verification_error

    exc = httpx.ConnectTimeout("timed out")
    assert _is_ssl_verification_error(exc) is False


@pytest.mark.asyncio
async def test_fetch_feed_falls_back_to_insecure_on_ssl_error(monkeypatch):
    """SSL hostname mismatch エラー → verify=False の insecure client で 1 回 fallback して成功。"""
    call_counts: dict[str, int] = {"primary": 0, "insecure": 0}

    def primary_handler(request: httpx.Request) -> httpx.Response:
        call_counts["primary"] += 1
        # 実 publish-all で観測された SSL hostname mismatch 例外を投げる
        raise httpx.ConnectError(
            "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
            "Hostname mismatch, certificate is not valid for 'example.lg.jp'.",
        )

    def insecure_handler(request: httpx.Request) -> httpx.Response:
        call_counts["insecure"] += 1
        return httpx.Response(
            200,
            content=FIXTURE_RSS_2,
            headers={"content-type": "application/rss+xml"},
        )

    primary_transport = httpx.MockTransport(primary_handler)
    insecure_transport = httpx.MockTransport(insecure_handler)

    client = PressRssClient(rate_limit_sec=0.0, transport=primary_transport)
    # insecure client を内部 attribute 経由で test 用の MockTransport にすり替え
    client._insecure_client = httpx.AsyncClient(
        headers=client._headers,
        timeout=client.timeout_sec,
        follow_redirects=True,
        transport=insecure_transport,
    )

    try:
        items = await client.fetch_feed(
            "https://example.lg.jp/rss.xml", municipality_code="06203", max_items=2
        )
    finally:
        await client.aclose()

    # primary は 1 回 (SSL error)、insecure で 1 回成功
    assert call_counts["primary"] == 1
    assert call_counts["insecure"] == 1
    assert len(items) == 2  # FIXTURE_RSS_2 の 2 item


@pytest.mark.asyncio
async def test_fetch_feed_does_not_fallback_for_non_ssl_error(monkeypatch):
    """非 SSL エラー (e.g. 403) は insecure fallback されず通常 retry で 3 回試行して失敗。"""
    call_counts: dict[str, int] = {"primary": 0}

    def primary_handler(request: httpx.Request) -> httpx.Response:
        call_counts["primary"] += 1
        return httpx.Response(403)  # raise_for_status() で HTTPStatusError

    client = PressRssClient(rate_limit_sec=0.0, transport=httpx.MockTransport(primary_handler))
    try:
        with pytest.raises(RuntimeError, match="after 3 retries"):
            await client.fetch_feed(
                "https://x.lg.jp/rss.xml", municipality_code="13213", max_items=2
            )
    finally:
        await client.aclose()

    # 通常 retry で 3 回試行 (insecure fallback 発動なし)
    assert call_counts["primary"] == 3
