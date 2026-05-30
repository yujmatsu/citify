"""MetaReasoningAgent unit tests (Plan PP)。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.reasoner.main import (
    _RULE_BASED_TEMPLATES,
    MetaReasoningAgent,
    _validate_input_leaks,
    _validate_output_leaks,
)
from agents.reasoner.schema import (
    AgentName,
    ReasoningExplanation,
    ReasoningInspectInput,
)


def _make_input(
    agent_name: AgentName = "forecast",
    raw_reasoning: str = "過去 6 か月で件数が安定して増加、月あたり 2 件のペース。",
    agent_output_summary: str = "住居議題は緩やかに増加",
    persona_context: str | None = "25-29 / 住居軸",
) -> ReasoningInspectInput:
    return ReasoningInspectInput(
        agent_name=agent_name,
        raw_reasoning=raw_reasoning,
        agent_output_summary=agent_output_summary,
        persona_context=persona_context,
    )


def _make_explanation(
    plain_summary: str = "住居議題は緩やかに増加傾向で、Agent は線形回帰で予測しました。",
    factors: list[str] | None = None,
    counterfactuals: list[str] | None = None,
    caveats: list[str] | None = None,
) -> ReasoningExplanation:
    return ReasoningExplanation(
        plain_summary=plain_summary,
        influencing_factors=factors or ["過去 6 か月の月別件数", "線形回帰の slope"],
        counterfactuals=counterfactuals or ["もし期間が短ければ信頼度は低くなります"],
        caveats=caveats or ["線形外挿は季節性を無視します"],
        confidence="medium",
        source="llm",
    )


# ============================================================================
# 1) LLM 成功 path
# ============================================================================


def test_explain_returns_llm_explanation_on_success() -> None:
    expected = _make_explanation()
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=expected, text="")

    agent = MetaReasoningAgent(client=client)
    result = agent.explain(_make_input())
    assert result.source == "llm"
    assert len(result.influencing_factors) >= 1
    assert len(result.counterfactuals) >= 1


# ============================================================================
# 2) LLM 失敗 → rule_based fallback (agent 別テンプレ)
# ============================================================================


def test_explain_falls_back_on_llm_exception() -> None:
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("API down")

    agent = MetaReasoningAgent(client=client)
    result = agent.explain(_make_input(agent_name="forecast"))
    assert result.source == "rule_based"
    assert "(rule-based)" in result.plain_summary
    assert "llm_failed" in result.plain_summary
    # forecast 用テンプレが適用される
    assert any("月別件数" in f or "slope" in f for f in result.influencing_factors)


# ============================================================================
# 3) 入力 leak 連鎖防止 (Reviewer High #1)
# ============================================================================


def test_explain_falls_back_on_raw_reasoning_leak() -> None:
    """raw_reasoning に固有名詞があれば LLM call せずに fallback。"""
    leaky_input = _make_input(
        raw_reasoning="石破総理が新政策を出したため、住居議題が増加傾向。",
    )
    client = MagicMock()
    agent = MetaReasoningAgent(client=client)
    result = agent.explain(leaky_input)

    assert result.source == "rule_based"
    assert "input_leak_chain_prevent" in result.plain_summary
    # LLM call は呼ばれない (連鎖防止)
    client.models.generate_content.assert_not_called()


def test_explain_falls_back_on_agent_output_summary_leak() -> None:
    """agent_output_summary にも leak チェック (Reviewer High #1)。"""
    leaky_input = _make_input(
        agent_output_summary="東京都の住居議題が活発で増加",
    )
    client = MagicMock()
    agent = MetaReasoningAgent(client=client)
    result = agent.explain(leaky_input)

    assert result.source == "rule_based"
    client.models.generate_content.assert_not_called()


def test_explain_falls_back_on_persona_context_leak() -> None:
    """persona_context にも leak チェック (Reviewer High #1、3 フィールド完全カバー)。"""
    leaky_input = _make_input(
        persona_context="新宿区在住、住居検討中",
    )
    client = MagicMock()
    agent = MetaReasoningAgent(client=client)
    result = agent.explain(leaky_input)

    assert result.source == "rule_based"
    client.models.generate_content.assert_not_called()


# ============================================================================
# 4) 出力 leak 検出 → fallback (Reviewer Medium #4)
# ============================================================================


def test_explain_falls_back_on_output_leak_in_plain_summary() -> None:
    leaky_explanation = _make_explanation(
        plain_summary="東京都での住居議題が増加、Agent は線形回帰で予測しました。",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky_explanation, text="")

    agent = MetaReasoningAgent(client=client)
    result = agent.explain(_make_input())
    assert result.source == "rule_based"
    assert "東京都" not in result.plain_summary


def test_explain_falls_back_on_output_leak_in_counterfactuals() -> None:
    """counterfactuals 内の leak も検出 (hallucination 防止)。"""
    leaky_explanation = _make_explanation(
        counterfactuals=["新宿区なら別の傾向が見える"],  # 固有名詞 leak
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky_explanation, text="")

    agent = MetaReasoningAgent(client=client)
    result = agent.explain(_make_input())
    assert result.source == "rule_based"
    # 出力 leak fallback でも leaked 文字列が含まれない
    assert not any("新宿区" in c for c in result.counterfactuals)


def test_explain_falls_back_on_output_leak_in_factors() -> None:
    leaky_explanation = _make_explanation(
        factors=["北海道の人口動態", "線形回帰"],
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky_explanation, text="")

    agent = MetaReasoningAgent(client=client)
    result = agent.explain(_make_input())
    assert result.source == "rule_based"


# ============================================================================
# 5) _RULE_BASED_TEMPLATES が 7 種 agent 全カバー
# ============================================================================


def test_rule_based_templates_cover_all_7_agents() -> None:
    """7 種 AgentName 全てに rule_based fallback テンプレ。"""
    expected = {
        "concierge",
        "translator",
        "critic",
        "heatmap_advisor",
        "timeline",
        "forecast",
        "scraper_doctor",
    }
    assert set(_RULE_BASED_TEMPLATES.keys()) == expected
    for template in _RULE_BASED_TEMPLATES.values():
        assert "factor" in template
        assert "counterfactual" in template


# ============================================================================
# 6) plain_summary が raw_reasoning と完全一致しない (DoD: 単なる原文コピーでない)
# ============================================================================


def test_plain_summary_differs_from_raw_reasoning() -> None:
    """LLM 出力時、plain_summary が raw_reasoning と完全一致しない (Meta-Agent の付加価値)。"""
    raw = "過去 6 か月で件数が安定して増加、月あたり 2 件のペース。"
    expected = _make_explanation(
        plain_summary=(
            "Agent は過去半年の月別議題数を分析し、安定した増加傾向を検出しました。"
            "線形外挿で 3 か月先を予測。"
        ),
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=expected, text="")

    agent = MetaReasoningAgent(client=client)
    result = agent.explain(_make_input(raw_reasoning=raw))
    assert result.plain_summary != raw  # 完全一致は NG


# ============================================================================
# 7) _validate_input_leaks helper の動作確認
# ============================================================================


def test_validate_input_leaks_returns_field_name_on_leak() -> None:
    inp = _make_input(raw_reasoning="石破総理の発言で住居議題増")
    result = _validate_input_leaks(inp)
    assert result is not None
    assert "raw_reasoning" in result


def test_validate_input_leaks_returns_none_when_clean() -> None:
    inp = _make_input()
    assert _validate_input_leaks(inp) is None


# ============================================================================
# 8) _validate_output_leaks helper の動作確認
# ============================================================================


def test_validate_output_leaks_detects_in_caveats() -> None:
    explanation = _make_explanation(caveats=["大阪府限定の傾向"])
    leak = _validate_output_leaks(explanation)
    assert leak == "大阪府"


def test_validate_output_leaks_returns_none_when_clean() -> None:
    explanation = _make_explanation()
    assert _validate_output_leaks(explanation) is None


# ============================================================================
# 9) AgentName Literal が 7 種限定 (Pydantic validation)
# ============================================================================


def test_agent_name_literal_rejects_unknown() -> None:
    """unknown agent_name は Pydantic で reject。"""
    import pytest as _pytest
    from pydantic import ValidationError

    with _pytest.raises(ValidationError):
        ReasoningInspectInput(
            agent_name="unknown_agent",  # type: ignore[arg-type]
            raw_reasoning="x",
            agent_output_summary="y",
        )


# ============================================================================
# 10) 全 7 種 agent_name で rule_based fallback が動く (LLM 失敗時)
# ============================================================================


def test_all_7_agent_names_have_working_fallback() -> None:
    """全 agent_name で LLM 失敗時に rule_based を返せる。"""
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("LLM down")
    agent = MetaReasoningAgent(client=client)

    for agent_name in [
        "concierge",
        "translator",
        "critic",
        "heatmap_advisor",
        "timeline",
        "forecast",
        "scraper_doctor",
    ]:
        result = agent.explain(_make_input(agent_name=agent_name))  # type: ignore[arg-type]
        assert result.source == "rule_based"
        assert result.plain_summary
        assert len(result.influencing_factors) >= 1
