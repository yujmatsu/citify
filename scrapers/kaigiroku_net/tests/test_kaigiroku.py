"""kaigiroku_net スクレイパーのテスト (Playwright 不要、純粋ロジックのみ)。

Playwright 部分は live verification (CLI) で確認。
ここでは parse 系のヘルパー関数 + schema の妥当性 + URL 組み立てを検証。
"""

from __future__ import annotations

from datetime import date

import pytest

from scrapers.kaigiroku_net.client import (
    CENTRAL_BASE_URL_TEMPLATE,
    KaigirokuNetClient,
    _build_minuteview_url,
    _build_schedule_url,
    _extract_url_param,
    _extract_view_year_from_council_name,
    _parse_date_jp,
    _parse_schedule_title_to_date,
    _parse_speech_block,
)
from scrapers.kaigiroku_net.schema import MeetingSchedule, MeetingSummary, Speech

# ============================================================================
# 日付パース
# ============================================================================


def test_parse_date_iso():
    assert _parse_date_jp("2026-04-15") == date(2026, 4, 15)
    assert _parse_date_jp("2026/04/15") == date(2026, 4, 15)
    assert _parse_date_jp("2026.04.15") == date(2026, 4, 15)


def test_parse_date_reiwa():
    """令和 8 年 = 2026 年 (令和 N = 2018 + N)。"""
    assert _parse_date_jp("令和8年4月15日") == date(2026, 4, 15)
    assert _parse_date_jp("令和7年12月1日") == date(2025, 12, 1)


def test_parse_date_heisei():
    """平成 30 年 = 2018 年 (平成 N = 1988 + N)。"""
    assert _parse_date_jp("平成30年4月1日") == date(2018, 4, 1)


def test_parse_date_invalid_returns_none():
    assert _parse_date_jp(None) is None
    assert _parse_date_jp("") is None
    assert _parse_date_jp("invalid") is None


# ============================================================================
# council 名から年抽出
# ============================================================================


def test_extract_view_year_zenkaku():
    """全角数字対応。"""
    assert _extract_view_year_from_council_name("令和　７年　２月定例会") == 2025


def test_extract_view_year_hankaku():
    assert _extract_view_year_from_council_name("令和8年4月臨時会") == 2026


def test_extract_view_year_no_match():
    assert _extract_view_year_from_council_name("(unknown)") is None
    assert _extract_view_year_from_council_name("") is None


# ============================================================================
# schedule タイトルから date
# ============================================================================


def test_parse_schedule_title_with_year():
    assert _parse_schedule_title_to_date("02月21日－01号", base_year=2025) == date(2025, 2, 21)


def test_parse_schedule_title_no_year_returns_none():
    """base_year なしだと年情報なし、None。"""
    assert _parse_schedule_title_to_date("02月21日－01号") is None


def test_parse_schedule_title_invalid():
    assert _parse_schedule_title_to_date("", base_year=2025) is None
    assert _parse_schedule_title_to_date("(no date)", base_year=2025) is None


# ============================================================================
# 発言ブロックパース
# ============================================================================


def test_parse_speech_block_chairperson():
    """○議長（久徳大輔君）の標準形。"""
    text = "○議長（久徳大輔君）　　皆さん、おはようございます。"
    speech_type, speaker, position, body = _parse_speech_block(text)
    assert speech_type == "○"
    assert speaker == "久徳大輔"
    assert position == "議長"
    assert "皆さん、おはようございます" in body


def test_parse_speech_block_governor():
    """◎答弁の例: 知事 (◎)。"""
    text = "◎知事（伊原木隆太君）　　令和7年度予算について..."
    st, sp, pos, body = _parse_speech_block(text)
    assert st == "◎"
    assert sp == "伊原木隆太"
    assert pos == "知事"


def test_parse_speech_block_topic_header():
    """△議題は発言者というより議題ヘッダ。"""
    text = "△議題　日程第１"
    st, sp, pos, body = _parse_speech_block(text)
    assert st == "△"
    # 議題は speaker_position 形式に近いので、speaker="議題" or similar が妥当
    assert sp in ("議題", "(不明)")


def test_parse_speech_block_multiline_body():
    """本文が複数行にわたるケース。"""
    text = "○議長（山田太郎君）　　質問させていただきます。\n本日は天候不順..."
    st, sp, pos, body = _parse_speech_block(text)
    assert sp == "山田太郎"
    assert "質問させていただきます" in body
    assert "本日は天候不順" in body


def test_parse_speech_block_unknown_format():
    """マーク無し → speech_type None、speaker (不明)。"""
    text = "ただの本文テキスト"
    st, sp, pos, body = _parse_speech_block(text)
    assert st is None
    assert sp == "(不明)"
    assert pos is None
    assert body == "ただの本文テキスト"


def test_parse_speech_block_empty():
    st, sp, pos, body = _parse_speech_block("")
    assert sp == "(不明)"
    assert body == ""


# ============================================================================
# URL 組み立て
# ============================================================================


def test_build_schedule_url_with_tenant_num():
    url = _build_schedule_url("https://ssp.kaigiroku.net/tenant/prefokayama/", "177", "455")
    assert url == (
        "https://ssp.kaigiroku.net/tenant/prefokayama/MinuteSchedule.html"
        "?tenant_id=455&council_id=177"
    )


def test_build_schedule_url_without_tenant_num():
    url = _build_schedule_url("https://example.com/tenant/x/", "100")
    assert url.endswith("MinuteSchedule.html?council_id=100")


def test_build_minuteview_url():
    url = _build_minuteview_url("https://ssp.kaigiroku.net/tenant/prefokayama/", "177", "1")
    assert url == (
        "https://ssp.kaigiroku.net/tenant/prefokayama/MinuteView.html?council_id=177&schedule_id=1"
    )


# ============================================================================
# URL クエリ抽出
# ============================================================================


def test_extract_url_param():
    url = "https://example.com/x?foo=bar&tenant_id=455"
    assert _extract_url_param(url, "tenant_id") == "455"
    assert _extract_url_param(url, "foo") == "bar"
    assert _extract_url_param(url, "missing") is None


def test_extract_url_param_invalid_url():
    # 完全に壊れた URL でも例外を出さない
    assert _extract_url_param("", "x") is None


# ============================================================================
# Schema バリデーション
# ============================================================================


def test_meeting_summary_minimal():
    m = MeetingSummary(
        tenant_id="prefokayama",
        council_id="177",
        name_of_meeting="本会議",
        detail_url="https://example.com/MinuteSchedule.html?council_id=177",
    )
    assert m.tenant_id == "prefokayama"
    assert m.meeting_date is None


def test_meeting_schedule_minimal():
    s = MeetingSchedule(
        tenant_id="prefokayama",
        council_id="177",
        schedule_id="1",
        title="02月21日－01号",
        detail_url="https://example.com/MinuteView.html?council_id=177&schedule_id=1",
    )
    assert s.schedule_id == "1"
    assert s.page_label is None


def test_meeting_schedule_with_date():
    s = MeetingSchedule(
        tenant_id="prefokayama",
        council_id="177",
        schedule_id="1",
        page_label="P.1",
        title="02月21日－01号",
        meeting_date=date(2025, 2, 21),
        detail_url="https://example.com/",
    )
    assert s.meeting_date == date(2025, 2, 21)


def test_speech_minimal():
    s = Speech(
        tenant_id="prefokayama",
        council_id="177",
        name_of_meeting="本会議",
        speech_order=0,
        speaker="区長",
        content_text="ただいまから本会議を開きます。",
        detail_url="https://example.com",
    )
    assert s.speech_order == 0
    assert s.speech_type is None  # default


def test_speech_with_full_metadata():
    s = Speech(
        tenant_id="prefokayama",
        council_id="177",
        schedule_id="1",
        name_of_meeting="令和　７年　２月定例会",
        speech_order=5,
        speech_type="○",
        speaker="久徳大輔",
        speaker_position="議長",
        content_text="本日の会議を開きます。",
        detail_url="https://example.com",
    )
    assert s.speech_type == "○"
    assert s.speaker_position == "議長"
    assert s.schedule_id == "1"


def test_speech_extra_fields_allowed():
    """extra='allow' なので追加フィールドが落ちない。"""
    s = Speech.model_validate(
        {
            "tenant_id": "prefokayama",
            "council_id": "177",
            "name_of_meeting": "本会議",
            "speech_order": 0,
            "speaker": "区長",
            "content_text": "...",
            "detail_url": "https://example.com",
            "future_field": "value",
        }
    )
    assert s.tenant_id == "prefokayama"


# ============================================================================
# Client URL 組み立て
# ============================================================================


def test_client_central_url_template():
    """tenant_id から中央型 URL を組み立てる。"""
    client = KaigirokuNetClient(tenant_id="prefokayama")
    assert client.base_url == "https://ssp.kaigiroku.net/tenant/prefokayama/"


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
        base_url="http://giji.city.yokohama.lg.jp/tenant/yokohama",
    )
    assert client.base_url.endswith("/")


def test_client_template_constant_format():
    """CENTRAL_BASE_URL_TEMPLATE が tenant_id placeholder を持つ。"""
    assert "{tenant_id}" in CENTRAL_BASE_URL_TEMPLATE


@pytest.mark.asyncio
async def test_client_requires_context_manager():
    """async context manager の外で _new_page を呼ぶと RuntimeError。"""
    client = KaigirokuNetClient(tenant_id="prefokayama")
    with pytest.raises(RuntimeError, match="context manager"):
        await client._new_page()
