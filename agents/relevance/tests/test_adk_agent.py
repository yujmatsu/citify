"""ADKRelevanceAgent のユニットテスト (Plan C)。

テスト戦略 (translator/test_adk_agent.py と並列):
    - Group 1 (mock-based): 内部 RelevanceAgent を mock。ADK loaded 不要。
    - Group 2 (ADK integration): google.adk を monkeypatch で fake モジュール化。

multi-persona scoring の挙動も Phase Y 仕様に沿って検証。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.relevance.adk_agent import ADKRelevanceAgent
from agents.relevance.main import RelevanceAgent
from agents.relevance.schema import (
    PersonaRelevanceOutput,
    RelevanceInput,
    RelevanceOutput,
    UserPersona,
)


def _make_persona(user_id: str = "demo-25-29", age_group: str = "25-29") -> UserPersona:
    return UserPersona(
        user_id=user_id,
        age_group=age_group,  # type: ignore[arg-type]
        interests=["住居", "子育て"],  # type: ignore[list-item]
        municipality_codes=["13104"],
    )


def _make_input(persona: UserPersona | None = None) -> RelevanceInput:
    return RelevanceInput(
        speech_id="13104:press-abc:2026-05-29:0",
        content_text="新宿区が家賃補助を新設します。",
        translated_summary=[
            "新宿区の家賃補助、新しく始まるよ。",
            "対象は若い世帯と子育て世帯。",
            "上限月3万円。",
        ],
        title="新宿区の家賃補助スタート",
        speaker_position="区長",
        meeting_context="新宿区プレスリリース 2026-05-29",
        municipality_code="13104",
        user=persona or _make_persona(),
    )


def _make_relevance_output() -> RelevanceOutput:
    return RelevanceOutput(
        relevance_score=85,
        score_topic=22,
        score_age=22,
        score_geographic=23,
        score_urgency=18,
        matched_interests=["住居", "子育て"],  # type: ignore[list-item]
        reasoning="家賃補助は住居関心と直結、新宿区民の登録ペルソナに高関連。",
        contains_political_judgment=False,
    )


def _make_persona_output(user_id: str, score: int = 80) -> PersonaRelevanceOutput:
    return PersonaRelevanceOutput(
        user_id=user_id,
        relevance_score=score,
        score_topic=20,
        score_age=20,
        score_geographic=22,
        score_urgency=18,
        matched_interests=["住居"],  # type: ignore[list-item]
        reasoning="持家・賃貸に関わる",
        contains_political_judgment=False,
    )


# ============================================================================
# Group 1: mock-based (ADK loaded 不要)
# ============================================================================


def test_score_speech_single_delegates_to_relevance_agent() -> None:
    """score_speech_single() は内部 RelevanceAgent.score() に委譲する。"""
    expected = _make_relevance_output()
    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.score.return_value = expected
    mock_relevance.prompt_version = "test-v1"

    adk = ADKRelevanceAgent(relevance=mock_relevance)
    input_ = _make_input()
    result = adk.score_speech_single(input_)

    assert result is expected
    mock_relevance.score.assert_called_once_with(input_)


def test_score_speech_multi_persona_delegates_to_relevance_agent() -> None:
    """score_speech_multi_persona() は内部 score_multi() に personas 含めて委譲。"""
    personas = [_make_persona("p1"), _make_persona("p2", age_group="40-49")]
    expected = [_make_persona_output("p1", 80), _make_persona_output("p2", 50)]

    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.score_multi.return_value = expected

    adk = ADKRelevanceAgent(relevance=mock_relevance)
    input_ = _make_input()
    results = adk.score_speech_multi_persona(input_, personas)

    assert results is expected
    mock_relevance.score_multi.assert_called_once_with(input_, personas)


def test_score_speech_single_propagates_exceptions() -> None:
    """内部 score() の例外はそのまま伝播する。"""
    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.score.side_effect = RuntimeError("Gemini timeout")

    adk = ADKRelevanceAgent(relevance=mock_relevance)
    with pytest.raises(RuntimeError, match="Gemini timeout"):
        adk.score_speech_single(_make_input())


def test_score_speech_single_preserves_output_structure() -> None:
    """RelevanceOutput の各フィールドが保持される。"""
    expected = _make_relevance_output()
    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.score.return_value = expected

    adk = ADKRelevanceAgent(relevance=mock_relevance)
    result = adk.score_speech_single(_make_input())

    assert result.relevance_score == 85
    assert result.score_topic == 22
    assert result.score_age == 22
    assert result.score_geographic == 23
    assert result.score_urgency == 18
    assert result.matched_interests == ["住居", "子育て"]
    assert isinstance(result, RelevanceOutput)


def test_score_speech_multi_persona_preserves_persona_order() -> None:
    """multi の結果は personas 入力順を維持して返る (内部仕様の証跡)。"""
    personas = [_make_persona("p3"), _make_persona("p1"), _make_persona("p2")]
    expected = [
        _make_persona_output("p3", 70),
        _make_persona_output("p1", 80),
        _make_persona_output("p2", 50),
    ]
    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.score_multi.return_value = expected

    adk = ADKRelevanceAgent(relevance=mock_relevance)
    results = adk.score_speech_multi_persona(_make_input(), personas)

    assert [r.user_id for r in results] == ["p3", "p1", "p2"]


def test_prompt_version_property_reflects_internal_relevance() -> None:
    """prompt_version property は内部 RelevanceAgent を transparent に公開。"""
    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.prompt_version = "v2.71"

    adk = ADKRelevanceAgent(relevance=mock_relevance)

    assert adk.prompt_version == "v2.71"


def test_relevance_property_exposes_inner_agent() -> None:
    """relevance property で内部 RelevanceAgent に直接アクセス可能 (debug 用)。"""
    mock_relevance = MagicMock(spec=RelevanceAgent)
    adk = ADKRelevanceAgent(relevance=mock_relevance)

    assert adk.relevance is mock_relevance


def test_default_construction_creates_relevance_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """relevance=None ならデフォルトで RelevanceAgent をインスタンス化する。"""
    constructed: dict[str, object] = {}

    def fake_init(self: RelevanceAgent, **kwargs: object) -> None:
        constructed.update(kwargs)
        self._client = None  # type: ignore[attr-defined]
        self.project_id = kwargs.get("project_id")  # type: ignore[attr-defined]
        self.prompt_version = "v1.0"  # type: ignore[attr-defined]
        self.model = "gemini-2.5-flash"  # type: ignore[attr-defined]

    monkeypatch.setattr(RelevanceAgent, "__init__", fake_init)
    adk = ADKRelevanceAgent(project_id="citify-dev")

    assert constructed.get("project_id") == "citify-dev"
    assert isinstance(adk.relevance, RelevanceAgent)


# ============================================================================
# Group 2: ADK integration (google.adk を monkeypatch で差し替え)
# ============================================================================


def _install_fake_adk(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    fake_Agent = MagicMock(name="Agent")
    fake_FunctionTool = MagicMock(name="FunctionTool")

    fake_adk_module = SimpleNamespace(Agent=fake_Agent)
    fake_adk_tools_module = SimpleNamespace(FunctionTool=fake_FunctionTool)

    monkeypatch.setitem(sys.modules, "google.adk", fake_adk_module)
    monkeypatch.setitem(sys.modules, "google.adk.tools", fake_adk_tools_module)

    return fake_Agent, fake_FunctionTool


def test_as_tools_returns_two_function_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """as_tools() は single / multi の 2 つの FunctionTool を返す。"""
    _, fake_FunctionTool = _install_fake_adk(monkeypatch)

    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.prompt_version = "v1.0"
    mock_relevance.model = "gemini-2.5-flash"

    adk = ADKRelevanceAgent(relevance=mock_relevance)
    tools = adk.as_tools()

    assert len(tools) == 2
    # FunctionTool が 2 回呼ばれている (single, multi)
    assert fake_FunctionTool.call_count == 2
    call_funcs = [call.kwargs["func"] for call in fake_FunctionTool.call_args_list]
    assert adk.score_speech_single in call_funcs
    assert adk.score_speech_multi_persona in call_funcs


def test_as_tool_returns_multi_persona_function_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """as_tool() (単数) は multi-persona の FunctionTool を返す (production default)。"""
    _, fake_FunctionTool = _install_fake_adk(monkeypatch)

    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.prompt_version = "v1.0"
    mock_relevance.model = "gemini-2.5-flash"

    adk = ADKRelevanceAgent(relevance=mock_relevance)
    tool = adk.as_tool()

    fake_FunctionTool.assert_called_once()
    call_kwargs = fake_FunctionTool.call_args.kwargs
    assert call_kwargs["func"] == adk.score_speech_multi_persona
    assert tool is fake_FunctionTool.return_value


def test_as_agent_returns_adk_agent_with_correct_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """as_agent() が ADK Agent を name/model/schemas/tools 付きで生成する。"""
    fake_Agent, fake_FunctionTool = _install_fake_adk(monkeypatch)

    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.prompt_version = "v1.0"
    mock_relevance.model = "gemini-2.5-flash"

    adk = ADKRelevanceAgent(relevance=mock_relevance)
    agent = adk.as_agent(name="relevance_test")

    fake_Agent.assert_called_once()
    call_kwargs = fake_Agent.call_args.kwargs

    assert call_kwargs["name"] == "relevance_test"
    assert call_kwargs["model"] == "gemini-2.5-flash"
    assert call_kwargs["input_schema"] is RelevanceInput
    assert call_kwargs["output_schema"] is RelevanceOutput
    assert isinstance(call_kwargs["instruction"], str)
    assert len(call_kwargs["instruction"]) > 0
    assert isinstance(call_kwargs["description"], str)
    # tools=[single FunctionTool, multi FunctionTool] (2 つ)
    assert len(call_kwargs["tools"]) == 2
    assert agent is fake_Agent.return_value


def test_as_agent_default_name_is_relevance(monkeypatch: pytest.MonkeyPatch) -> None:
    """as_agent() の name パラメータ省略時は 'relevance' になる。"""
    fake_Agent, _ = _install_fake_adk(monkeypatch)

    mock_relevance = MagicMock(spec=RelevanceAgent)
    mock_relevance.prompt_version = "v1.0"
    mock_relevance.model = "gemini-2.5-flash"

    adk = ADKRelevanceAgent(relevance=mock_relevance)
    adk.as_agent()

    assert fake_Agent.call_args.kwargs["name"] == "relevance"
