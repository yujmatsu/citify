"""agents/translator/worker.py のテスト (Pub/Sub + Gemini はすべて mock)。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from agents.translator.schema import TranslateInput, TranslatorOutput
from agents.translator.worker import (
    SOURCE,
    _envelope_to_translate_input,
    make_handler,
)
from pkg.pubsub import MessageEnvelope, PubSubPublisher


def _make_speech_envelope(
    speech_order: int = 0,
    content_text: str = "本日の会議を開きます。",
    schedule_id: str | None = "1",
) -> MessageEnvelope:
    payload = {
        "tenant_id": "prefokayama",
        "council_id": "177",
        "schedule_id": schedule_id,
        "meeting_date": str(date(2025, 2, 21)),
        "name_of_meeting": "令和7年2月定例会",
        "speech_order": speech_order,
        "speech_type": "○",
        "speaker": "久徳大輔",
        "speaker_position": "議長",
        "content_text": content_text,
        "detail_url": "https://example.com/m/1",
    }
    return MessageEnvelope(
        schema_version="v1",
        source="kaigiroku_net",
        payload_type="Speech",
        payload=payload,
    )


# ============================================================================
# _envelope_to_translate_input
# ============================================================================


def test_envelope_to_translate_input_builds_composite_speech_id():
    env = _make_speech_envelope(speech_order=3, schedule_id="2")
    inp = _envelope_to_translate_input(env)
    assert inp.speech_id == "prefokayama:177:2:3"
    assert inp.content_text == "本日の会議を開きます。"
    assert inp.speaker == "久徳大輔"
    assert inp.speaker_position == "議長"
    assert "令和7年2月定例会" in inp.meeting_context
    assert "2025-02-21" in inp.meeting_context


def test_envelope_to_translate_input_no_schedule_id():
    env = _make_speech_envelope(speech_order=0, schedule_id=None)
    inp = _envelope_to_translate_input(env)
    assert inp.speech_id == "prefokayama:177::0"


def test_envelope_to_translate_input_raises_on_missing_keys():
    env = MessageEnvelope(
        schema_version="v1",
        source="x",
        payload_type="Speech",
        payload={"tenant_id": "x"},  # 必須 keys 欠落
    )
    with pytest.raises(ValueError, match="missing"):
        _envelope_to_translate_input(env)


# ============================================================================
# make_handler
# ============================================================================


def _make_mock_agent(output: TranslatorOutput | None = None) -> MagicMock:
    agent = MagicMock()
    if output is None:
        output = TranslatorOutput(
            title="本会議を開始しました",
            summary=["定例会が始まったよ", "知事の挨拶があったよ", "今日は予算審議だよ"],
            tone="casual",
            contains_politician_names=False,
            contains_political_judgment=False,
        )
    agent.translate.return_value = output
    return agent


def _make_mock_publisher() -> tuple[PubSubPublisher, MagicMock]:
    client = MagicMock()
    client.topic_path.side_effect = lambda p, t: f"projects/{p}/topics/{t}"
    future = MagicMock()
    future.result.return_value = "msg-out-1"
    client.publish.return_value = future
    pub = PubSubPublisher(project_id="citify-dev", client=client)
    return pub, client


def test_handler_translates_and_publishes():
    agent = _make_mock_agent()
    pub, client = _make_mock_publisher()
    handler = make_handler(agent, pub, "citify-speech-translated")

    env = _make_speech_envelope(speech_order=0)
    handler(env)

    # translate 呼び出し検証
    agent.translate.assert_called_once()
    call_arg = agent.translate.call_args[0][0]
    assert isinstance(call_arg, TranslateInput)
    assert call_arg.speech_id == "prefokayama:177:1:0"

    # publish 呼び出し検証
    client.publish.assert_called_once()
    args, kwargs = client.publish.call_args
    assert args[0] == "projects/citify-dev/topics/citify-speech-translated"
    # attributes に speech_id / source 含む
    assert kwargs["speech_id"] == "prefokayama:177:1:0"
    assert kwargs["source"] == SOURCE
    assert kwargs["upstream_source"] == "kaigiroku_net"


def test_handler_skips_non_speech_payload():
    """payload_type が 'Speech' でない envelope は skip して何も起こらない。"""
    agent = _make_mock_agent()
    pub, client = _make_mock_publisher()
    handler = make_handler(agent, pub, "out")

    env = MessageEnvelope(
        schema_version="v1",
        source="other",
        payload_type="PressItem",
        payload={"foo": "bar"},
    )
    handler(env)  # 例外も発生しない

    agent.translate.assert_not_called()
    client.publish.assert_not_called()


def test_handler_skips_empty_content():
    """content_text が空 (whitespace のみ) なら translate / publish 共にスキップ。"""
    agent = _make_mock_agent()
    pub, client = _make_mock_publisher()
    handler = make_handler(agent, pub, "out")

    env = _make_speech_envelope(content_text="   \n  ")
    handler(env)

    agent.translate.assert_not_called()
    client.publish.assert_not_called()


def test_handler_propagates_translator_failure_for_nack():
    """TranslatorAgent.translate() が例外 → handler も例外を伝播。

    process_message 側で nack されることを担保。
    """
    agent = MagicMock()
    agent.translate.side_effect = RuntimeError("Gemini timeout")
    pub, client = _make_mock_publisher()
    handler = make_handler(agent, pub, "out")

    env = _make_speech_envelope()
    with pytest.raises(RuntimeError, match="Gemini timeout"):
        handler(env)
    client.publish.assert_not_called()  # 失敗時は出力しない
