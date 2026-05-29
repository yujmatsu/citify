"""TimelineAgent unit tests (Plan N)。

テスト戦略:
    - google.genai を MagicMock + SimpleNamespace(parsed=...) で差し替え
    - LLM success / failure / political leak / source_id 捏造 / 縮退 / fallback を網羅
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.timeline.main import (
    MIN_VALID_EVENTS,
    POLITICAL_PERSON_PATTERNS,
    TimelineAgent,
    _detect_political_leak,
)
from agents.timeline.schema import (
    CandidateSpeech,
    TimelineEvent,
    TimelineNarrative,
    TimelineRequest,
)


def _make_candidates(n: int = 5) -> list[CandidateSpeech]:
    return [
        CandidateSpeech(
            speech_id=f"muni:council:sched:order_{i}",
            title=f"議題タイトル {i}",
            summary_first_line=f"議論サマリ {i}",
            meeting_date=date(2026, 3, i + 1),
            municipality_code="13104",
            municipality_name="新宿区",
            speaker_position="議員",
            matched_interests=["住居"],
            relevance_score=80 - i,
        )
        for i in range(n)
    ]


def _make_request(municipality_code: str | None = "13104") -> TimelineRequest:
    return TimelineRequest(
        user_id="test-user",
        theme_interest="住居",
        municipality_code=municipality_code,
        days=90,
    )


def _make_narrative(
    events: list[TimelineEvent] | None = None,
    overall_summary: str = "住居問題は段階的に議論されました。",
) -> TimelineNarrative:
    candidates = _make_candidates(5)
    default_events = [
        TimelineEvent(
            event_date=c.meeting_date or date(2026, 3, 1),
            municipality_code=c.municipality_code,
            municipality_name=c.municipality_name,
            headline=f"見出し {i}",
            detail=f"詳細 {i}",
            source_speech_id=c.speech_id,
            importance=70,
        )
        for i, c in enumerate(candidates)
    ]
    return TimelineNarrative(
        theme_label="住居",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
        overall_summary=overall_summary,
        events=events if events is not None else default_events,
        source="llm",
    )


# ============================================================================
# 1) LLM 成功 path: events 5+ 件で source="llm"
# ============================================================================


def test_narrate_returns_llm_narrative_on_success() -> None:
    candidates = _make_candidates(10)
    narrative = _make_narrative()
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=narrative, text="")

    agent = TimelineAgent(client=client)
    result = agent.narrate(
        candidates,
        _make_request(),
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
    )

    assert result.source == "llm"
    assert len(result.events) == 5
    assert all(e.source_speech_id.startswith("muni:council") for e in result.events)


# ============================================================================
# 2) データ不足 (< 3 件) → empty + source="rule_based"
# ============================================================================


def test_narrate_returns_empty_for_insufficient_candidates() -> None:
    agent = TimelineAgent(client=MagicMock())
    result = agent.narrate(
        _make_candidates(2),
        _make_request(),
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
    )

    assert result.source == "rule_based"
    assert result.events == []
    assert "データが不足" in result.overall_summary


# ============================================================================
# 3) LLM 失敗 (Exception) → rule-based fallback (raw 上位 5)
# ============================================================================


def test_narrate_falls_back_on_llm_exception() -> None:
    candidates = _make_candidates(10)
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("Gemini timeout")

    agent = TimelineAgent(client=client)
    result = agent.narrate(
        candidates,
        _make_request(),
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
    )

    assert result.source == "rule_based"
    assert len(result.events) == 5  # raw 上位 5
    assert "rule-based fallback" in result.overall_summary
    assert "llm_failed" in result.overall_summary


# ============================================================================
# 4) 政治家名 leak (Reviewer Critical #1) → fallback
# ============================================================================


def test_narrate_falls_back_on_political_leak_in_summary() -> None:
    candidates = _make_candidates(10)
    leaky_narrative = _make_narrative(
        overall_summary="石破総理が新住宅政策を発表しました。議論が継続しています。",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky_narrative, text="")

    agent = TimelineAgent(client=client)
    result = agent.narrate(
        candidates,
        _make_request(),
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
    )

    assert result.source == "rule_based"
    assert "political_leak" in result.overall_summary
    # leaked 文字列がユーザー向け出力に残らないこと
    assert "石破総理" not in result.overall_summary


def test_narrate_falls_back_on_party_name_in_event_headline() -> None:
    candidates = _make_candidates(10)
    leaky_events = [
        TimelineEvent(
            event_date=date(2026, 3, 1),
            municipality_code="13104",
            municipality_name="新宿区",
            headline="立憲民主党が反対表明",  # 政党名 leak
            detail="住居政策で意見対立",
            source_speech_id=candidates[0].speech_id,
        ),
        *[
            TimelineEvent(
                event_date=date(2026, 3, i),
                municipality_code="13104",
                municipality_name="新宿区",
                headline=f"見出し {i}",
                detail=f"詳細 {i}",
                source_speech_id=candidates[i - 1].speech_id,
            )
            for i in range(2, 6)
        ],
    ]
    leaky_narrative = _make_narrative(events=leaky_events, overall_summary="議論変遷。")
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky_narrative, text="")

    agent = TimelineAgent(client=client)
    result = agent.narrate(
        candidates,
        _make_request(),
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
    )

    assert result.source == "rule_based"
    # leaked 政党名がユーザー向け出力に残らない
    assert "立憲民主党" not in result.overall_summary


# ============================================================================
# 5) source_speech_id 捏造 → 該当 event 削除、3 件未満なら fallback (Reviewer High #4)
# ============================================================================


def test_narrate_removes_fabricated_source_speech_id() -> None:
    candidates = _make_candidates(10)
    # 5 events のうち最初の 1 つだけ捏造 ID
    events = [
        TimelineEvent(
            event_date=date(2026, 3, 1),
            municipality_code="13104",
            municipality_name="新宿区",
            headline="捏造 event",
            detail="LLM が幻覚した speech",
            source_speech_id="fabricated:speech:id:999",  # candidate 集合外
        ),
        *[
            TimelineEvent(
                event_date=date(2026, 3, i),
                municipality_code="13104",
                municipality_name="新宿区",
                headline=f"見出し {i}",
                detail=f"詳細 {i}",
                source_speech_id=candidates[i - 1].speech_id,
            )
            for i in range(2, 6)  # 4 件 valid
        ],
    ]
    narrative = _make_narrative(events=events)
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=narrative, text="")

    agent = TimelineAgent(client=client)
    result = agent.narrate(
        candidates,
        _make_request(),
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
    )

    # 4 件 valid >= MIN_VALID_EVENTS (3) なので LLM result 維持、捏造 event のみ削除
    assert result.source == "llm"
    assert len(result.events) == 4
    assert all(e.source_speech_id.startswith("muni:council") for e in result.events)


def test_narrate_falls_back_when_too_few_valid_events() -> None:
    """source_speech_id 捏造で 3 件未満になったら fallback。"""
    candidates = _make_candidates(10)
    # 5 events のうち 3 件が捏造、valid は 2 件 → fallback (Reviewer High #4)
    events = [
        TimelineEvent(
            event_date=date(2026, 3, i),
            municipality_code="13104",
            municipality_name="新宿区",
            headline=f"捏造 {i}",
            detail=f"捏造詳細 {i}",
            source_speech_id=f"fake:id:{i}",
        )
        for i in range(1, 4)  # 3 件捏造
    ] + [
        TimelineEvent(
            event_date=date(2026, 3, i),
            municipality_code="13104",
            municipality_name="新宿区",
            headline=f"valid {i}",
            detail=f"valid詳細 {i}",
            source_speech_id=candidates[i - 1].speech_id,
        )
        for i in range(4, 6)  # 2 件 valid
    ]
    narrative = _make_narrative(events=events)
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=narrative, text="")

    agent = TimelineAgent(client=client)
    result = agent.narrate(
        candidates,
        _make_request(),
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
    )

    assert result.source == "rule_based"
    assert "too_few_valid_events" in result.overall_summary
    assert len(result.events) == 5  # raw fallback で 5 件


# ============================================================================
# 6) MIN_VALID_EVENTS = 3 (定数確認)
# ============================================================================


def test_min_valid_events_threshold_is_3() -> None:
    assert MIN_VALID_EVENTS == 3


# ============================================================================
# 7) POLITICAL_PERSON_PATTERNS が主要パターンを捕捉
# ============================================================================


def test_political_person_patterns_detect_titles() -> None:
    assert _detect_political_leak("石破総理が発表") == "石破総理"
    assert _detect_political_leak("田中議員が反対") == "田中議員"
    assert _detect_political_leak("山田市長が言及") == "山田市長"


def test_political_person_patterns_detect_parties() -> None:
    assert _detect_political_leak("自民党が支持") == "自民党"
    assert _detect_political_leak("立憲民主党が反対") == "立憲民主党"


def test_political_person_patterns_pass_clean_text() -> None:
    assert _detect_political_leak("総理大臣が発表") is None
    assert _detect_political_leak("議員側が反対") is None
    assert _detect_political_leak("野党が指摘") is None


def test_political_patterns_count_matches_intent() -> None:
    """POLITICAL_PERSON_PATTERNS が 3 patterns 構成 (役職 / 個人末尾 / 政党)。"""
    assert len(POLITICAL_PERSON_PATTERNS) == 3


# ============================================================================
# 8) Gemini text fallback (parsed=None だが text に JSON)
# ============================================================================


def test_narrate_handles_text_fallback_parse() -> None:
    candidates = _make_candidates(10)
    narrative = _make_narrative()
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(
        parsed=None,
        text=narrative.model_dump_json(),
    )

    agent = TimelineAgent(client=client)
    result = agent.narrate(
        candidates,
        _make_request(),
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
    )

    assert result.source == "llm"
    assert len(result.events) == 5


# ============================================================================
# 9) max_output_tokens / thinking_budget 設定 (Reviewer Critical #2)
# ============================================================================


def test_default_token_budget_meets_reviewer_critical_2() -> None:
    """Reviewer Critical #2: token 見積もり に応じた設定値が定数で明示。"""
    from agents.timeline.main import DEFAULT_MAX_OUTPUT_TOKENS, DEFAULT_THINKING_BUDGET

    assert DEFAULT_MAX_OUTPUT_TOKENS == 2048  # narrative + events 10 × ~150
    assert DEFAULT_THINKING_BUDGET == 512  # CoT 用


# ============================================================================
# 10) candidates の speaker フィールドは schema 上存在しない (Reviewer Critical #1 二重防御)
# ============================================================================


def test_candidate_speech_schema_has_no_speaker_field() -> None:
    """CandidateSpeech は speaker_position のみ、speaker (実名) は schema 上存在しない。"""
    fields = CandidateSpeech.model_fields
    assert "speaker_position" in fields
    assert "speaker" not in fields  # 実名は構造的に排除
