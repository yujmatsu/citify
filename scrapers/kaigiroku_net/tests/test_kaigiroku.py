"""kaigiroku_net スクレイパーのテスト (Playwright 不要、純粋ロジックのみ)。

Playwright を mock する代わりに、parse 系のヘルパー関数 + schema の妥当性のみ検証。
実 site の挙動は CLI inspect / list で手動確認。
"""

from __future__ import annotations

from datetime import date

import pytest

from scrapers.kaigiroku_net.client import (
    CENTRAL_BASE_URL_TEMPLATE,
    KaigirokuNetClient,
    _parse_date_jp,
)
from scrapers.kaigiroku_net.schema import MeetingSummary, Speech

# ============================================================================
# 日付パース
# ============================================================================


def test_parse_date_iso():
    assert _parse_date_jp("2026-04-15") == date(2026, 4, 15)
    assert _parse_date_jp("2026/04/15") == date(2026, 4, 15)
    assert _parse_date_jp("2026.04.15") == date(2026, 4, 15)


def test_parse_date_reiwa():
    """令和 8 年 = 2026 年。"""
    assert _parse_date_jp("令和8年4月15日") == date(2026, 4, 15)
    assert _parse_date_jp("令和7年12月1日") == date(2025, 12, 1)


def test_parse_date_invalid_returns_none():
    assert _parse_date_jp(None) is None
    assert _parse_date_jp("") is None
    assert _parse_date_jp("invalid") is None


# ============================================================================
# Schema バリデーション
# ============================================================================


def test_meeting_summary_minimal():
    m = MeetingSummary(
        tenant_id="arakawa",
        council_id="123",
        name_of_meeting="本会議",
        detail_url="https://example.com/m/123",
    )
    assert m.tenant_id == "arakawa"
    assert m.meeting_date is None  # default


def test_meeting_summary_with_date():
    m = MeetingSummary(
        tenant_id="arakawa",
        council_id="123",
        meeting_date=date(2026, 4, 15),
        name_of_meeting="本会議",
        title="令和8年第1回定例会",
        detail_url="https://example.com/m/123",
    )
    assert m.meeting_date == date(2026, 4, 15)


def test_speech_minimal():
    s = Speech(
        tenant_id="arakawa",
        council_id="123",
        name_of_meeting="本会議",
        speech_order=0,
        speaker="区長",
        content_text="ただいまから本会議を開きます。",
        detail_url="https://example.com/m/123",
    )
    assert s.speech_order == 0
    assert s.speaker == "区長"


def test_speech_extra_fields_allowed():
    """extra='allow' なので追加フィールドが落ちない。"""
    s = Speech.model_validate(
        {
            "tenant_id": "arakawa",
            "council_id": "123",
            "name_of_meeting": "本会議",
            "speech_order": 0,
            "speaker": "区長",
            "content_text": "...",
            "detail_url": "https://example.com",
            "future_field": "value",
        }
    )
    assert s.tenant_id == "arakawa"


# ============================================================================
# Client URL 組み立て
# ============================================================================


def test_client_central_url_template():
    """tenant_id から中央型 URL を組み立てる。"""
    client = KaigirokuNetClient(tenant_id="arakawa")
    assert client.base_url == "https://ssp.kaigiroku.net/tenant/arakawa/"


def test_client_white_label_url_override():
    """base_url 指定で白ラベル型に切り替え。"""
    client = KaigirokuNetClient(
        tenant_id="yokohama",
        base_url="http://giji.city.yokohama.lg.jp/tenant/yokohama/",
    )
    assert client.base_url == "http://giji.city.yokohama.lg.jp/tenant/yokohama/"


def test_client_base_url_trailing_slash_normalized():
    """末尾スラッシュなしでも追加される。"""
    client = KaigirokuNetClient(
        tenant_id="yokohama",
        base_url="http://giji.city.yokohama.lg.jp/tenant/yokohama",  # 末尾なし
    )
    assert client.base_url.endswith("/")


def test_client_template_constant_format():
    """CENTRAL_BASE_URL_TEMPLATE が tenant_id placeholder を持つ。"""
    assert "{tenant_id}" in CENTRAL_BASE_URL_TEMPLATE


@pytest.mark.asyncio
async def test_client_requires_context_manager():
    """async context manager の外で _new_page を呼ぶと RuntimeError。"""
    client = KaigirokuNetClient(tenant_id="arakawa")
    with pytest.raises(RuntimeError, match="context manager"):
        await client._new_page()
