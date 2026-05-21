"""agents/relevance/worker.py のテスト (Pub/Sub + Gemini はすべて mock)。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.relevance.schema import (
    RelevanceInput,
    RelevanceOutput,
    ScoredSpeech,
    UserPersona,
)
from agents.relevance.worker import (
    SOURCE,
    _build_scored_speech,
    _envelope_to_relevance_input,
    make_handler,
)
from pkg.pubsub import MessageEnvelope, PubSubPublisher


def _make_translated_envelope(
    speech_id: str = "prefokayama:177:1:0",
    municipality_code: str = "33000",
    summary: list[str] | None = None,
    title: str = "本会議を開始しました",
) -> MessageEnvelope:
    payload = {
        "speech_id": speech_id,
        "tenant_id": "prefokayama",
        "council_id": "177",
        "schedule_id": "1",
        "municipality_code": municipality_code,
        "meeting_date": "2025-02-21",
        "name_of_meeting": "令和7年2月定例会",
        "speaker_position": "議長",
        "detail_url": "https://example.com/m/1",
        "content_text": "本日の会議を開きます。",
        "translation": {
            "title": title,
            "summary": summary or ["定例会が始まったよ", "知事の挨拶があったよ", "予算審議だよ"],
            "tone": "casual",
            "contains_politician_names": False,
            "contains_political_judgment": False,
            "notes": "",
        },
    }
    return MessageEnvelope(
        schema_version="v1",
        source="translator",
        payload_type="TranslatedSpeech",
        payload=payload,
    )


def _make_user() -> UserPersona:
    return UserPersona(
        user_id="test-user-1",
        age_group="25-29",
        interests=["住居", "雇用", "税"],
        municipality_codes=["33000", "00000"],
    )


def _make_mock_agent(score: int = 75) -> MagicMock:
    agent = MagicMock()
    agent.score.return_value = RelevanceOutput(
        relevance_score=score,
        score_topic=20,
        score_age=20,
        score_geographic=20,
        score_urgency=15,
        matched_interests=["住居", "税"],
        reasoning="ペルソナ関心軸と speech の合致度が高い",
        contains_political_judgment=False,
    )
    return agent


def _make_mock_publisher() -> tuple[PubSubPublisher, MagicMock]:
    client = MagicMock()
    client.topic_path.side_effect = lambda p, t: f"projects/{p}/topics/{t}"
    future = MagicMock()
    future.result.return_value = "msg-scored-1"
    client.publish.return_value = future
    return PubSubPublisher(project_id="citify-dev", client=client), client


# ============================================================================
# _envelope_to_relevance_input
# ============================================================================


def test_envelope_to_relevance_input_extracts_summary_and_title():
    env = _make_translated_envelope()
    user = _make_user()
    inp = _envelope_to_relevance_input(env, user)

    assert inp.speech_id == "prefokayama:177:1:0"
    assert inp.title == "本会議を開始しました"
    assert inp.translated_summary == [
        "定例会が始まったよ",
        "知事の挨拶があったよ",
        "予算審議だよ",
    ]
    assert inp.speaker_position == "議長"
    assert inp.municipality_code == "33000"
    assert "令和7年2月定例会" in inp.meeting_context
    assert "2025-02-21" in inp.meeting_context
    assert inp.user.user_id == "test-user-1"


def test_envelope_to_relevance_input_raises_on_missing_keys():
    env = MessageEnvelope(
        schema_version="v1",
        source="translator",
        payload_type="TranslatedSpeech",
        payload={"speech_id": "x"},  # 必須 keys 欠落
    )
    with pytest.raises(ValueError, match="missing"):
        _envelope_to_relevance_input(env, _make_user())


# ============================================================================
# _build_scored_speech
# ============================================================================


def test_build_scored_speech_carries_translation_metadata():
    env = _make_translated_envelope()
    user = _make_user()
    inp = _envelope_to_relevance_input(env, user)
    score = _make_mock_agent().score.return_value
    scored = _build_scored_speech(env, inp, score)

    assert isinstance(scored, ScoredSpeech)
    assert scored.speech_id == "prefokayama:177:1:0"
    assert scored.user_id == "test-user-1"
    assert scored.title == "本会議を開始しました"
    assert len(scored.summary) == 3
    assert scored.detail_url == "https://example.com/m/1"
    assert scored.score.relevance_score == 75
    assert "住居" in scored.score.matched_interests


# ============================================================================
# make_handler
# ============================================================================


def test_handler_scores_and_publishes_scored_speech():
    agent = _make_mock_agent(score=80)
    pub, client = _make_mock_publisher()
    user = _make_user()
    handler = make_handler(agent, pub, "citify-speech-scored", user)

    env = _make_translated_envelope()
    handler(env)

    # score 呼び出し検証
    agent.score.assert_called_once()
    rel_input: RelevanceInput = agent.score.call_args[0][0]
    assert rel_input.user.user_id == "test-user-1"
    assert rel_input.municipality_code == "33000"

    # publish 呼び出し検証
    client.publish.assert_called_once()
    args, kwargs = client.publish.call_args
    assert args[0] == "projects/citify-dev/topics/citify-speech-scored"
    assert kwargs["speech_id"] == "prefokayama:177:1:0"
    assert kwargs["user_id"] == "test-user-1"
    assert kwargs["score"] == "80"
    assert kwargs["source"] == SOURCE

    payload = json.loads(args[1].decode("utf-8"))
    assert payload["payload_type"] == "ScoredSpeech"
    ss = payload["payload"]
    assert ss["speech_id"] == "prefokayama:177:1:0"
    assert ss["title"] == "本会議を開始しました"
    assert ss["detail_url"] == "https://example.com/m/1"
    assert ss["score"]["relevance_score"] == 80


def test_handler_skips_non_translated_speech_payload():
    """payload_type が 'TranslatedSpeech' でない envelope は skip。"""
    agent = _make_mock_agent()
    pub, client = _make_mock_publisher()
    user = _make_user()
    handler = make_handler(agent, pub, "out", user)

    env = MessageEnvelope(
        schema_version="v1",
        source="other",
        payload_type="Speech",  # raw Speech (translator 前) は通さない
        payload={"speech_id": "x"},
    )
    handler(env)

    agent.score.assert_not_called()
    client.publish.assert_not_called()


def test_handler_propagates_score_failure_for_nack():
    """RelevanceAgent.score() が例外 → handler も例外を伝播 (subscriber が nack)。"""
    agent = MagicMock()
    agent.score.side_effect = RuntimeError("Gemini timeout")
    pub, client = _make_mock_publisher()
    user = _make_user()
    handler = make_handler(agent, pub, "out", user)

    env = _make_translated_envelope()
    with pytest.raises(RuntimeError, match="Gemini timeout"):
        handler(env)
    client.publish.assert_not_called()
