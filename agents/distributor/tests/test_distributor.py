"""DistributorAgent のテスト (LLM 不要、純粋ロジック)。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from agents.distributor.main import DistributorAgent
from agents.distributor.schema import FeedCandidate

TODAY = date(2026, 5, 21)


def _cand(
    speech_id: str,
    relevance: int = 70,
    interests: list[str] | None = None,
    speaker: str | None = None,
    days_ago: int = 10,
) -> FeedCandidate:
    """テスト用 FeedCandidate ファクトリ。"""
    return FeedCandidate(
        speech_id=speech_id,
        title=f"title-{speech_id}",
        summary=[f"L1-{speech_id}", f"L2-{speech_id}", f"L3-{speech_id}"],
        relevance_score=relevance,
        score_topic=relevance // 4,
        score_age=relevance // 4,
        score_geographic=relevance // 4,
        score_urgency=relevance // 4,
        matched_interests=interests or [],
        speaker_position=speaker,
        municipality_code="00000",
        meeting_date=TODAY - timedelta(days=days_ago),
    )


# ============================================================================
# Filter
# ============================================================================


def test_empty_candidates_returns_empty_feed():
    agent = DistributorAgent(today=TODAY)
    assert agent.generate_feed([]) == []


def test_all_below_threshold_returns_empty_feed():
    agent = DistributorAgent(today=TODAY, min_relevance=50)
    candidates = [_cand(f"c{i}", relevance=30) for i in range(5)]
    assert agent.generate_feed(candidates) == []


def test_filters_below_min_relevance():
    """50 未満は捨てる、50 以上のみ feed に。"""
    agent = DistributorAgent(today=TODAY, min_relevance=50, feed_size=10)
    candidates = [
        _cand("high", relevance=80),
        _cand("low", relevance=40),  # 捨てられる
        _cand("mid", relevance=55),
    ]
    feed = agent.generate_feed(candidates)
    assert len(feed) == 2
    assert {f.speech_id for f in feed} == {"high", "mid"}


# ============================================================================
# Sorting + final_rank
# ============================================================================


def test_higher_relevance_ranked_first():
    """同条件なら relevance_score 高い順。"""
    agent = DistributorAgent(today=TODAY, feed_size=3)
    candidates = [
        _cand("low", relevance=55),
        _cand("high", relevance=90),
        _cand("mid", relevance=70),
    ]
    feed = agent.generate_feed(candidates)
    assert feed[0].speech_id == "high"
    assert feed[1].speech_id == "mid"
    assert feed[2].speech_id == "low"
    assert [f.final_rank for f in feed] == [1, 2, 3]


def test_feed_size_caps_results():
    agent = DistributorAgent(today=TODAY, feed_size=3)
    candidates = [_cand(f"c{i}", relevance=70 + i) for i in range(10)]
    feed = agent.generate_feed(candidates)
    assert len(feed) == 3


# ============================================================================
# Diversity penalty
# ============================================================================


def test_diversity_penalty_prefers_different_interests():
    """同 interest 連続を避け、別 interest を選ぶ。"""
    agent = DistributorAgent(today=TODAY, feed_size=3, diversity_weight=0.5, freshness_boost=0)
    # 3 件、全部 relevance=70 だが interests が違う
    # c1: 子育て (top に最初に出る)
    # c2: 子育て (重複ペナルティ受ける)
    # c3: 教育 (重複なしで 2 番目に来るはず)
    candidates = [
        _cand("c1", relevance=80, interests=["子育て"], days_ago=10),
        _cand("c2", relevance=70, interests=["子育て"], days_ago=10),
        _cand("c3", relevance=70, interests=["教育"], days_ago=10),
    ]
    feed = agent.generate_feed(candidates)
    assert feed[0].speech_id == "c1"  # 最高関連度
    # c3 が c2 より上に来るはず (c2 は子育て重複でペナルティ)
    assert feed[1].speech_id == "c3"
    assert feed[2].speech_id == "c2"


def test_diversity_zero_weight_pure_relevance_order():
    """diversity_weight=0 なら relevance 順そのまま。"""
    agent = DistributorAgent(
        today=TODAY,
        feed_size=3,
        diversity_weight=0.0,
        freshness_boost=0,
        speaker_repetition_penalty=0,
    )
    candidates = [
        _cand("c1", relevance=80, interests=["子育て"]),
        _cand("c2", relevance=75, interests=["子育て"]),  # 重複だが penalty=0 なので順位維持
        _cand("c3", relevance=70, interests=["教育"]),
    ]
    feed = agent.generate_feed(candidates)
    assert [f.speech_id for f in feed] == ["c1", "c2", "c3"]


# ============================================================================
# Freshness boost
# ============================================================================


def test_recent_speech_gets_freshness_boost():
    """同 relevance なら新しい方が上に。"""
    agent = DistributorAgent(today=TODAY, feed_size=2, diversity_weight=0)
    candidates = [
        _cand("old", relevance=70, days_ago=120),  # 古い (-5)
        _cand("new", relevance=70, days_ago=5),  # 新鮮 (+5)
    ]
    feed = agent.generate_feed(candidates)
    assert feed[0].speech_id == "new"
    assert feed[0].freshness_boost == 5
    assert feed[1].speech_id == "old"
    assert feed[1].freshness_boost == -5


def test_neutral_age_no_boost():
    """30-90 日は boost なし。"""
    agent = DistributorAgent(today=TODAY)
    candidates = [_cand("neutral", relevance=70, days_ago=60)]
    feed = agent.generate_feed(candidates)
    assert feed[0].freshness_boost == 0


# ============================================================================
# Speaker repetition
# ============================================================================


def test_speaker_repetition_penalty():
    """同 speaker_position 連続を避ける (penalty=5、確実に再順位)。"""
    agent = DistributorAgent(today=TODAY, feed_size=3, diversity_weight=0, freshness_boost=0)
    candidates = [
        _cand("c1", relevance=80, speaker="内閣総理大臣"),
        _cand("c2", relevance=78, speaker="内閣総理大臣"),  # 同 speaker、penalty 受ける
        _cand("c3", relevance=75, speaker="衆議院議長"),  # 別 speaker
    ]
    feed = agent.generate_feed(candidates)
    assert feed[0].speech_id == "c1"
    # c2 は同 speaker でペナルティ -5 → 73 < 75, c3 が 2 番目
    assert feed[1].speech_id == "c3"
    assert feed[2].speech_id == "c2"


# ============================================================================
# display_reason
# ============================================================================


def test_display_reason_includes_matched_interests():
    agent = DistributorAgent(today=TODAY)
    candidates = [_cand("c1", relevance=80, interests=["子育て", "住居"])]
    feed = agent.generate_feed(candidates)
    reason = feed[0].display_reason
    assert "子育て" in reason
    assert "住居" in reason
    assert "80" in reason


def test_display_reason_fallback_when_no_matched_interests():
    agent = DistributorAgent(today=TODAY)
    candidates = [_cand("c1", relevance=70, interests=[])]
    feed = agent.generate_feed(candidates)
    reason = feed[0].display_reason
    assert "70" in reason


def test_display_reason_truncates_to_three_interests():
    """matched_interests が 4 件あっても reason は 3 件まで。"""
    agent = DistributorAgent(today=TODAY)
    candidates = [_cand("c1", relevance=80, interests=["子育て", "住居", "教育", "雇用"])]
    feed = agent.generate_feed(candidates)
    reason = feed[0].display_reason
    # 4 件目の "雇用" は出ない
    assert "雇用" not in reason


# ============================================================================
# Schema / 例外系
# ============================================================================


def test_invalid_diversity_weight_raises():
    with pytest.raises(ValueError, match="diversity_weight"):
        DistributorAgent(diversity_weight=1.5)


def test_meeting_date_none_yields_zero_freshness():
    agent = DistributorAgent(today=TODAY)
    cand = _cand("c1", relevance=70)
    cand = cand.model_copy(update={"meeting_date": None})
    feed = agent.generate_feed([cand])
    assert feed[0].freshness_boost == 0
