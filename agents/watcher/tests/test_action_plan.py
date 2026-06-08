"""移住アクションプラン純関数の test (TASK-ACTIONPLAN)。

assemble/select/reasons/links/filter/parse を検証。generate_visit_checklist (ADK) は対象外。
"""

from __future__ import annotations

from agents.watcher.action_plan import (
    PORTAL_URL,
    _filter_forbidden,
    _parse_checklist,
    assemble_action_plan,
    build_reasons,
    construct_official_links,
    select_recommended,
)
from agents.watcher.schema import TownAnalysis, TownAssessment, WatchVerdict

_LINKS = {"14206": ("https://www.city.odawara.kanagawa.jp/", "小田原市 公式サイト")}


def _analysis(recommended: str | None, *assessments: TownAssessment) -> TownAnalysis:
    return TownAnalysis(
        verdict=WatchVerdict(
            headline="小田原が優勢", reasoning="人口減が緩やか", recommended_code=recommended
        ),
        town_assessments=list(assessments),
        open_questions=["通勤時間を確認"],
    )


def _candidate(code: str, fit: int = 50) -> TownAssessment:
    return TownAssessment(
        municipality_code=code,
        role="candidate",
        headline="候補",
        strengths=["財政健全"],
        fit_score=fit,
    )


def _home(code: str, fit: int = 50) -> TownAssessment:
    return TownAssessment(
        municipality_code=code,
        role="home",
        headline="今の街",
        strengths=["住み慣れ"],
        fit_score=fit,
    )


def test_select_recommended_prefers_verdict_code() -> None:
    a = _analysis("14206", _candidate("13104", 90), _candidate("14206", 40))
    sel = select_recommended(a)
    assert sel is not None
    rec, mode = sel
    assert rec.municipality_code == "14206"  # fit_score でなく verdict.recommended_code 優先
    assert mode == "relocate"


def test_select_recommended_fallback_to_max_fit() -> None:
    a = _analysis(None, _candidate("13104", 40), _candidate("14206", 88))
    sel = select_recommended(a)
    assert sel is not None
    assert sel[0].municipality_code == "14206"


def test_select_recommended_home_is_stay_mode() -> None:
    a = _analysis("14206", _home("14206", 70))
    sel = select_recommended(a)
    assert sel is not None
    assert sel[1] == "stay"


def test_select_recommended_none_when_no_assessments() -> None:
    assert select_recommended(_analysis("14206")) is None


def test_build_reasons_reasoning_first_then_strengths() -> None:
    a = _analysis("14206", _candidate("14206"))
    reasons = build_reasons(a, a.town_assessments[0])
    assert reasons[0] == "人口減が緩やか"  # verdict.reasoning が先頭
    assert "財政健全" in reasons


def test_construct_links_seed_then_portal() -> None:
    # seed あり → 公式URL
    links = construct_official_links("14206", "小田原市", "relocate", _LINKS)
    assert links[0].url == "https://www.city.odawara.kanagawa.jp/"
    # seed なし → 信頼ポータルへフォールバック
    fb = construct_official_links("99999", "どこか市", "relocate", _LINKS)
    assert fb[0].url == PORTAL_URL
    assert "どこか市" in fb[0].label


def test_construct_links_stay_is_empty() -> None:
    assert construct_official_links("14206", "小田原市", "stay", _LINKS) == []


def test_assemble_relocate_full() -> None:
    a = _analysis("14206", _candidate("14206", 80))
    plan = assemble_action_plan(
        a, {"14206": "小田原市"}, ["朝の通勤帯の混雑を見る"], "run1", "2026-06-08T00:00:00Z", _LINKS
    )
    assert plan is not None
    assert plan.mode == "relocate"
    assert plan.recommended_name == "小田原市"
    assert plan.decision_summary == "小田原が優勢"
    assert plan.open_questions == ["通勤時間を確認"]
    assert plan.visit_checklist == ["朝の通勤帯の混雑を見る"]
    assert plan.official_links[0].label == "小田原市 公式サイト"


def test_assemble_stay_no_links() -> None:
    a = _analysis("14206", _home("14206", 70))
    plan = assemble_action_plan(a, {"14206": "小田原市"}, [], "run2", "now", _LINKS)
    assert plan is not None
    assert plan.mode == "stay"
    assert plan.official_links == []


def test_assemble_none_when_no_assessments() -> None:
    assert assemble_action_plan(_analysis(None), {}, [], "r", "t", _LINKS) is None


def test_filter_forbidden_drops_political_items() -> None:
    # find_forbidden_matches の実パターン (処方 / 必ず投票 等) に該当する項目を除去
    items = ["朝の通勤帯の混雑を見る", "必ず投票に行くべき", "移住を処方します", ""]
    out = _filter_forbidden(items)
    assert out == ["朝の通勤帯の混雑を見る"]


def test_parse_checklist_handles_bad_input() -> None:
    assert _parse_checklist("") == []
    assert _parse_checklist("説明文だけ") == []
    assert _parse_checklist('{"items": ["A", "B", ""]}') == ["A", "B"]
    assert _parse_checklist('前後に文字 {"items":["X"]} あり') == ["X"]
