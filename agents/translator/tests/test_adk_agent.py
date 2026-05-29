"""ADKTranslatorAgent のユニットテスト (Plan C)。

テスト戦略:
    - **Group 1 (mock-based)**: 内部 TranslatorAgent を mock。ADK loaded 不要。
    - **Group 2 (ADK integration)**: 実際の `from google.adk import Agent` を
       monkeypatch で差し替えて検証。CI 環境では skip 可能 (ADK の重い import
       を避ける)。

既存の `test_translator.py` の `_MockGenAIClient` パターンと整合する。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.translator.adk_agent import ADKTranslatorAgent
from agents.translator.main import TranslatorAgent
from agents.translator.schema import TranslateInput, TranslatorOutput


def _make_input() -> TranslateInput:
    return TranslateInput(
        speech_id="13104:press-abc:2026-05-29:0",
        content_text="令和8年度予算案を本日公表しました。総額1,500億円。",
        speaker=None,
        speaker_position="区長",
        speaker_group=None,
        meeting_context="新宿区プレスリリース 2026-05-29",
        age_group="25-29",
    )


def _make_output() -> TranslatorOutput:
    return TranslatorOutput(
        title="新宿区の予算1500億円公表",
        summary=[
            "新宿区の来年度予算が今日発表されたよ。",
            "総額は1,500億円で結構大きい。",
            "区長コメント付きでホームページに載ってる。",
        ],
        tone="casual",
        contains_politician_names=False,
        contains_political_judgment=False,
        notes="",
    )


# ============================================================================
# Group 1: mock-based (ADK loaded 不要)
# ============================================================================


def test_translate_speech_delegates_to_translator_agent() -> None:
    """translate_speech() は内部 TranslatorAgent.translate() を呼ぶだけ。"""
    expected = _make_output()
    mock_translator = MagicMock(spec=TranslatorAgent)
    mock_translator.translate.return_value = expected
    mock_translator.prompt_version = "test-v1"

    adk = ADKTranslatorAgent(translator=mock_translator)
    input_ = _make_input()
    result = adk.translate_speech(input_)

    assert result is expected
    mock_translator.translate.assert_called_once_with(input_)


def test_translate_speech_propagates_exceptions() -> None:
    """内部 translate() が例外を投げたら ADK wrapper はそのまま伝播する。"""
    mock_translator = MagicMock(spec=TranslatorAgent)
    mock_translator.translate.side_effect = RuntimeError("Gemini timeout")

    adk = ADKTranslatorAgent(translator=mock_translator)

    with pytest.raises(RuntimeError, match="Gemini timeout"):
        adk.translate_speech(_make_input())


def test_translate_speech_preserves_output_structure() -> None:
    """入出力は TranslatorOutput Pydantic schema をそのまま通す。"""
    expected = _make_output()
    mock_translator = MagicMock(spec=TranslatorAgent)
    mock_translator.translate.return_value = expected

    adk = ADKTranslatorAgent(translator=mock_translator)
    result = adk.translate_speech(_make_input())

    # Pydantic Output の全フィールドが保持される
    assert result.title == expected.title
    assert result.summary == expected.summary
    assert result.tone == expected.tone
    assert result.contains_politician_names == expected.contains_politician_names
    assert result.contains_political_judgment == expected.contains_political_judgment
    assert isinstance(result, TranslatorOutput)


def test_prompt_version_property_reflects_internal_translator() -> None:
    """prompt_version property は内部 TranslatorAgent の値を transparent に返す。"""
    mock_translator = MagicMock(spec=TranslatorAgent)
    mock_translator.prompt_version = "v3.14"

    adk = ADKTranslatorAgent(translator=mock_translator)

    assert adk.prompt_version == "v3.14"


def test_translator_property_exposes_inner_agent() -> None:
    """translator property で内部 TranslatorAgent に直接アクセス可能 (debug 用)。"""
    mock_translator = MagicMock(spec=TranslatorAgent)
    adk = ADKTranslatorAgent(translator=mock_translator)

    assert adk.translator is mock_translator


def test_default_construction_creates_translator_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """translator=None ならデフォルトで TranslatorAgent をインスタンス化する。"""
    constructed: dict[str, object] = {}

    def fake_init(self: TranslatorAgent, **kwargs: object) -> None:
        constructed.update(kwargs)
        self._client = None  # type: ignore[attr-defined]
        self.project_id = kwargs.get("project_id")  # type: ignore[attr-defined]
        self.prompt_version = "v1.0"  # type: ignore[attr-defined]
        self.model = "gemini-2.5-flash"  # type: ignore[attr-defined]

    monkeypatch.setattr(TranslatorAgent, "__init__", fake_init)
    adk = ADKTranslatorAgent(project_id="citify-dev")

    assert constructed.get("project_id") == "citify-dev"
    assert isinstance(adk.translator, TranslatorAgent)


# ============================================================================
# Group 2: ADK integration (google.adk を monkeypatch で差し替え)
# ============================================================================


def _install_fake_adk(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    """google.adk と google.adk.tools を fake モジュールに置き換える。

    Returns:
        (fake_Agent_class, fake_FunctionTool_class) のタプル
    """
    fake_Agent = MagicMock(name="Agent")
    fake_FunctionTool = MagicMock(name="FunctionTool")

    fake_adk_module = SimpleNamespace(Agent=fake_Agent)
    fake_adk_tools_module = SimpleNamespace(FunctionTool=fake_FunctionTool)

    monkeypatch.setitem(sys.modules, "google.adk", fake_adk_module)
    monkeypatch.setitem(sys.modules, "google.adk.tools", fake_adk_tools_module)

    return fake_Agent, fake_FunctionTool


def test_as_tool_returns_function_tool_wrapping_translate_speech(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """as_tool() が FunctionTool(func=translate_speech) を返す。"""
    _, fake_FunctionTool = _install_fake_adk(monkeypatch)

    mock_translator = MagicMock(spec=TranslatorAgent)
    mock_translator.prompt_version = "v1.0"
    mock_translator.model = "gemini-2.5-flash"

    adk = ADKTranslatorAgent(translator=mock_translator)
    tool = adk.as_tool()

    # FunctionTool(func=adk.translate_speech) で呼ばれていることを確認
    fake_FunctionTool.assert_called_once()
    call_kwargs = fake_FunctionTool.call_args.kwargs
    assert "func" in call_kwargs
    # bound method の同一性は `==` で比較 (`is` は毎回新規 method オブジェクトで失敗する)
    assert call_kwargs["func"] == adk.translate_speech
    assert tool is fake_FunctionTool.return_value


def test_as_agent_returns_adk_agent_with_correct_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """as_agent() が ADK Agent を name/model/schemas/tools 付きで生成する。"""
    fake_Agent, fake_FunctionTool = _install_fake_adk(monkeypatch)

    mock_translator = MagicMock(spec=TranslatorAgent)
    mock_translator.prompt_version = "v1.0"
    mock_translator.model = "gemini-2.5-flash"

    adk = ADKTranslatorAgent(translator=mock_translator)
    agent = adk.as_agent(name="translator_test")

    # Agent(name=..., model=..., instruction=..., input_schema=..., output_schema=..., tools=[...])
    # が 1 回呼ばれている
    fake_Agent.assert_called_once()
    call_kwargs = fake_Agent.call_args.kwargs

    assert call_kwargs["name"] == "translator_test"
    assert call_kwargs["model"] == "gemini-2.5-flash"
    assert call_kwargs["input_schema"] is TranslateInput
    assert call_kwargs["output_schema"] is TranslatorOutput
    assert isinstance(call_kwargs["instruction"], str)
    assert len(call_kwargs["instruction"]) > 0
    assert isinstance(call_kwargs["description"], str)
    assert len(call_kwargs["description"]) > 0
    # tools=[FunctionTool(...)]
    assert "tools" in call_kwargs
    assert len(call_kwargs["tools"]) == 1
    assert call_kwargs["tools"][0] is fake_FunctionTool.return_value
    assert agent is fake_Agent.return_value


def test_as_agent_default_name_is_translator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """as_agent() の name パラメータ省略時は 'translator' になる。"""
    fake_Agent, _ = _install_fake_adk(monkeypatch)

    mock_translator = MagicMock(spec=TranslatorAgent)
    mock_translator.prompt_version = "v1.0"
    mock_translator.model = "gemini-2.5-flash"

    adk = ADKTranslatorAgent(translator=mock_translator)
    adk.as_agent()

    call_kwargs = fake_Agent.call_args.kwargs
    assert call_kwargs["name"] == "translator"
