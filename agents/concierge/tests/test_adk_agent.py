"""ADKConciergeAgent (adk_agent.py) のユニットテスト (Plan E Phase 2)。

テスト戦略 (Plan C の test_adk_agent.py パターンと並列):
    - Group 1 (mock-based): 内部 sub-agents (Translator/Relevance) を mock 注入
    - Group 2 (ADK integration): google.adk + google.adk.tools を monkeypatch で
      fake モジュール化、as_agent() / as_tools() の引数を検証
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.concierge.adk_agent import ADKConciergeAgent
from agents.relevance.adk_agent import ADKRelevanceAgent
from agents.translator.adk_agent import ADKTranslatorAgent

# ============================================================================
# Group 1: mock-based (ADK loaded 不要)
# ============================================================================


def test_translator_property_exposes_inner_sub_agent() -> None:
    """translator property で sub-agent に直接アクセス可能 (debug 用)。"""
    mock_translator = MagicMock(spec=ADKTranslatorAgent)
    adk = ADKConciergeAgent(translator=mock_translator)

    assert adk.translator is mock_translator


def test_relevance_property_exposes_inner_sub_agent() -> None:
    """relevance property で sub-agent に直接アクセス可能 (debug 用)。"""
    mock_relevance = MagicMock(spec=ADKRelevanceAgent)
    adk = ADKConciergeAgent(relevance=mock_relevance)

    assert adk.relevance is mock_relevance


def test_default_construction_creates_sub_agents() -> None:
    """translator / relevance 未注入時はデフォルトで ADK wrapper をインスタンス化。"""
    adk = ADKConciergeAgent(project_id="citify-dev")

    assert isinstance(adk.translator, ADKTranslatorAgent)
    assert isinstance(adk.relevance, ADKRelevanceAgent)


# ============================================================================
# Group 2: ADK integration (google.adk を monkeypatch で差し替え)
# ============================================================================


def _install_fake_adk(monkeypatch: pytest.MonkeyPatch) -> tuple[MagicMock, MagicMock]:
    """google.adk + google.adk.tools を fake モジュールに置き換え。"""
    fake_Agent = MagicMock(name="Agent")
    fake_FunctionTool = MagicMock(name="FunctionTool")

    fake_adk_module = SimpleNamespace(Agent=fake_Agent)
    fake_adk_tools_module = SimpleNamespace(FunctionTool=fake_FunctionTool)

    monkeypatch.setitem(sys.modules, "google.adk", fake_adk_module)
    monkeypatch.setitem(sys.modules, "google.adk.tools", fake_adk_tools_module)

    return fake_Agent, fake_FunctionTool


def test_as_tools_returns_four_function_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """as_tools() は 4 つの FunctionTool を返す (search/compare/dashboard/speeches)。"""
    _, fake_FunctionTool = _install_fake_adk(monkeypatch)

    mock_translator = MagicMock(spec=ADKTranslatorAgent)
    mock_relevance = MagicMock(spec=ADKRelevanceAgent)

    adk = ADKConciergeAgent(translator=mock_translator, relevance=mock_relevance)
    tools = adk.as_tools()

    assert len(tools) == 4
    assert fake_FunctionTool.call_count == 4
    # 各 call に func= が渡っている
    func_names = [
        call.kwargs.get("func").__name__
        for call in fake_FunctionTool.call_args_list
        if "func" in call.kwargs
    ]
    assert "search_municipalities" in func_names
    assert "compare_municipalities" in func_names
    assert "fetch_city_dashboard" in func_names
    assert "fetch_city_speeches" in func_names


def test_as_agent_returns_adk_agent_with_tools_and_sub_agents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """as_agent() が ADK Agent を tools + sub_agents 構成で生成する。"""
    fake_Agent, fake_FunctionTool = _install_fake_adk(monkeypatch)

    # sub-agent の as_agent() は MagicMock で「fake Agent」を返すよう設定
    mock_translator = MagicMock(spec=ADKTranslatorAgent)
    mock_translator.as_agent.return_value = MagicMock(name="translator_agent_obj")
    mock_relevance = MagicMock(spec=ADKRelevanceAgent)
    mock_relevance.as_agent.return_value = MagicMock(name="relevance_agent_obj")

    adk = ADKConciergeAgent(
        project_id="citify-dev",
        translator=mock_translator,
        relevance=mock_relevance,
    )
    agent = adk.as_agent(name="concierge_test")

    # Agent(name=, description=, model=, instruction=, tools=[4], sub_agents=[2]) で呼ばれる
    fake_Agent.assert_called_once()
    call_kwargs = fake_Agent.call_args.kwargs

    assert call_kwargs["name"] == "concierge_test"
    assert call_kwargs["model"] == "gemini-2.5-flash"
    assert isinstance(call_kwargs["instruction"], str)
    assert len(call_kwargs["instruction"]) > 100  # system prompt は長め
    assert isinstance(call_kwargs["description"], str)
    assert len(call_kwargs["description"]) > 0

    # tools: 4 個
    assert len(call_kwargs["tools"]) == 4
    assert fake_FunctionTool.call_count == 4

    # sub_agents: 2 個 (translator, relevance)
    assert len(call_kwargs["sub_agents"]) == 2

    # sub_agent.as_agent() が呼ばれている (name= 引数も検証)
    mock_translator.as_agent.assert_called_once_with(name="translator")
    mock_relevance.as_agent.assert_called_once_with(name="relevance")

    assert agent is fake_Agent.return_value


def test_as_agent_default_name_is_concierge(monkeypatch: pytest.MonkeyPatch) -> None:
    """as_agent() の name 省略時は 'concierge'。"""
    fake_Agent, _ = _install_fake_adk(monkeypatch)

    mock_translator = MagicMock(spec=ADKTranslatorAgent)
    mock_translator.as_agent.return_value = MagicMock()
    mock_relevance = MagicMock(spec=ADKRelevanceAgent)
    mock_relevance.as_agent.return_value = MagicMock()

    adk = ADKConciergeAgent(translator=mock_translator, relevance=mock_relevance)
    adk.as_agent()

    assert fake_Agent.call_args.kwargs["name"] == "concierge"


def test_build_runner_kwargs_returns_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_runner_kwargs() は {'agent': <Agent instance>} を返す。"""
    fake_Agent, _ = _install_fake_adk(monkeypatch)
    fake_Agent.return_value = MagicMock(name="concierge_agent_instance")

    mock_translator = MagicMock(spec=ADKTranslatorAgent)
    mock_translator.as_agent.return_value = MagicMock()
    mock_relevance = MagicMock(spec=ADKRelevanceAgent)
    mock_relevance.as_agent.return_value = MagicMock()

    adk = ADKConciergeAgent(translator=mock_translator, relevance=mock_relevance)
    kwargs = adk.build_runner_kwargs()

    assert "agent" in kwargs
    assert kwargs["agent"] is fake_Agent.return_value
