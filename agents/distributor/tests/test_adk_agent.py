"""ADKDistributorAgent のユニットテスト (Plan C)。

テスト戦略 (translator/relevance の test_adk_agent.py と並列):
    - Group 1 (mock-based): 内部 DistributorAgent を mock。ADK loaded 不要。
    - Group 2 (ADK integration): google.adk を monkeypatch で fake モジュール化。

Distributor は LLM 呼ばない (純粋アルゴリズム) ので exception 系の test は少なめ。
"""

from __future__ import annotations

import sys
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.distributor.adk_agent import ADKDistributorAgent
from agents.distributor.main import DistributorAgent
from agents.distributor.schema import FeedCandidate, FeedItem, FeedSnapshot


def _make_candidate(speech_id: str, score: int = 80) -> FeedCandidate:
    return FeedCandidate(
        speech_id=speech_id,
        title=f"記事-{speech_id}",
        summary=["要約1", "要約2", "要約3"],
        tone="casual",
        relevance_score=score,
        score_topic=20,
        score_age=20,
        score_geographic=20,
        score_urgency=20,
        matched_interests=["住居"],
        reasoning="関心軸合致",
        speaker_position="区長",
        municipality_code="13104",
        meeting_date=date(2026, 5, 20),
        meeting_url=f"https://example.lg.jp/news/{speech_id}",
        name_of_meeting="プレスリリース",
    )


def _make_feed_item(speech_id: str, rank: int, score: float = 85.0) -> FeedItem:
    return FeedItem(
        speech_id=speech_id,
        title=f"記事-{speech_id}",
        summary=["要約1", "要約2", "要約3"],
        tone="casual",
        relevance_score=80,
        matched_interests=["住居"],
        reasoning="関心軸合致",
        speaker_position="区長",
        municipality_code="13104",
        meeting_date=date(2026, 5, 20),
        meeting_url=f"https://example.lg.jp/news/{speech_id}",
        name_of_meeting="プレスリリース",
        final_rank=rank,
        adjusted_score=score,
        display_reason="あなたの住居関心と合致",
        diversity_penalty=0.0,
        freshness_boost=5,
    )


# ============================================================================
# Group 1: mock-based (ADK loaded 不要)
# ============================================================================


def test_generate_feed_delegates_to_distributor_agent() -> None:
    """generate_feed() は内部 DistributorAgent.generate_feed() に委譲する。"""
    candidates = [_make_candidate("s1"), _make_candidate("s2", score=60)]
    expected = [_make_feed_item("s1", 1), _make_feed_item("s2", 2, score=70.0)]

    mock_distributor = MagicMock(spec=DistributorAgent)
    mock_distributor.generate_feed.return_value = expected
    mock_distributor.feed_size = 20

    adk = ADKDistributorAgent(distributor=mock_distributor)
    result = adk.generate_feed(candidates)

    assert result is expected
    mock_distributor.generate_feed.assert_called_once_with(candidates)


def test_generate_feed_propagates_exceptions() -> None:
    """内部 generate_feed() の例外はそのまま伝播する。"""
    mock_distributor = MagicMock(spec=DistributorAgent)
    mock_distributor.generate_feed.side_effect = ValueError("invalid candidate")

    adk = ADKDistributorAgent(distributor=mock_distributor)

    with pytest.raises(ValueError, match="invalid candidate"):
        adk.generate_feed([_make_candidate("s1")])


def test_generate_feed_preserves_output_structure() -> None:
    """FeedItem の各フィールドが保持される。"""
    expected = [_make_feed_item("s1", 1), _make_feed_item("s2", 2)]
    mock_distributor = MagicMock(spec=DistributorAgent)
    mock_distributor.generate_feed.return_value = expected
    mock_distributor.feed_size = 20

    adk = ADKDistributorAgent(distributor=mock_distributor)
    result = adk.generate_feed([_make_candidate("s1"), _make_candidate("s2")])

    assert len(result) == 2
    assert result[0].final_rank == 1
    assert result[1].final_rank == 2
    assert all(isinstance(item, FeedItem) for item in result)


def test_feed_size_property_reflects_internal_distributor() -> None:
    """feed_size property は内部 DistributorAgent を transparent に公開。"""
    mock_distributor = MagicMock(spec=DistributorAgent)
    mock_distributor.feed_size = 50

    adk = ADKDistributorAgent(distributor=mock_distributor)

    assert adk.feed_size == 50


def test_distributor_property_exposes_inner_agent() -> None:
    """distributor property で内部 DistributorAgent に直接アクセス可能 (debug 用)。"""
    mock_distributor = MagicMock(spec=DistributorAgent)
    adk = ADKDistributorAgent(distributor=mock_distributor)

    assert adk.distributor is mock_distributor


def test_default_construction_creates_distributor_agent() -> None:
    """distributor=None ならデフォルトで DistributorAgent をインスタンス化する。"""
    adk = ADKDistributorAgent(min_relevance=60, feed_size=30)

    assert isinstance(adk.distributor, DistributorAgent)
    assert adk.distributor.min_relevance == 60
    assert adk.distributor.feed_size == 30


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


def test_as_tool_returns_function_tool_wrapping_generate_feed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """as_tool() が FunctionTool(func=generate_feed) を返す。"""
    _, fake_FunctionTool = _install_fake_adk(monkeypatch)

    mock_distributor = MagicMock(spec=DistributorAgent)
    mock_distributor.feed_size = 20

    adk = ADKDistributorAgent(distributor=mock_distributor)
    tool = adk.as_tool()

    fake_FunctionTool.assert_called_once()
    call_kwargs = fake_FunctionTool.call_args.kwargs
    assert "func" in call_kwargs
    assert call_kwargs["func"] == adk.generate_feed
    assert tool is fake_FunctionTool.return_value


def test_as_agent_returns_adk_agent_with_correct_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """as_agent() が ADK Agent を name/model/output_schema/tools 付きで生成する。"""
    fake_Agent, fake_FunctionTool = _install_fake_adk(monkeypatch)

    mock_distributor = MagicMock(spec=DistributorAgent)
    mock_distributor.feed_size = 20

    adk = ADKDistributorAgent(distributor=mock_distributor)
    agent = adk.as_agent(name="distributor_test")

    fake_Agent.assert_called_once()
    call_kwargs = fake_Agent.call_args.kwargs

    assert call_kwargs["name"] == "distributor_test"
    assert call_kwargs["model"] == "gemini-2.5-flash"
    assert call_kwargs["output_schema"] is FeedSnapshot
    assert isinstance(call_kwargs["instruction"], str)
    assert len(call_kwargs["instruction"]) > 0
    assert isinstance(call_kwargs["description"], str)
    assert len(call_kwargs["tools"]) == 1
    assert call_kwargs["tools"][0] is fake_FunctionTool.return_value
    assert agent is fake_Agent.return_value


def test_as_agent_default_name_is_distributor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """as_agent() の name パラメータ省略時は 'distributor' になる。"""
    fake_Agent, _ = _install_fake_adk(monkeypatch)

    mock_distributor = MagicMock(spec=DistributorAgent)
    mock_distributor.feed_size = 20

    adk = ADKDistributorAgent(distributor=mock_distributor)
    adk.as_agent()

    assert fake_Agent.call_args.kwargs["name"] == "distributor"
