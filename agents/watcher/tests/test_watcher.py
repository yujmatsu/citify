"""WatcherAgent の純粋ロジック test (TASK-WATCHER Slice 3.5)。

ADK Runner I/O (自律ループ) は実環境 smoke で検証するため、ここでは ADK 非依存の
parse_analysis / apply_ethics / run-log / schema を検証する。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from agents.watcher.main import WatcherAgent, apply_ethics, parse_analysis
from agents.watcher.schema import (
    AgentRunLog,
    TownAnalysis,
    TownAssessment,
    WatchInput,
    WatchVerdict,
)


def _analysis(
    headline: str = "今は小田原が子育て面でリード",
    reasoning: str = "人口は両市とも微減だが小田原は子育て施設が多い",
    home_headline: str = "住み慣れた基準の街",
    political: bool = False,
) -> TownAnalysis:
    return TownAnalysis(
        verdict=WatchVerdict(
            headline=headline,
            reasoning=reasoning,
            recommended_code="27206",
            contains_political_judgment=political,
        ),
        town_assessments=[
            TownAssessment(
                municipality_code="11227",
                role="home",
                headline=home_headline,
                strengths=["通勤至便"],
                concerns=["人口微減"],
                population_outlook="2070 まで緩やかに減少",
                source_speech_ids=["sp-1"],
                fit_score=60,
            ),
            TownAssessment(
                municipality_code="27206",
                role="candidate",
                headline="子育て施設が充実",
                strengths=["子育て施設多い"],
                concerns=[],
                population_outlook="横ばい",
                fit_score=75,
            ),
        ],
        watch_points=["小田原の住居コストの動向"],
    )


def _analysis_json(**kw: object) -> str:
    return json.dumps(_analysis(**kw).model_dump(), ensure_ascii=False)  # type: ignore[arg-type]


# ============================================================================
# WatchInput.all_codes
# ============================================================================


def test_all_codes_dedup_home_first() -> None:
    w = WatchInput(
        user_id="demo-40-49",
        age_group="40-49",
        interests=["子育て"],
        home_municipality_code="11227",
        watched_codes=["13104", "11227", "27100"],  # 11227 重複
    )
    assert w.all_codes() == ["11227", "13104", "27100"]  # home 先頭・重複除去


def test_all_codes_truncates_to_max5() -> None:
    w = WatchInput(
        user_id="u",
        age_group="40-49",
        home_municipality_code="00001",
        watched_codes=["00002", "00003", "00004", "00005", "00006", "00007"],
    )
    codes = w.all_codes()
    assert len(codes) == 5
    assert codes[0] == "00001"


# ============================================================================
# parse_analysis
# ============================================================================


def test_parse_valid_json() -> None:
    a = parse_analysis(_analysis_json())
    assert a is not None
    assert a.verdict.headline.startswith("今は小田原")
    assert [t.role for t in a.town_assessments] == ["home", "candidate"]
    assert a.town_assessments[1].municipality_code == "27206"


def test_parse_json_with_surrounding_text() -> None:
    text = f"はい、分析しました:\n{_analysis_json()}\n以上です。"
    a = parse_analysis(text)
    assert a is not None and a.verdict.recommended_code == "27206"


def test_parse_confidence_and_open_questions() -> None:
    """A7: confidence / open_questions をパースできる。"""
    text = (
        '{"verdict":{"headline":"今は朝霞が安心","reasoning":"人口が安定",'
        '"recommended_code":"11227","confidence":"high","contains_political_judgment":false},'
        '"town_assessments":[{"municipality_code":"11227","role":"home","headline":"安定",'
        '"confidence":"high","source_speech_ids":["sp-1"]}],'
        '"watch_points":[],"open_questions":["小田原の待機児童の最新状況"]}'
    )
    a = parse_analysis(text)
    assert a is not None
    assert a.verdict.confidence == "high"
    assert a.town_assessments[0].confidence == "high"
    assert a.open_questions == ["小田原の待機児童の最新状況"]


def test_parse_confidence_defaults_medium_when_absent() -> None:
    """confidence 未指定でも後方互換 (default medium)。"""
    a = parse_analysis(_analysis_json())
    assert a is not None
    assert a.verdict.confidence == "medium"


def test_parse_empty_verdict_returns_none() -> None:
    text = (
        '{"verdict":{"headline":"","reasoning":"","recommended_code":null,'
        '"contains_political_judgment":false},"town_assessments":[],"watch_points":[]}'
    )
    assert parse_analysis(text) is None


def test_parse_invalid_or_missing_verdict_returns_none() -> None:
    assert parse_analysis("これはJSONではありません") is None
    assert parse_analysis("") is None
    assert parse_analysis('{"town_assessments": []}') is None  # verdict キー無し


# ============================================================================
# apply_ethics (倫理ゲート)
# ============================================================================


def test_ethics_keeps_clean_analysis() -> None:
    assert apply_ethics(_analysis()) is not None


def test_ethics_none_passthrough() -> None:
    assert apply_ethics(None) is None


def test_ethics_drops_forbidden_in_verdict() -> None:
    bad = _analysis(reasoning="この政策には必ず投票しましょう")
    assert apply_ethics(bad) is None


def test_ethics_drops_forbidden_in_assessment() -> None:
    bad = _analysis(home_headline="絶対に賛成すべき議案がある街")
    assert apply_ethics(bad) is None


def test_ethics_drops_self_flagged_political() -> None:
    assert apply_ethics(_analysis(political=True)) is None


# ============================================================================
# _persist (repo 注入で永続化、None なら skip)
# ============================================================================


def test_persist_skips_when_no_repo() -> None:
    agent = WatcherAgent(repo=None)
    agent._persist("u", AgentRunLog(run_id="r1", user_id="u"), _analysis())


def test_persist_calls_repo() -> None:
    repo = MagicMock()
    agent = WatcherAgent(repo=repo)
    log = AgentRunLog(run_id="r1", user_id="demo-40-49")
    analysis = _analysis()
    agent._persist("demo-40-49", log, analysis)
    repo.save_run.assert_called_once_with(log)
    repo.save_analysis.assert_called_once_with("demo-40-49", "r1", analysis)


def test_persist_skips_analysis_when_none() -> None:
    repo = MagicMock()
    agent = WatcherAgent(repo=repo)
    log = AgentRunLog(run_id="r1", user_id="u")
    agent._persist("u", log, None)
    repo.save_run.assert_called_once_with(log)
    repo.save_analysis.assert_not_called()


def test_persist_graceful_on_repo_failure() -> None:
    repo = MagicMock()
    repo.save_run.side_effect = RuntimeError("firestore down")
    agent = WatcherAgent(repo=repo)
    agent._persist("u", AgentRunLog(run_id="r1", user_id="u"), _analysis())
