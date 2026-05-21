"""scrapers/kaigiroku_net/publish.py のテスト (Pub/Sub クライアントは mock)。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from pkg.pubsub import PubSubPublisher
from scrapers.kaigiroku_net.publish import SOURCE, publish_speeches
from scrapers.kaigiroku_net.schema import Speech


def _make_speech(order: int = 0, schedule_id: str = "1") -> Speech:
    return Speech(
        tenant_id="prefokayama",
        council_id="177",
        schedule_id=schedule_id,
        meeting_date=date(2025, 2, 21),
        name_of_meeting="令和7年2月定例会",
        speech_order=order,
        speech_type="○",
        speaker="久徳大輔",
        speaker_position="議長",
        content_text=f"テスト発言 {order}",
        detail_url="https://example.com/m/1",
    )


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


def test_publish_speeches_empty_returns_empty():
    pub, client = _make_mock_publisher()
    msg_ids = publish_speeches("citify-dev", "t", [], publisher=pub)
    assert msg_ids == []
    client.publish.assert_not_called()


def test_publish_speeches_publishes_each():
    pub, client = _make_mock_publisher()
    speeches = [_make_speech(i) for i in range(3)]
    msg_ids = publish_speeches("citify-dev", "citify-speech-translate", speeches, publisher=pub)
    assert msg_ids == ["msg-0", "msg-1", "msg-2"]
    assert client.publish.call_count == 3


def test_publish_speeches_attributes_carry_tenant_metadata():
    pub, client = _make_mock_publisher()
    speeches = [_make_speech(0, schedule_id="42")]
    publish_speeches("citify-dev", "topic", speeches, publisher=pub)
    _, kwargs = client.publish.call_args
    assert kwargs["tenant_id"] == "prefokayama"
    assert kwargs["council_id"] == "177"
    assert kwargs["schedule_id"] == "42"
    assert kwargs["source"] == SOURCE


def test_publish_speeches_handles_none_schedule_id():
    """schedule_id=None でも publish 可能 (空文字列に変換)。"""
    speech = _make_speech(0)
    # schedule_id を Pydantic で None に
    speech_no_sched = speech.model_copy(update={"schedule_id": None})
    pub, client = _make_mock_publisher()
    publish_speeches("citify-dev", "t", [speech_no_sched], publisher=pub)
    _, kwargs = client.publish.call_args
    assert kwargs["schedule_id"] == ""
