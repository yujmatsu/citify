"""scrapers/kokkai/publish.py のテスト (BQ + Pub/Sub mock)。"""

from __future__ import annotations

import json
from datetime import date
from unittest.mock import MagicMock

from pkg.pubsub import PubSubPublisher
from scrapers.kokkai.publish import (
    SOURCE,
    kokkai_row_to_speech_payload,
    publish_kokkai_speeches,
)


def _make_bq_row(**overrides):
    """Mock BQ row (dict-like)。"""
    defaults = {
        "id": "122104024X02020260428_006",
        "source": "kokkai",
        "municipality_code": "00000",
        "session": 215,
        "name_of_house": "衆議院",
        "name_of_meeting": "予算委員会",
        "issue": "第16号",
        "meeting_date": date(2026, 4, 28),
        "speech_order": 6,
        "speaker": "山田太郎",
        "speaker_yomi": "やまだたろう",
        "speaker_group": "自由民主党",
        "speaker_position": "厚生労働大臣",
        "speech": "子育て世帯への家賃補助を拡充します。",
        "speech_url": "https://kokkai.ndl.go.jp/.../122104024X02020260428/006",
        "meeting_url": "https://kokkai.ndl.go.jp/.../122104024X02020260428",
    }
    defaults.update(overrides)

    class Row:
        def __init__(self, d):
            self._d = d

        def get(self, k, default=None):
            return self._d.get(k, default)

        def __getitem__(self, k):
            return self._d[k]

    return Row(defaults)


# ============================================================================
# kokkai_row_to_speech_payload
# ============================================================================


def test_payload_maps_basic_fields():
    row = _make_bq_row()
    p = kokkai_row_to_speech_payload(row)

    assert p["tenant_id"] == "衆議院"
    assert p["council_id"] == "215"
    assert p["schedule_id"] == "第16号"
    assert p["meeting_date"] == "2026-04-28"  # ISO 文字列に変換
    assert p["name_of_meeting"] == "予算委員会"
    assert p["speech_order"] == 6
    assert p["speech_type"] is None  # kokkai は ○△◎ 無し
    assert p["speaker"] == "山田太郎"
    assert p["speaker_position"] == "厚生労働大臣"
    assert p["content_text"] == "子育て世帯への家賃補助を拡充します。"
    assert p["detail_url"].endswith("/006")


def test_payload_preserves_kokkai_meta():
    """kokkai 固有メタは extra として保持 (downstream で参照可)。"""
    row = _make_bq_row()
    p = kokkai_row_to_speech_payload(row)

    assert p["kokkai_speech_id"] == "122104024X02020260428_006"
    assert p["kokkai_session"] == 215
    assert p["speaker_yomi"] == "やまだたろう"
    assert p["speaker_group"] == "自由民主党"


def test_payload_handles_missing_optional():
    row = _make_bq_row(
        speaker_position=None, speaker_yomi=None, speaker_group=None, meeting_date=None
    )
    p = kokkai_row_to_speech_payload(row)
    assert p["speaker_position"] is None
    assert p["speaker_yomi"] is None
    assert p["meeting_date"] is None


def test_payload_handles_sangiin_house():
    row = _make_bq_row(name_of_house="参議院")
    p = kokkai_row_to_speech_payload(row)
    assert p["tenant_id"] == "参議院"


def test_payload_handles_none_house_falls_back_to_kokkai():
    row = _make_bq_row(name_of_house=None)
    p = kokkai_row_to_speech_payload(row)
    assert p["tenant_id"] == "kokkai"


# ============================================================================
# publish_kokkai_speeches
# ============================================================================


def _make_mock_publisher() -> tuple[PubSubPublisher, MagicMock]:
    client = MagicMock()
    client.topic_path.side_effect = lambda p, t: f"projects/{p}/topics/{t}"
    futures = []

    def _publish(topic_path, data, **attrs):
        future = MagicMock()
        future.result.return_value = f"msg-{len(futures)}"
        futures.append(future)
        return future

    client.publish.side_effect = _publish
    return PubSubPublisher(project_id="citify-dev", client=client), client


def test_publish_empty_returns_empty():
    pub, client = _make_mock_publisher()
    msg_ids = publish_kokkai_speeches("citify-dev", "topic", [], publisher=pub)
    assert msg_ids == []
    client.publish.assert_not_called()


def test_publish_creates_speech_envelopes():
    pub, client = _make_mock_publisher()
    rows = [_make_bq_row(), _make_bq_row(speech="別の発言です")]
    msg_ids = publish_kokkai_speeches("citify-dev", "citify-speech-translate", rows, publisher=pub)

    assert len(msg_ids) == 2
    assert client.publish.call_count == 2

    # 1 件目の publish データを確認
    args, kwargs = client.publish.call_args_list[0]
    topic_path, data = args
    assert topic_path == "projects/citify-dev/topics/citify-speech-translate"

    payload = json.loads(data.decode("utf-8"))
    assert payload["source"] == SOURCE
    assert payload["payload_type"] == "Speech"
    assert payload["payload"]["speaker"] == "山田太郎"

    # attributes
    assert kwargs["tenant_id"] == "衆議院"
    assert kwargs["council_id"] == "215"


def test_publish_attributes_handle_none_schedule_id():
    """schedule_id が None でも空文字列で publish できる。"""
    pub, client = _make_mock_publisher()
    rows = [_make_bq_row(issue=None)]
    publish_kokkai_speeches("citify-dev", "topic", rows, publisher=pub)

    _, kwargs = client.publish.call_args
    assert kwargs["schedule_id"] == ""
