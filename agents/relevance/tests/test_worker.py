"""agents/relevance/worker.py のテスト (Pub/Sub + Gemini はすべて mock)。

Phase Y で multi-persona fan-out 対応に書き換え。
make_handler は personas: list[UserPersona] を受け取り、agent.score_multi() を呼ぶ。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.relevance.schema import (
    PersonaRelevanceOutput,
    RelevanceInput,
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


def _make_user(user_id: str = "test-user-1") -> UserPersona:
    return UserPersona(
        user_id=user_id,
        age_group="25-29",
        interests=["住居", "雇用", "税"],
        municipality_codes=["33000", "00000"],
    )


def _make_persona_output(user_id: str, score: int = 75) -> PersonaRelevanceOutput:
    return PersonaRelevanceOutput(
        user_id=user_id,
        relevance_score=score,
        score_topic=20,
        score_age=20,
        score_geographic=20,
        score_urgency=15,
        matched_interests=["住居", "税"],
        reasoning="ペルソナ関心軸と speech の合致度が高い",
        contains_political_judgment=False,
    )


def _make_mock_agent_multi(outputs: list[PersonaRelevanceOutput]) -> MagicMock:
    agent = MagicMock()
    agent.score_multi.return_value = outputs
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


def test_envelope_to_relevance_input_extracts_summary_and_title() -> None:
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


def test_envelope_to_relevance_input_raises_on_missing_keys() -> None:
    env = MessageEnvelope(
        schema_version="v1",
        source="translator",
        payload_type="TranslatedSpeech",
        payload={"speech_id": "x"},
    )
    with pytest.raises(ValueError, match="missing"):
        _envelope_to_relevance_input(env, _make_user())


# ============================================================================
# _build_scored_speech
# ============================================================================


def test_build_scored_speech_carries_translation_metadata() -> None:
    env = _make_translated_envelope()
    user = _make_user()
    inp = _envelope_to_relevance_input(env, user)
    score = _make_persona_output("test-user-1", score=75).to_relevance_output()
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
# make_handler (multi-persona fan-out)
# ============================================================================


def test_handler_publishes_n_scored_speeches_for_n_personas() -> None:
    """1 envelope を受けたら N persona 分の ScoredSpeech が publish される。"""
    personas = [
        _make_user("demo-18-24"),
        _make_user("demo-25-29"),
        _make_user("demo-30-39"),
    ]
    agent = _make_mock_agent_multi(
        [
            _make_persona_output("demo-18-24", score=60),
            _make_persona_output("demo-25-29", score=80),
            _make_persona_output("demo-30-39", score=70),
        ]
    )
    pub, client = _make_mock_publisher()
    handler = make_handler(agent, pub, "citify-speech-scored", personas)

    env = _make_translated_envelope()
    handler(env)

    # score_multi が 1 回 (N persona を一括) 呼ばれる
    agent.score_multi.assert_called_once()
    rel_input: RelevanceInput
    persona_args: list[UserPersona]
    rel_input, persona_args = agent.score_multi.call_args[0]
    assert rel_input.speech_id == "prefokayama:177:1:0"
    assert [p.user_id for p in persona_args] == ["demo-18-24", "demo-25-29", "demo-30-39"]

    # publish が N 回呼ばれる
    assert client.publish.call_count == 3
    user_ids_published = [call.kwargs["user_id"] for call in client.publish.call_args_list]
    scores_published = [call.kwargs["score"] for call in client.publish.call_args_list]
    assert user_ids_published == ["demo-18-24", "demo-25-29", "demo-30-39"]
    assert scores_published == ["60", "80", "70"]

    # 各 publish の payload を確認
    for call, expected_user, expected_score in zip(
        client.publish.call_args_list,
        ["demo-18-24", "demo-25-29", "demo-30-39"],
        [60, 80, 70],
        strict=True,
    ):
        args, kwargs = call
        assert args[0] == "projects/citify-dev/topics/citify-speech-scored"
        assert kwargs["source"] == SOURCE
        payload = json.loads(args[1].decode("utf-8"))
        assert payload["payload_type"] == "ScoredSpeech"
        ss = payload["payload"]
        assert ss["user_id"] == expected_user
        assert ss["score"]["relevance_score"] == expected_score


def test_handler_skips_non_translated_speech_payload() -> None:
    agent = _make_mock_agent_multi([])
    pub, client = _make_mock_publisher()
    personas = [_make_user("demo-25-29")]
    handler = make_handler(agent, pub, "out", personas)

    env = MessageEnvelope(
        schema_version="v1",
        source="other",
        payload_type="Speech",
        payload={"speech_id": "x"},
    )
    handler(env)

    agent.score_multi.assert_not_called()
    client.publish.assert_not_called()


def test_handler_propagates_score_failure_for_nack() -> None:
    """score_multi が例外 → handler も例外を伝播 (subscriber が nack)。"""
    agent = MagicMock()
    agent.score_multi.side_effect = RuntimeError("Gemini timeout")
    pub, client = _make_mock_publisher()
    personas = [_make_user("demo-25-29")]
    handler = make_handler(agent, pub, "out", personas)

    env = _make_translated_envelope()
    with pytest.raises(RuntimeError, match="Gemini timeout"):
        handler(env)
    client.publish.assert_not_called()
