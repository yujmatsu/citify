"""WatcherAgent の純粋ロジック test (TASK-WATCHER Slice 3.5)。

ADK Runner I/O (自律ループ) は実環境 smoke で検証するため、ここでは ADK 非依存の
parse_analysis / apply_ethics / run-log / schema を検証する。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.watcher.main import (
    COVERAGE_FLOOR_DOMAINS,
    WatcherAgent,
    _coverage_missing,
    _finding_from_response,
    apply_ethics,
    diff_against_previous,
    parse_advocacy,
    parse_analysis,
    parse_critique,
    parse_finding,
    should_revise,
)
from agents.watcher.schema import (
    AgentRunLog,
    Critique,
    SpecialistFinding,
    ToolCall,
    TownAnalysis,
    TownAssessment,
    WatcherResult,
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


# ============================================================================
# P2: critique / advocacy / should_revise (純関数)
# ============================================================================


def test_parse_critique_valid() -> None:
    c = parse_critique(
        '{"issues":["矛盾A"],"missing_axes":["治安"],"grounding_failures":[],"needs_revision":true}'
    )
    assert c is not None and c.needs_revision is True
    assert "治安" in c.missing_axes


def test_parse_advocacy_valid() -> None:
    a = parse_advocacy(
        'はい:\n{"counter_verdict":"実は小田原が良い","strongest_points":["住居費が安い"]}'
    )
    assert a is not None and a.counter_verdict.startswith("実は")


def test_parse_critique_invalid_returns_none() -> None:
    assert parse_critique("not json") is None


def test_should_revise_logic() -> None:
    assert should_revise(None) is False
    assert should_revise(Critique(needs_revision=True)) is True
    assert should_revise(Critique(issues=["x"])) is True  # 指摘あれば修正
    assert should_revise(Critique()) is False  # 空なら不要


# ============================================================================
# P2: _verify_and_revise オーケストレーション (_run_single_agent を mock)
# ============================================================================


def _watch() -> WatchInput:
    return WatchInput(
        user_id="demo-40-49",
        age_group="40-49",
        interests=["子育て"],
        home_municipality_code="11227",
        watched_codes=["27206"],
    )


@pytest.mark.asyncio
async def test_verify_and_revise_revises_when_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = WatcherAgent(repo=None)
    revised = _analysis(headline="再検討の結果、朝霞が安心")
    calls = [
        '{"issues":["治安に未言及"],"missing_axes":["治安"],"grounding_failures":[],"needs_revision":true}',
        '{"counter_verdict":"小田原も捨てがたい","strongest_points":["住居費"]}',
        json.dumps(revised.model_dump(), ensure_ascii=False),
    ]
    it = iter(calls)

    async def _fake(instruction: str, message: str) -> str:
        return next(it)

    monkeypatch.setattr(agent, "_run_single_agent", _fake)
    out, crit_note, adv_note = await agent._verify_and_revise(_analysis(), _watch(), None)
    assert out.verdict.headline == "再検討の結果、朝霞が安心"  # revise 反映
    assert "治安" in crit_note
    assert adv_note.startswith("小田原")


# ============================================================================
# P3: parse_finding / マルチエージェント run() オーケストレーション
# ============================================================================


def test_parse_finding_valid() -> None:
    f = parse_finding(
        '{"headline":"財政は朝霞が安定","key_points":["財政力 朝霞0.98 > 小田原0.95"],'
        '"confidence":"high","source_speech_ids":[]}',
        "fiscal",
    )
    assert f is not None and f.domain == "fiscal" and f.confidence == "high"


def test_parse_finding_forces_canonical_domain() -> None:
    """LLM が domain に日本語ラベルを入れても正規キーに強制 (UI 整合)。"""
    f = parse_finding('{"domain":"財政アナリスト","headline":"x","confidence":"high"}', "fiscal")
    assert f is not None and f.domain == "fiscal"


# ============================================================================
# P4: diff_against_previous (変化検知、純関数)
# ============================================================================

_NAMES = {"11227": "朝霞市", "27206": "小田原市"}


def test_diff_first_run_no_changes() -> None:
    assert diff_against_previous(None, _analysis(), _NAMES) == []


def test_diff_detects_recommended_change() -> None:
    prev = _analysis()  # recommended_code = 27206
    cur = _analysis()
    cur.verdict.recommended_code = "11227"
    changes = diff_against_previous(prev, cur, _NAMES)
    assert any("小田原市" in c and "朝霞市" in c for c in changes)


def test_diff_detects_fit_score_change() -> None:
    prev = _analysis()  # 11227 fit 60, 27206 fit 75
    cur = _analysis()
    cur.town_assessments[0].fit_score = 70  # 60 → 70
    changes = diff_against_previous(prev, cur, _NAMES)
    assert any("朝霞市" in c and "60" in c and "70" in c and "上昇" in c for c in changes)


def test_diff_ignores_small_fit_change() -> None:
    prev = _analysis()
    cur = _analysis()
    cur.town_assessments[0].fit_score = 62  # 60 → 62 (< 5、無視)
    assert diff_against_previous(prev, cur, _NAMES) == []


def test_parse_finding_invalid_returns_none() -> None:
    assert parse_finding("not json", "fiscal") is None


@pytest.mark.asyncio
async def test_run_multi_agent_orchestration(monkeypatch: pytest.MonkeyPatch) -> None:
    """run() が 4専門家 → synth → critique/advocate を回し analysis を組み立てる (crew モード)。"""
    monkeypatch.setenv("WATCHER_AUTONOMY_MODE", "crew")
    agent = WatcherAgent(repo=None)

    async def fake_spec(
        domain: str, watch: WatchInput, town_names: dict[str, str] | None
    ) -> tuple[SpecialistFinding, list[ToolCall], int | None]:
        return (
            SpecialistFinding(domain=domain, headline=f"{domain}所見", confidence="medium"),
            [ToolCall(tool="compare_towns")],
            10,
        )

    monkeypatch.setattr(agent, "_run_specialist", fake_spec)

    synth = json.dumps(_analysis().model_dump(), ensure_ascii=False)
    critique = '{"issues":[],"missing_axes":[],"grounding_failures":[],"needs_revision":false}'
    advocacy = '{"counter_verdict":"","strongest_points":[]}'
    seq = iter([synth, critique, advocacy])

    async def fake_single(instruction: str, message: str) -> str:
        return next(seq)

    monkeypatch.setattr(agent, "_run_single_agent", fake_single)

    res = await agent.run(_watch())
    assert res.run_log.status == "ok"
    assert res.analysis is not None
    # 4専門家の所見が付与され、tool_calls も集約される
    assert len(res.analysis.specialist_findings) == 4
    assert len(res.run_log.tool_calls) == 4
    assert res.analysis.verdict.headline  # synth 由来


@pytest.mark.asyncio
async def test_run_empty_when_all_specialists_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WATCHER_AUTONOMY_MODE", "crew")
    agent = WatcherAgent(repo=None)

    async def fake_spec(
        domain: str, watch: WatchInput, town_names: dict[str, str] | None
    ) -> tuple[None, list[ToolCall], None]:
        return (None, [], None)

    monkeypatch.setattr(agent, "_run_specialist", fake_spec)
    res = await agent.run(_watch())
    assert res.analysis is None
    assert res.run_log.status == "empty"


# ============================================================================
# Lv3: Coordinator dispatch / fallback / _finding_from_response / _finalize
# ============================================================================


def test_finding_from_response_str_json() -> None:
    f = _finding_from_response(
        '{"headline":"人口は横ばい","key_points":["朝霞 > 小田原"],"confidence":"medium"}',
        "population",
    )
    assert f is not None and f.domain == "population" and f.headline.startswith("人口")


def test_finding_from_response_dict_wrapped() -> None:
    """ADK が {"result": "<json文字列>"} で包んでも抽出できる。"""
    f = _finding_from_response(
        {"result": '{"headline":"財政は安定","confidence":"high"}'}, "fiscal"
    )
    assert f is not None and f.domain == "fiscal" and f.confidence == "high"


def test_finding_from_response_dict_direct() -> None:
    f = _finding_from_response({"headline": "治安良好", "confidence": "high"}, "living_safety")
    assert f is not None and f.domain == "living_safety"


def test_finding_from_response_garbage_is_none() -> None:
    assert _finding_from_response("ただの文章", "topics") is None
    assert _finding_from_response(None, "topics") is None


def test_coverage_missing() -> None:
    """カバレッジ床: 揃っていないコア専門家ドメインを返す。"""
    # 何も無ければコア全部が不足
    assert _coverage_missing([]) == list(COVERAGE_FLOOR_DOMAINS)
    # population + living_safety + topics が揃えば不足なし
    full = [SpecialistFinding(domain=d, headline="x") for d in COVERAGE_FLOOR_DOMAINS]
    assert _coverage_missing(full) == []
    # living_safety だけなら population と topics が不足 (本番 smoke の偏りケース)
    only_ls = [SpecialistFinding(domain="living_safety", headline="x")]
    assert _coverage_missing(only_ls) == ["population", "topics"]
    # fiscal は床に含まれないので、fiscal を持っていても不足判定には効かない
    only_fiscal = [SpecialistFinding(domain="fiscal", headline="x")]
    assert _coverage_missing(only_fiscal) == list(COVERAGE_FLOOR_DOMAINS)


def test_finalize_attaches_investigation_plan() -> None:
    """_finalize が investigation_plan を analysis に載せ、ok で締める (coordinator 共通の締め)。"""
    agent = WatcherAgent(repo=None)
    res = agent._finalize(
        _watch(),
        "run-x",
        None,
        _analysis(),
        True,
        [ToolCall(tool="record_plan"), ToolCall(tool="specialist_population")],
        12,
        [SpecialistFinding(domain="population", headline="x")],
        town_names=_NAMES,
        investigation_plan=["子育てと医療を重点調査", "将来人口も確認"],
    )
    assert res.analysis is not None
    assert res.analysis.investigation_plan == ["子育てと医療を重点調査", "将来人口も確認"]
    assert res.run_log.status == "ok"
    assert res.run_log.tool_calls[0].tool == "record_plan"


@pytest.mark.asyncio
async def test_run_dispatches_to_coordinator(monkeypatch: pytest.MonkeyPatch) -> None:
    """既定(coordinator)では _run_coordinator が使われ、結論が出れば crew は呼ばれない。"""
    monkeypatch.setenv("WATCHER_AUTONOMY_MODE", "coordinator")
    agent = WatcherAgent(repo=None)
    expected = WatcherResult(analysis=_analysis(), run_log=AgentRunLog(run_id="c1", user_id="u"))

    async def fake_coord(
        watch: WatchInput, town_names: dict[str, str] | None = None
    ) -> WatcherResult:
        return expected

    async def fail_crew(
        watch: WatchInput, town_names: dict[str, str] | None = None
    ) -> WatcherResult:
        raise AssertionError("crew should not be called when coordinator succeeds")

    monkeypatch.setattr(agent, "_run_coordinator", fake_coord)
    monkeypatch.setattr(agent, "_run_crew", fail_crew)
    res = await agent.run(_watch())
    assert res is expected


@pytest.mark.asyncio
async def test_run_falls_back_to_crew_on_coordinator_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """coordinator が例外で落ちたら crew にフォールバックして結論を出す (回帰防止)。"""
    monkeypatch.setenv("WATCHER_AUTONOMY_MODE", "coordinator")
    agent = WatcherAgent(repo=None)

    async def boom(watch: WatchInput, town_names: dict[str, str] | None = None) -> WatcherResult:
        raise RuntimeError("AgentTool import failed")

    monkeypatch.setattr(agent, "_run_coordinator", boom)

    # crew 内部 (専門家 + synth/critique/advocate) を mock
    async def fake_spec(
        domain: str, watch: WatchInput, town_names: dict[str, str] | None
    ) -> tuple[SpecialistFinding, list[ToolCall], int | None]:
        return (SpecialistFinding(domain=domain, headline=f"{domain}所見"), [], None)

    monkeypatch.setattr(agent, "_run_specialist", fake_spec)
    seq = iter(
        [
            json.dumps(_analysis().model_dump(), ensure_ascii=False),
            '{"issues":[],"missing_axes":[],"grounding_failures":[],"needs_revision":false}',
            '{"counter_verdict":"","strongest_points":[]}',
        ]
    )

    async def fake_single(instruction: str, message: str) -> str:
        return next(seq)

    monkeypatch.setattr(agent, "_run_single_agent", fake_single)
    res = await agent.run(_watch())
    assert res.analysis is not None  # crew が結論を出した
    assert res.run_log.status == "ok"


@pytest.mark.asyncio
async def test_run_falls_back_to_crew_when_coordinator_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """coordinator が analysis=None を返しても crew にフォールバックする。"""
    monkeypatch.setenv("WATCHER_AUTONOMY_MODE", "coordinator")
    agent = WatcherAgent(repo=None)

    async def empty_coord(
        watch: WatchInput, town_names: dict[str, str] | None = None
    ) -> WatcherResult:
        return WatcherResult(analysis=None, run_log=AgentRunLog(run_id="e1", user_id="u"))

    crew_result = WatcherResult(
        analysis=_analysis(), run_log=AgentRunLog(run_id="crew1", user_id="u")
    )

    async def fake_crew(
        watch: WatchInput, town_names: dict[str, str] | None = None
    ) -> WatcherResult:
        return crew_result

    monkeypatch.setattr(agent, "_run_coordinator", empty_coord)
    monkeypatch.setattr(agent, "_run_crew", fake_crew)
    res = await agent.run(_watch())
    assert res is crew_result


@pytest.mark.asyncio
async def test_verify_and_revise_keeps_draft_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = WatcherAgent(repo=None)
    draft = _analysis(headline="据え置きの結論")
    calls = [
        '{"issues":[],"missing_axes":[],"grounding_failures":[],"needs_revision":false}',
        '{"counter_verdict":"","strongest_points":[]}',
    ]
    it = iter(calls)

    async def _fake(instruction: str, message: str) -> str:
        return next(it)

    monkeypatch.setattr(agent, "_run_single_agent", _fake)
    out, crit_note, adv_note = await agent._verify_and_revise(draft, _watch(), None)
    assert out.verdict.headline == "据え置きの結論"  # 修正なし
    assert crit_note == "" and adv_note == ""
