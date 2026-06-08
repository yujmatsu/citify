"""前提抽出の純関数 test (TASK-ONBOARDING / F)。ADK 呼び出しは対象外。"""

from __future__ import annotations

from agents.preferences.extract import _parse_extracted


def test_parse_extracted_sanitizes_interests_and_priorities() -> None:
    raw = (
        '{"interests":["医療","子育て","未知の軸"],'
        '"priorities":["医療","子育て","税"],'  # 税 は interests に無い→除外
        '"household":"family_kids","budget_man":3000,'
        '"background_summary":"子育て環境を重視して移住を検討"}'
    )
    out = _parse_extracted(raw)
    assert out["interests"] == ["医療", "子育て"]  # 未知の軸を除去
    assert out["priorities"] == ["医療", "子育て"]  # interests の部分集合のみ
    assert out["household"] == "family_kids"
    assert out["budget_man"] == 3000
    assert out["background_summary"].startswith("子育て")


def test_parse_extracted_invalid_household_and_budget() -> None:
    out = _parse_extracted('{"household":"bogus","budget_man":-5,"interests":[]}')
    assert out["household"] == ""  # 未知の家族構成→空
    assert out["budget_man"] is None  # 非正→None


def test_parse_extracted_drops_forbidden_summary() -> None:
    out = _parse_extracted('{"background_summary":"必ず投票に行くべき","interests":["医療"]}')
    assert out["background_summary"] == ""  # 倫理違反は破棄
    assert out["interests"] == ["医療"]


def test_parse_extracted_bad_input() -> None:
    for bad in ("", "ただの文章", "{壊れたJSON"):
        out = _parse_extracted(bad)
        assert out["interests"] == []
        assert out["priorities"] == []
        assert out["budget_man"] is None


def test_parse_extracted_priorities_max3() -> None:
    raw = (
        '{"interests":["医療","子育て","住居","教育"],"priorities":["医療","子育て","住居","教育"]}'
    )
    out = _parse_extracted(raw)
    assert len(out["priorities"]) == 3  # 上位3に制限
