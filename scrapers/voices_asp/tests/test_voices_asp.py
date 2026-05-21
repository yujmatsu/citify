"""voices_asp スクレイパーのテスト (fixture HTML + httpx.MockTransport)。"""

from __future__ import annotations

from datetime import date

import httpx
import pytest

from scrapers.voices_asp.client import (
    CENTRAL_BASE_URL_TEMPLATE,
    VoicesAspClient,
    _extract_year_from_label,
    _parse_date_jp,
)
from scrapers.voices_asp.schema import MeetingSummary, Speech, YearEntry

# ============================================================================
# 日付パース
# ============================================================================


def test_parse_date_iso():
    assert _parse_date_jp("2026-04-15") == date(2026, 4, 15)
    assert _parse_date_jp("2026/04/15") == date(2026, 4, 15)
    assert _parse_date_jp("2026.04.15") == date(2026, 4, 15)


def test_parse_date_japanese():
    assert _parse_date_jp("2026年4月15日") == date(2026, 4, 15)
    assert _parse_date_jp("令和8年4月15日") == date(2026, 4, 15)
    assert _parse_date_jp("平成31年4月30日") == date(2019, 4, 30)


def test_parse_date_invalid_returns_none():
    assert _parse_date_jp(None) is None
    assert _parse_date_jp("invalid") is None


# ============================================================================
# 年度ラベル抽出
# ============================================================================


def test_year_from_label_western():
    assert _extract_year_from_label("2025年度") == 2025
    assert _extract_year_from_label("2026") == 2026


def test_year_from_label_reiwa():
    assert _extract_year_from_label("令和8年度") == 2026
    assert _extract_year_from_label("令和  7  年度") == 2025


def test_year_from_label_heisei():
    assert _extract_year_from_label("平成31年度") == 2019


def test_year_from_label_none_when_no_year():
    assert _extract_year_from_label("") is None
    assert _extract_year_from_label("会議録") is None


# ============================================================================
# URL 組み立て
# ============================================================================


def test_client_central_url_template():
    """tenant_id だけで中央型 URL を構築。"""
    c = VoicesAspClient(tenant_id="sapporo")
    assert c.base_url == "https://sapporo.gijiroku.com/voices/"


def test_client_base_url_override_minato():
    c = VoicesAspClient(
        tenant_id="minato",
        base_url="https://gikai2.city.minato.tokyo.jp/voices",
    )
    assert c.base_url == "https://gikai2.city.minato.tokyo.jp/voices/"


def test_client_base_url_override_adachi_with_trailing():
    c = VoicesAspClient(
        tenant_id="adachi",
        base_url="https://www.gikai-adachi.jp/voices/",
    )
    assert c.base_url == "https://www.gikai-adachi.jp/voices/"


def test_template_constant_has_placeholder():
    assert "{tenant_id}" in CENTRAL_BASE_URL_TEMPLATE


# ============================================================================
# HTML fixture-based parse (Shift_JIS + BS4)
# ============================================================================

# voices_asp 風の年度一覧 HTML (recon doc §4 のセレクタ ul.kaigi_view を再現)
# Python 文字列で書き、.encode("shift_jis") で実 site と同じバイト列にする
_FIXTURE_YEAR_LIST_TEMPLATE = """<?xml version="1.0" encoding="shift_jis"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=shift_jis" />
<title>札幌市議会 会議録検索システム</title>
</head>
<body>
<div class="AreaContentsBase">
  <ul class="kaigi_view">
    <li><a href="g08v_viewh.asp?Sflg=11&amp;FYY=2026&amp;TYY=2026">2026年度</a></li>
    <li><a href="g08v_viewh.asp?Sflg=11&amp;FYY=2025&amp;TYY=2025">2025年度</a></li>
    <li><a href="g08v_viewh.asp?Sflg=11&amp;FYY=2024&amp;TYY=2024">2024年度</a></li>
  </ul>
</div>
</body>
</html>
"""
FIXTURE_YEAR_LIST_HTML = _FIXTURE_YEAR_LIST_TEMPLATE.encode("shift_jis")


def _make_transport(html_bytes: bytes, *, content_type: str = "text/html; charset=shift_jis"):
    """1 リクエストに対して fixture HTML を返す MockTransport。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=html_bytes,
            headers={"content-type": content_type},
        )

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_fetch_year_list_parses_ul_kaigi_view():
    """ul.kaigi_view の <li><a> から YearEntry を抽出。"""
    transport = _make_transport(FIXTURE_YEAR_LIST_HTML)
    async with VoicesAspClient(tenant_id="sapporo", rate_limit_sec=0, transport=transport) as c:
        years = await c.fetch_year_list("honkai")
    assert len(years) == 3
    assert all(isinstance(y, YearEntry) for y in years)
    # FYY=2026 / 2025 / 2024 抽出
    assert [y.year for y in years] == [2026, 2025, 2024]
    # detail_url に Sflg=11 が含まれる
    assert "Sflg=11" in years[0].detail_url
    assert "FYY=2026" in years[0].detail_url


@pytest.mark.asyncio
async def test_fetch_year_list_empty_when_no_match():
    """ul.kaigi_view も他セレクタも hit しない HTML で空 list。"""
    html = "<html><body><p>no year list here</p></body></html>".encode("shift_jis")
    transport = _make_transport(html)
    async with VoicesAspClient(tenant_id="sapporo", rate_limit_sec=0, transport=transport) as c:
        years = await c.fetch_year_list("honkai")
    assert years == []


@pytest.mark.asyncio
async def test_inspect_page_returns_metadata():
    transport = _make_transport(FIXTURE_YEAR_LIST_HTML)
    async with VoicesAspClient(tenant_id="sapporo", rate_limit_sec=0, transport=transport) as c:
        result = await c.inspect_page("g08v_viewh.asp")
    # 該当セレクタが候補に含まれる
    selectors = [c["selector"] for c in result["candidates"]]
    assert "ul.kaigi_view li a" in selectors
    # 該当セレクタの count > 0
    matched = [c for c in result["candidates"] if c["selector"] == "ul.kaigi_view li a"]
    assert matched[0]["count"] == 3
    assert result["html_length"] > 0


# ============================================================================
# Schema バリデーション
# ============================================================================


def test_meeting_summary_minimal():
    m = MeetingSummary(
        tenant_id="sapporo",
        council_id="123",
        name_of_meeting="第1回定例会 本会議",
        detail_url="https://example.com",
    )
    assert m.year is None
    assert m.meeting_type == "honkai"


def test_meeting_summary_with_year():
    m = MeetingSummary(
        tenant_id="sapporo",
        council_id="123",
        meeting_date=date(2026, 4, 15),
        name_of_meeting="本会議",
        year=2026,
        meeting_type="iinkai",
        detail_url="https://example.com",
    )
    assert m.meeting_type == "iinkai"


def test_speech_minimal():
    s = Speech(
        tenant_id="sapporo",
        council_id="123",
        name_of_meeting="本会議",
        speech_order=0,
        speaker="市長",
        content_text="ただいまから本会議を開きます。",
        detail_url="https://example.com",
    )
    assert s.speech_order == 0


def test_year_entry_minimal():
    y = YearEntry(label="2025年度", detail_url="https://example.com")
    assert y.year is None  # default
    assert y.label == "2025年度"
