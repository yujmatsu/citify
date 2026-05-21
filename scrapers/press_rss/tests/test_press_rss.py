"""press_rss スクレイパーのテスト (fixture RSS XML + httpx.MockTransport)。"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from scrapers.press_rss.client import (
    PressRssClient,
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
