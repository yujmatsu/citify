"""HeatmapAdvisor unit tests (Plan X)。

テスト戦略:
    - Gemini client を MagicMock + SimpleNamespace(parsed=...) で差し替え
    - LLM success / LLM failure / ethics leak / fallback mapping を網羅
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.heatmap_advisor.main import (
    FALLBACK_METRIC_BY_INTEREST,
    HeatmapAdvisor,
)
from agents.heatmap_advisor.prompts.system import PREFECTURE_NAMES_JA
from agents.heatmap_advisor.schema import HeatmapAdvice, PersonaContext
from agents.relevance.schema import ALL_INTERESTS


def _make_persona(focus: str = "住居") -> PersonaContext:
    return PersonaContext(
        user_id="test-user",
        age_group="25-29",
        interests=["住居", "子育て"],
        free_form_context="リモートワーク中心、家賃を抑えたい",
        focus_interest=focus,  # type: ignore[arg-type]
    )


def _mock_llm_advice(
    metric_column: str = "used_apartment_median_price_man_yen",
    metric_label_ja: str = "中古マンション中央値",
    direction: str = "lower_is_better",
    unit: str = "万円",
    reasoning: str = "20 代後半の住居検討では価格水準が直接効くため、中古マンション中央値を採用しました。",
    persona_summary: str = "25-29 / 住居 / リモートワーク",
) -> HeatmapAdvice:
    return HeatmapAdvice(
        metric_column=metric_column,
        metric_label_ja=metric_label_ja,
        direction=direction,  # type: ignore[arg-type]
        unit=unit,
        reasoning=reasoning,
        persona_summary=persona_summary,
        source="llm",
    )


def _make_mock_client(
    advice: HeatmapAdvice | None = None, raise_exc: Exception | None = None
) -> MagicMock:
    client = MagicMock()
    if raise_exc is not None:
        client.models.generate_content.side_effect = raise_exc
    else:
        client.models.generate_content.return_value = SimpleNamespace(parsed=advice, text="")
    return client


# ============================================================================
# 1) LLM 成功 path: HeatmapAdvice をそのまま返す (source="llm")
# ============================================================================


def test_suggest_metric_returns_llm_advice_on_success() -> None:
    """Gemini 成功時は LLM 出力をそのまま返す。"""
    advice = _mock_llm_advice()
    advisor = HeatmapAdvisor(client=_make_mock_client(advice=advice))

    result = advisor.suggest_metric(_make_persona(focus="住居"))

    assert result.metric_column == "used_apartment_median_price_man_yen"
    assert result.direction == "lower_is_better"
    assert result.source == "llm"
    assert "中古マンション" in result.reasoning


# ============================================================================
# 2) LLM 失敗 (Exception) → fallback rule-based、source="rule_based"
# ============================================================================


def test_suggest_metric_falls_back_on_llm_exception() -> None:
    """Gemini が例外を投げたら FALLBACK_METRIC_BY_INTEREST に degrade。"""
    advisor = HeatmapAdvisor(client=_make_mock_client(raise_exc=RuntimeError("Gemini API down")))

    result = advisor.suggest_metric(_make_persona(focus="子育て"))

    assert result.source == "rule_based"
    assert result.metric_column == FALLBACK_METRIC_BY_INTEREST["子育て"].column
    assert result.metric_column == "childcare_facility_count"
    assert result.direction == "higher_is_better"
    assert "(rule-based)" in result.reasoning
    assert "llm_failed" in result.reasoning


# ============================================================================
# 3) 倫理ガード: LLM が 47 都道府県名を reasoning に含めたら fallback
# ============================================================================


def test_suggest_metric_falls_back_on_prefecture_leak() -> None:
    """reasoning に都道府県名が混入したら ethics_leak で fallback。"""
    leaky_advice = _mock_llm_advice(
        reasoning="あなたには東京都が向いているので、保育施設密度を見ましょう。",
    )
    advisor = HeatmapAdvisor(client=_make_mock_client(advice=leaky_advice))

    result = advisor.suggest_metric(_make_persona(focus="子育て"))

    assert result.source == "rule_based"
    assert "(rule-based)" in result.reasoning
    assert "ethics_leak" in result.reasoning
    # fallback では「東京都」が含まれない
    assert "東京都" not in result.reasoning


# ============================================================================
# 4) Fallback mapping が全 10 interest 軸で定義されている
# ============================================================================


def test_fallback_mapping_covers_all_interests() -> None:
    """FALLBACK_METRIC_BY_INTEREST が 10 interest 軸全てを網羅。"""
    for interest in ALL_INTERESTS:
        assert interest in FALLBACK_METRIC_BY_INTEREST
        spec = FALLBACK_METRIC_BY_INTEREST[interest]
        assert spec.column
        assert spec.label_ja
        assert spec.direction in ("lower_is_better", "higher_is_better")


# ============================================================================
# 5) 47 都道府県名定数が完全に 47 件
# ============================================================================


def test_prefecture_names_complete_47() -> None:
    """PREFECTURE_NAMES_JA が 47 件全部、重複なし。"""
    assert len(PREFECTURE_NAMES_JA) == 47
    assert len(set(PREFECTURE_NAMES_JA)) == 47
    assert "北海道" in PREFECTURE_NAMES_JA
    assert "沖縄県" in PREFECTURE_NAMES_JA
    assert "東京都" in PREFECTURE_NAMES_JA


# ============================================================================
# 6) direction 値の整合性 (lower_is_better と higher_is_better だけ)
# ============================================================================


def test_all_fallback_directions_valid() -> None:
    """全 fallback spec の direction が enum に収まる。"""
    for spec in FALLBACK_METRIC_BY_INTEREST.values():
        assert spec.direction in ("lower_is_better", "higher_is_better")


# ============================================================================
# 7) population_change_2025_2050_pct は higher_is_better (Reviewer Low #7 検証)
# ============================================================================


def test_population_change_direction_is_higher_is_better() -> None:
    """人口維持/増加 (positive %) が好ましいので higher_is_better。"""
    # 「移住」軸では population_change を使う想定
    spec = FALLBACK_METRIC_BY_INTEREST["移住"]
    assert spec.column == "population_change_2025_2050_pct"
    assert spec.direction == "higher_is_better"


# ============================================================================
# 8) Gemini が parsed=None (text fallback path) でも HeatmapAdvice として正常に返す
# ============================================================================


def test_suggest_metric_handles_text_fallback_parse() -> None:
    """response.parsed が None で response.text が JSON 文字列なら text から parse。"""
    import json

    advice = _mock_llm_advice()
    text = json.dumps(advice.model_dump())
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=None, text=text)
    advisor = HeatmapAdvisor(client=client)

    result = advisor.suggest_metric(_make_persona())
    assert result.source == "llm"
    assert result.metric_column == advice.metric_column


# ============================================================================
# 9) Gemini text 空文字 → fallback (RuntimeError raised → caught → fallback)
# ============================================================================


def test_suggest_metric_falls_back_when_gemini_returns_empty() -> None:
    """response.parsed=None かつ text='' なら fallback。"""
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=None, text="")
    advisor = HeatmapAdvisor(client=client)

    result = advisor.suggest_metric(_make_persona(focus="医療"))

    assert result.source == "rule_based"
    assert result.metric_column == "medical_facility_count"


# ============================================================================
# 10) 不正な focus_interest (Literal 外) は Pydantic で reject
# ============================================================================


def test_persona_context_rejects_invalid_focus_interest() -> None:
    """PersonaContext は focus_interest を Interest Literal で制約。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PersonaContext(focus_interest="存在しない軸")  # type: ignore[arg-type]
