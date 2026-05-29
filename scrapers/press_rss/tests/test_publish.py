"""press_rss publish のテスト (Pub/Sub は mock、Speech envelope mapping を検証)。"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from pkg.pubsub import PubSubPublisher
from scrapers.press_rss.publish import (
    SOURCE,
    press_item_to_speech_payload,
    publish_press_items,
)
from scrapers.press_rss.schema import PressItem


def _make_item(
    item_id: str = "abc-1",
    muni: str = "13000",
    title: str = "令和8年度予算案を公表",
    description: str = "東京都の予算案 1,500 億円",
    link: str = "https://example.tokyo.lg.jp/news/budget.html",
    category: str | None = "お知らせ",
    pub_date: datetime | None = None,
) -> PressItem:
    return PressItem(
        id=item_id,
        municipality_code=muni,
        title=title,
        link=link,
        description=description,
        pub_date=pub_date or datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
        category=category,
        source_url="https://example.tokyo.lg.jp/rss.xml",
        fetched_at=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
    )


def _make_mock_publisher() -> tuple[PubSubPublisher, MagicMock]:
    client = MagicMock()
    client.topic_path.side_effect = lambda p, t: f"projects/{p}/topics/{t}"
    future = MagicMock()
    future.result.return_value = "msg-1"
    client.publish.return_value = future
    return PubSubPublisher(project_id="citify-dev", client=client), client


# ============================================================================
# press_item_to_speech_payload
# ============================================================================


def test_payload_basic_fields() -> None:
    item = _make_item()
    payload = press_item_to_speech_payload(item)

    assert payload["speech_id"] == "press:13000:abc-1"
    assert payload["tenant_id"] == "13000"  # 5 桁コード直接
    # council_id は item.id (= "abc-1") の sha256[:8] を含む (同日複数記事の speech_id 衝突回避)
    assert payload["council_id"] == "press-65397a5f"
    assert payload["schedule_id"] == "2026-04-15"
    assert payload["meeting_date"] == "2026-04-15"
    assert payload["name_of_meeting"] == "お知らせ"
    assert payload["speaker"] == "(プレス担当)"
    assert payload["speaker_position"] == "プレス担当"
    assert payload["detail_url"] == "https://example.tokyo.lg.jp/news/budget.html"
    # content_text に title + description が連結される
    assert "令和8年度予算案を公表" in payload["content_text"]
    assert "1,500 億円" in payload["content_text"]


def test_payload_preserves_press_meta_via_extras() -> None:
    item = _make_item(item_id="x-99", category="子育て")
    payload = press_item_to_speech_payload(item)

    # press 固有メタは extra として保持
    assert payload["press_id"] == "x-99"
    assert payload["press_title"] == "令和8年度予算案を公表"
    assert payload["press_category"] == "子育て"
    assert payload["press_municipality_code"] == "13000"
    assert payload["press_rss_url"] == "https://example.tokyo.lg.jp/rss.xml"
    assert payload["press_pub_date"] == "2026-04-15T09:00:00+00:00"


def test_payload_handles_missing_pub_date() -> None:
    # _make_item default fallback を経由しないよう、直接 PressItem を生成
    item = PressItem(
        id="no-date-1",
        municipality_code="13000",
        title="日付なしのお知らせ",
        link="https://example.tokyo.lg.jp/no-date.html",
        description="",
        pub_date=None,
        category=None,
        source_url="https://example.tokyo.lg.jp/rss.xml",
        fetched_at=datetime(2026, 5, 25, 12, 0, tzinfo=UTC),
    )
    payload = press_item_to_speech_payload(item)
    assert payload["schedule_id"] is None
    assert payload["meeting_date"] is None
    assert payload["press_pub_date"] is None


def test_payload_handles_missing_category() -> None:
    item = _make_item(category=None)
    payload = press_item_to_speech_payload(item)
    # category 欠如時は "プレスリリース" にフォールバック
    assert payload["name_of_meeting"] == "プレスリリース"


def test_payload_handles_empty_description() -> None:
    item = _make_item(description="")
    payload = press_item_to_speech_payload(item)
    # title のみ (description 空)
    assert payload["content_text"].strip() == "令和8年度予算案を公表"


# ============================================================================
# publish_press_items
# ============================================================================


def test_publish_empty_list_returns_no_messages() -> None:
    pub, client = _make_mock_publisher()
    msg_ids = publish_press_items("citify-dev", "topic-x", [], publisher=pub)
    assert msg_ids == []
    client.publish.assert_not_called()


def test_publish_envelope_structure_and_attributes() -> None:
    """envelope の source / payload_type / attrs を検証。"""
    import json

    pub, client = _make_mock_publisher()
    item = _make_item()
    msg_ids = publish_press_items("citify-dev", "citify-speech-translate", [item], publisher=pub)

    assert msg_ids == ["msg-1"]
    args, kwargs = client.publish.call_args
    assert args[0] == "projects/citify-dev/topics/citify-speech-translate"
    # attributes
    assert kwargs["source"] == SOURCE
    assert kwargs["tenant_id"] == "13000"
    assert kwargs["council_id"] == "press-65397a5f"  # sha256("abc-1")[:8] (Phase G-1 fix)
    assert kwargs["schedule_id"] == "2026-04-15"
    # payload
    envelope = json.loads(args[1].decode("utf-8"))
    assert envelope["source"] == SOURCE
    assert envelope["payload_type"] == "Speech"
    assert envelope["payload"]["speech_id"] == "press:13000:abc-1"
    assert envelope["payload"]["content_text"].startswith("令和8年度予算案を公表")


def test_publish_multiple_items_in_order() -> None:
    pub, client = _make_mock_publisher()
    items = [
        _make_item(item_id="a", muni="13000"),
        _make_item(item_id="b", muni="27000"),
    ]
    msg_ids = publish_press_items("citify-dev", "topic-x", items, publisher=pub)
    assert len(msg_ids) == 2
    assert client.publish.call_count == 2


# ============================================================================
# resolve_municipality_code 連携 (pkg.municipality_map)
# ============================================================================


def test_press_rss_municipality_code_resolution() -> None:
    """press_rss source + tenant_id (5 桁) → そのまま返ることを確認 (worker 連携の保証)。"""
    from pkg.municipality_map import resolve_municipality_code

    assert resolve_municipality_code("press_rss", "13000") == "13000"
    assert resolve_municipality_code("press_rss", "27000") == "27000"
    # 不正値 (5 桁数字でない) は fallback
    assert resolve_municipality_code("press_rss", "tokyo") == "00000"
    assert resolve_municipality_code("press_rss", None) == "00000"


# ============================================================================
# CSV reader
# ============================================================================


def test_csv_reader_filters_empty_rows(tmp_path: pytest.Path) -> None:  # type: ignore[name-defined]
    from scrapers.press_rss.__main__ import _read_press_feeds_from_csv

    csv_text = (
        "municipality_code,scraper_type,scraper_base_url,tenant_id,press_rss_url,opendata_url,tier,is_active,notes\n"
        "13000,press_rss,,,https://tokyo.example/rss.xml,,1,true,Tokyo\n"
        "27000,press_rss,,,https://osaka.example/rss.xml,,1,true,Osaka\n"
        "01000,unknown,,,,,3,false,Hokkaido (no RSS)\n"
        "39000,kaigiroku,https://x,tosa,,,,1,true,Tosa (no press)\n"
    )
    p = tmp_path / "test.csv"
    p.write_text(csv_text, encoding="utf-8")

    feeds = _read_press_feeds_from_csv(str(p))
    assert feeds == [
        ("13000", "https://tokyo.example/rss.xml"),
        ("27000", "https://osaka.example/rss.xml"),
    ]
