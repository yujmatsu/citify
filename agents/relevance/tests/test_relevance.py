"""RelevanceAgent のユニットテスト (Gemini mock)。"""

from __future__ import annotations

import pytest

from agents.relevance.main import RelevanceAgent
from agents.relevance.schema import RelevanceInput, RelevanceOutput, UserPersona


class _MockGenAIModels:
    def __init__(self, responses: list[RelevanceOutput]) -> None:
        self.responses = list(responses)
        self.call_count = 0
        self.last_call_args: dict = {}

    def generate_content(self, *, model: str, contents: str, config: object) -> object:
        self.last_call_args = {"model": model, "contents": contents, "config": config}
        idx = min(self.call_count, len(self.responses) - 1)
        self.call_count += 1
        parsed = self.responses[idx]

        class _MockResponse:
            def __init__(self, parsed: RelevanceOutput) -> None:
                self.parsed = parsed
                self.text = parsed.model_dump_json()

        return _MockResponse(parsed)


class _MockGenAIClient:
    def __init__(self, responses: list[RelevanceOutput]) -> None:
        self.models = _MockGenAIModels(responses)


def _make_good_output(score: int = 75) -> RelevanceOutput:
    """relevance_score が score、4 軸が均等に近い形の正常出力。"""
    per_dim = score // 4
    return RelevanceOutput(
        relevance_score=score,
        score_topic=per_dim + (score - per_dim * 4),  # remainder を topic に
        score_age=per_dim,
        score_geographic=per_dim,
        score_urgency=per_dim,
        matched_interests=["子育て"],
        reasoning="子育て世代向けの政策議論が含まれており、関心軸と合致する。",
        contains_political_judgment=False,
    )


def _make_input() -> RelevanceInput:
    return RelevanceInput(
        speech_id="test-1",
        content_text="このため、こども未来戦略の加速化プランに基づき、児童手当を拡充する。",
        translated_summary=None,
        title=None,
        speaker_position="内閣総理大臣",
        meeting_context="衆議院 本会議 第16号 2026-05-18",
        municipality_code="00000",
        user=UserPersona(
            user_id="test-user",
            age_group="25-29",
            interests=["子育て", "住居"],
            municipality_codes=["13104", "00000"],
        ),
    )


# ============================================================================
# 正常系
# ============================================================================


def test_score_returns_output_on_first_call():
    output = _make_good_output(80)
    client = _MockGenAIClient([output])
    agent = RelevanceAgent(project_id="test", client=client)

    result = agent.score(_make_input())

    assert client.models.call_count == 1
    assert result.relevance_score == 80
    assert "子育て" in result.matched_interests


def test_score_passes_persona_to_prompt():
    """ペルソナ情報 (年代/関心軸/自治体) が prompt に含まれる。"""
    client = _MockGenAIClient([_make_good_output()])
    agent = RelevanceAgent(project_id="test", client=client)

    agent.score(_make_input())

    contents = client.models.last_call_args["contents"]
    assert "25-29" in contents
    assert "子育て" in contents
    assert "13104" in contents


def test_score_uses_translated_summary_when_available():
    """translated_summary があれば prompt にそちらを使う。"""
    client = _MockGenAIClient([_make_good_output()])
    agent = RelevanceAgent(project_id="test", client=client)

    inp = _make_input().model_copy(
        update={
            "translated_summary": [
                "国は若い世代の所得を増やす。",
                "児童手当を拡充する。",
                "切れ目ない支援を行う。",
            ],
            "title": "子育て支援強化へ",
        }
    )
    agent.score(inp)

    contents = client.models.last_call_args["contents"]
    assert "子育て支援強化へ" in contents
    assert "児童手当を拡充する" in contents
    assert "A-5 翻訳サマリ" in contents


# ============================================================================
# Score normalization (LLM 算数ミス対策)
# ============================================================================


def test_score_normalizes_when_dimensions_disagree():
    """4 軸合計と relevance_score が 5 点以上ずれたら 4 軸合計を採用。"""
    bad = RelevanceOutput(
        relevance_score=50,  # 自己申告
        score_topic=20,
        score_age=20,
        score_geographic=20,
        score_urgency=20,  # 合計 = 80 (差 30)
        matched_interests=[],
        reasoning="...",
        contains_political_judgment=False,
    )
    client = _MockGenAIClient([bad])
    agent = RelevanceAgent(project_id="test", client=client)

    result = agent.score(_make_input())

    assert result.relevance_score == 80  # 4 軸合計に補正
    assert result.score_topic == 20


def test_score_keeps_when_difference_is_small():
    """4 軸合計と relevance_score の差が 5 未満なら補正しない。"""
    almost = RelevanceOutput(
        relevance_score=60,  # 自己申告
        score_topic=15,
        score_age=15,
        score_geographic=15,
        score_urgency=15,  # 合計 = 60 (差 0)
        matched_interests=[],
        reasoning="...",
        contains_political_judgment=False,
    )
    client = _MockGenAIClient([almost])
    agent = RelevanceAgent(project_id="test", client=client)

    result = agent.score(_make_input())

    assert result.relevance_score == 60


# ============================================================================
# 倫理ガードレール
# ============================================================================


def test_political_judgment_self_report_triggers_retry():
    bad = RelevanceOutput(
        relevance_score=70,
        score_topic=20,
        score_age=20,
        score_geographic=15,
        score_urgency=15,
        matched_interests=["子育て"],
        reasoning="この政策は素晴らしいので強く推奨する。",
        contains_political_judgment=True,  # 自己申告 True
    )
    good = _make_good_output()
    client = _MockGenAIClient([bad, good])
    agent = RelevanceAgent(project_id="test", client=client)

    result = agent.score(_make_input())

    assert client.models.call_count == 2
    assert result.contains_political_judgment is False


def test_forbidden_pattern_in_reasoning_triggers_retry():
    bad = RelevanceOutput(
        relevance_score=70,
        score_topic=20,
        score_age=20,
        score_geographic=15,
        score_urgency=15,
        matched_interests=["子育て"],
        reasoning="この施策に投票推奨します。",  # 禁止語
        contains_political_judgment=False,
    )
    good = _make_good_output()
    client = _MockGenAIClient([bad, good])
    agent = RelevanceAgent(project_id="test", client=client)

    agent.score(_make_input())

    assert client.models.call_count == 2


def test_three_retries_then_below_threshold():
    bad = RelevanceOutput(
        relevance_score=70,
        score_topic=20,
        score_age=20,
        score_geographic=15,
        score_urgency=15,
        matched_interests=[],
        reasoning="必ず投票してください。",  # 禁止語
        contains_political_judgment=False,
    )
    client = _MockGenAIClient([bad, bad, bad])
    agent = RelevanceAgent(project_id="test", client=client)

    result = agent.score(_make_input())

    assert client.models.call_count == 3
    assert result.relevance_score == 0  # below_threshold


# ============================================================================
# 早期 return
# ============================================================================


def test_empty_input_returns_below_threshold():
    client = _MockGenAIClient([_make_good_output()])
    agent = RelevanceAgent(project_id="test", client=client)

    inp = _make_input().model_copy(update={"content_text": "  "})
    result = agent.score(inp)

    assert client.models.call_count == 0
    assert result.relevance_score == 0


# ============================================================================
# Schema バリデーション
# ============================================================================


def test_score_bounds_validation():
    """score_topic > 25 で ValidationError。"""
    with pytest.raises(Exception):  # noqa: B017
        RelevanceOutput(
            relevance_score=30,
            score_topic=26,  # 上限超過
            score_age=10,
            score_geographic=10,
            score_urgency=10,
            matched_interests=[],
            reasoning="...",
            contains_political_judgment=False,
        )


def test_relevance_score_max_100():
    """relevance_score > 100 で ValidationError。"""
    with pytest.raises(Exception):  # noqa: B017
        RelevanceOutput(
            relevance_score=101,
            score_topic=25,
            score_age=25,
            score_geographic=25,
            score_urgency=25,
            matched_interests=[],
            reasoning="...",
            contains_political_judgment=False,
        )
