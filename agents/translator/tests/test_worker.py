"""agents/translator/worker.py のテスト (Pub/Sub + Gemini はすべて mock)。"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from agents.critic.schema import CriticScores, CritiqueResult
from agents.translator.schema import TranslateInput, TranslatorOutput, TranslatorWithCritique
from agents.translator.worker import (
    SOURCE,
    _envelope_to_translate_input,
    main,
    make_handler,
    run_worker,
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


def test_handler_translates_and_publishes_translated_speech():
    """TranslatedSpeech combined payload (原典 + 翻訳) を publish することを検証。"""
    import json

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
    # attributes に speech_id / source / municipality_code 含む
    assert kwargs["speech_id"] == "prefokayama:177:1:0"
    assert kwargs["source"] == SOURCE
    assert kwargs["upstream_source"] == "kaigiroku_net"
    assert kwargs["municipality_code"] == "33000"  # prefokayama → 33000

    # payload は TranslatedSpeech (原典メタ + translation)
    payload = json.loads(args[1].decode("utf-8"))
    assert payload["payload_type"] == "TranslatedSpeech"
    ts = payload["payload"]
    assert ts["speech_id"] == "prefokayama:177:1:0"
    assert ts["tenant_id"] == "prefokayama"
    assert ts["municipality_code"] == "33000"
    assert ts["detail_url"] == "https://example.com/m/1"
    assert ts["content_text"] == "本日の会議を開きます。"
    # translation も埋め込まれていること
    assert ts["translation"]["title"] == "本会議を開始しました"
    assert len(ts["translation"]["summary"]) == 3


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


# ============================================================================
# make_handler + critic (Plan D self-critique, env-flag-gated)
# ============================================================================


def _make_critique_result(
    overall_score: int = 85, revision_count: int = 0
) -> TranslatorWithCritique:
    output = TranslatorOutput(
        title="本会議を開始しました",
        summary=["定例会が始まったよ", "知事の挨拶があったよ", "今日は予算審議だよ"],
        tone="casual",
        contains_politician_names=False,
        contains_political_judgment=False,
    )
    critique = CritiqueResult(
        scores=CriticScores(faithfulness=90, simplicity=85, tone=85, ethics=100),
        overall_score=overall_score,
        feedback="良い翻訳です",
        passed=True,
    )
    return TranslatorWithCritique(
        translation=output,
        critique=critique,
        revision_count=revision_count,
        initial_score=overall_score,
    )


def test_handler_with_critic_calls_translate_with_critique_and_publishes_unwrapped_translation():
    """critic 指定時は translate_with_critique() を使い、.translation を unwrap して publish する。"""
    import json

    agent = MagicMock()
    with_critique = _make_critique_result(overall_score=72, revision_count=1)
    agent.translate_with_critique.return_value = with_critique
    critic = MagicMock()
    pub, client = _make_mock_publisher()
    handler = make_handler(agent, pub, "citify-speech-translated", critic=critic)

    env = _make_speech_envelope(speech_order=0)
    handler(env)

    # translate_with_critique が critic 付きで呼ばれ、plain translate は呼ばれない
    agent.translate_with_critique.assert_called_once()
    call_args = agent.translate_with_critique.call_args[0]
    assert isinstance(call_args[0], TranslateInput)
    assert call_args[1] is critic
    agent.translate.assert_not_called()

    # publish payload の translation は unwrap 済み TranslatorOutput (TranslatorWithCritique ではない)
    client.publish.assert_called_once()
    args, _kwargs = client.publish.call_args
    payload = json.loads(args[1].decode("utf-8"))
    ts = payload["payload"]
    assert ts["translation"]["title"] == with_critique.translation.title
    assert "critique" not in ts["translation"]
    assert "revision_count" not in ts["translation"]


def test_handler_without_critic_uses_plain_translate():
    """critic=None (default) なら従来通り translate() のみ呼ばれる (既存挙動を変えない)。"""
    agent = _make_mock_agent()
    pub, client = _make_mock_publisher()
    handler = make_handler(agent, pub, "out")  # critic 未指定 = default None

    env = _make_speech_envelope()
    handler(env)

    agent.translate.assert_called_once()
    agent.translate_with_critique.assert_not_called()
    client.publish.assert_called_once()


# ============================================================================
# run_worker / main: CITIFY_ENABLE_CRITIQUE env flag
# ============================================================================


def test_run_worker_default_critique_disabled_passes_no_critic(monkeypatch: pytest.MonkeyPatch):
    """critique_enabled=False (default) なら make_handler に critic=None が渡る。"""
    captured: dict = {}

    def fake_make_handler(agent, publisher, output_topic, critic=None):
        captured["critic"] = critic
        return MagicMock()

    monkeypatch.setattr("agents.translator.worker.TranslatorAgent", MagicMock())
    monkeypatch.setattr("agents.translator.worker.PubSubPublisher", MagicMock())
    monkeypatch.setattr("agents.translator.worker.PubSubSubscriber", MagicMock())
    monkeypatch.setattr("agents.translator.worker.make_handler", fake_make_handler)

    run_worker(
        project_id="citify-dev",
        input_subscription="sub",
        output_topic="topic",
        timeout_sec=0,
    )

    assert captured["critic"] is None


def test_run_worker_critique_enabled_builds_critic(monkeypatch: pytest.MonkeyPatch):
    """critique_enabled=True なら CriticAgent が生成され make_handler に渡る。"""
    captured: dict = {}
    fake_critic_instance = MagicMock()

    def fake_make_handler(agent, publisher, output_topic, critic=None):
        captured["critic"] = critic
        return MagicMock()

    monkeypatch.setattr("agents.translator.worker.TranslatorAgent", MagicMock())
    monkeypatch.setattr("agents.translator.worker.PubSubPublisher", MagicMock())
    monkeypatch.setattr("agents.translator.worker.PubSubSubscriber", MagicMock())
    monkeypatch.setattr("agents.translator.worker.make_handler", fake_make_handler)
    monkeypatch.setattr(
        "agents.translator.worker.CriticAgent", MagicMock(return_value=fake_critic_instance)
    )

    run_worker(
        project_id="citify-dev",
        input_subscription="sub",
        output_topic="topic",
        timeout_sec=0,
        critique_enabled=True,
    )

    assert captured["critic"] is fake_critic_instance


@pytest.mark.parametrize(
    ("env_value", "expected"),
    [
        ("1", True),
        ("true", True),
        ("True", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("", False),
    ],
)
def test_main_parses_critique_env_flag(
    monkeypatch: pytest.MonkeyPatch, env_value: str, expected: bool
):
    """CITIFY_ENABLE_CRITIQUE の値に応じて run_worker(critique_enabled=...) に渡す。"""
    captured: dict = {}

    def fake_run_worker(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("agents.translator.worker.run_worker", fake_run_worker)
    monkeypatch.setenv("CITIFY_ENABLE_CRITIQUE", env_value)
    monkeypatch.setattr(
        "sys.argv",
        ["worker.py", "--project-id", "citify-dev"],
    )

    main()

    assert captured["critique_enabled"] is expected


def test_main_defaults_critique_disabled_when_env_unset(monkeypatch: pytest.MonkeyPatch):
    """CITIFY_ENABLE_CRITIQUE 未設定なら critique_enabled=False (default off を担保)。"""
    captured: dict = {}

    def fake_run_worker(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("agents.translator.worker.run_worker", fake_run_worker)
    monkeypatch.delenv("CITIFY_ENABLE_CRITIQUE", raising=False)
    monkeypatch.setattr("sys.argv", ["worker.py", "--project-id", "citify-dev"])

    main()

    assert captured["critique_enabled"] is False
