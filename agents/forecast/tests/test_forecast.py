"""ForecastEngine + ForecastNarrator unit tests (Plan Z)。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.forecast.engine import (
    SLOPE_DECREASING,
    SLOPE_INCREASING,
    ForecastEngine,
    classify_trend,
    compute_confidence,
    linear_regression,
)
from agents.forecast.main import (
    MAJOR_MUNI_NAMES,
    ForecastNarrator,
    _detect_any_leak,
    _detect_geographic_leak,
)
from agents.forecast.schema import (
    ForecastNarrative,
    MonthCount,
    PersonaContext,
)

# ============================================================================
# Helpers
# ============================================================================


def _months(values: list[float], start_year: int = 2025, start_month: int = 1) -> list[MonthCount]:
    """連続月の MonthCount list を組み立て。"""
    out: list[MonthCount] = []
    y, m = start_year, start_month
    for v in values:
        out.append(MonthCount(year_month=f"{y:04d}-{m:02d}", speech_count=float(v)))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _persona() -> PersonaContext:
    return PersonaContext(
        user_id="test-user",
        age_group="25-29",
        interests=["住居"],
        focus_interest="住居",
    )


# ============================================================================
# 1) ForecastEngine: 増加トレンド ([1,2,3,4,5,6]) → slope > 0 + trend="increasing"
# ============================================================================


def test_engine_detects_increasing_trend() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([1, 2, 3, 4, 5, 6]))
    assert series.slope > 0
    assert series.trend_classification == "increasing"
    assert series.months_in_history == 6
    assert len(series.forecast) == 3
    # 各予測値 0+
    for fp in series.forecast:
        assert fp.speech_count >= 0
        assert fp.is_forecast is True


# ============================================================================
# 2) ForecastEngine: 減少トレンド ([10,8,6,4,2,1]) → slope < 0 + trend="decreasing"
# ============================================================================


def test_engine_detects_decreasing_trend() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([10, 8, 6, 4, 2, 1]))
    assert series.slope < 0
    assert series.trend_classification in ("decreasing", "crash")


# ============================================================================
# 3) ForecastEngine: 横ばい ([5,5,5,5,5,5]) → trend="flat"
# ============================================================================


def test_engine_detects_flat_trend() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([5, 5, 5, 5, 5, 5]))
    assert abs(series.slope) < 0.5
    assert series.trend_classification == "flat"


# ============================================================================
# 4) ForecastEngine: データ不足 (< 6) → confidence="low" + forecast=[]
# ============================================================================


def test_engine_low_confidence_when_history_short() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([1, 2, 3]))
    assert series.confidence == "low"
    assert series.forecast == []  # 3 ヶ月だけだと forecast 不発


# ============================================================================
# 5) ForecastEngine: 分散大 (CV > 0.5) → confidence="low" 強制 (Reviewer High #2)
# ============================================================================


def test_engine_low_confidence_when_cv_large() -> None:
    """[1, 50, 2, 60, 3, 55] のような分散大 → confidence="low"。"""
    engine = ForecastEngine()
    series = engine.forecast_series(_months([1, 50, 2, 60, 3, 55]))
    assert series.confidence == "low"


# ============================================================================
# 6) ForecastEngine: clip 0+ (slope 大 + last_smoothed 小でも負値にならない)
# ============================================================================


def test_engine_clips_forecast_to_zero_and_upper() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([10, 5, 3, 2, 1, 0]))  # 強い減少
    for fp in series.forecast:
        assert fp.speech_count >= 0


# ============================================================================
# 7) linear_regression: 完全直線 → slope=1.0, se_slope=0.0
# ============================================================================


def test_linear_regression_perfect_line() -> None:
    reg = linear_regression([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    assert abs(reg.slope - 1.0) < 0.001
    assert reg.se_slope == 0.0  # 残差ゼロ


# ============================================================================
# 8) classify_trend: 閾値境界
# ============================================================================


def test_classify_trend_boundaries() -> None:
    assert classify_trend(2.0) == "surge"
    assert classify_trend(1.0) == "increasing"
    assert classify_trend(0.0) == "flat"
    assert classify_trend(-1.0) == "decreasing"
    assert classify_trend(-2.0) == "crash"
    # 境界
    assert classify_trend(SLOPE_INCREASING) == "increasing"
    assert classify_trend(SLOPE_DECREASING) == "decreasing"


# ============================================================================
# 9) compute_confidence: history < 6 → low
# ============================================================================


def test_compute_confidence_short_history_is_low() -> None:
    assert (
        compute_confidence(history_months=5, values=[1, 2, 3, 4, 5], slope=0.5, se_slope=0.1)
        == "low"
    )


# ============================================================================
# 10) compute_confidence: 高 t 値 + 低 CV → high
# ============================================================================


def test_compute_confidence_high_when_t_large_and_cv_low() -> None:
    # CV = stddev/mean = sqrt(2.91)/3.5 ≈ 0.49 (CV_THRESHOLD_LOW=0.5 未満) なので CV では low にならない
    # slope=1.0 / se=0.1 → t=10.0 > 2.0 で high
    result = compute_confidence(
        history_months=6,
        values=[2, 3, 3, 4, 4, 5],
        slope=1.0,
        se_slope=0.1,
    )
    assert result == "high"


# ============================================================================
# 11) ForecastNarrator: LLM 成功 path → source="llm"
# ============================================================================


def test_narrator_returns_llm_narrative_on_success() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([1, 2, 3, 4, 5, 6]))

    narrative_mock = ForecastNarrative(
        headline="住居議題は緩やかに増加",
        reasoning="議論件数が緩やかに増加しており、住居政策の議論が拡大しています。",
        source="llm",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=narrative_mock, text="")

    narrator = ForecastNarrator(client=client)
    result = narrator.narrate(series, _persona(), municipality_label="全国")
    assert result.source == "llm"
    assert result.headline.startswith("住居")


# ============================================================================
# 12) ForecastNarrator: LLM 失敗 → rule_based fallback
# ============================================================================


def test_narrator_falls_back_on_llm_exception() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([1, 2, 3, 4, 5, 6]))

    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("Gemini API down")
    narrator = ForecastNarrator(client=client)

    result = narrator.narrate(series, _persona())
    assert result.source == "rule_based"
    assert "(rule-based)" in result.reasoning


# ============================================================================
# 13) ForecastNarrator: 47 都道府県名 leak → fallback (Reviewer High #1)
# ============================================================================


def test_narrator_falls_back_on_prefecture_leak() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([1, 2, 3, 4, 5, 6]))

    leaky = ForecastNarrative(
        headline="東京都の住居議題が活発",
        reasoning="住居議題が増加傾向です。",
        source="llm",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky, text="")
    narrator = ForecastNarrator(client=client)

    result = narrator.narrate(series, _persona())
    assert result.source == "rule_based"
    # leaked 県名がユーザー向けに残らない
    assert "東京都" not in result.headline
    assert "東京都" not in result.reasoning


# ============================================================================
# 14) ForecastNarrator: 主要市区町村名 leak → fallback (Reviewer High #1)
# ============================================================================


def test_narrator_falls_back_on_municipality_leak() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([1, 2, 3, 4, 5, 6]))

    leaky = ForecastNarrative(
        headline="新宿区への移住推奨",
        reasoning="議題件数が増加。",
        source="llm",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky, text="")
    narrator = ForecastNarrator(client=client)

    result = narrator.narrate(series, _persona())
    assert result.source == "rule_based"
    assert "新宿区" not in result.headline


# ============================================================================
# 15) ForecastNarrator: 政治家名 leak → fallback (Plan N 流用)
# ============================================================================


def test_narrator_falls_back_on_political_leak() -> None:
    engine = ForecastEngine()
    series = engine.forecast_series(_months([1, 2, 3, 4, 5, 6]))

    leaky = ForecastNarrative(
        headline="石破総理の政策で議題増",
        reasoning="増加傾向。",
        source="llm",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky, text="")
    narrator = ForecastNarrator(client=client)

    result = narrator.narrate(series, _persona())
    assert result.source == "rule_based"
    assert "石破総理" not in result.headline


# ============================================================================
# 16) _detect_geographic_leak: 47 県 + 主要市区
# ============================================================================


def test_detect_geographic_leak_finds_prefecture() -> None:
    assert _detect_geographic_leak("東京都の住居市場") == "東京都"
    assert _detect_geographic_leak("北海道の議論") == "北海道"


def test_detect_geographic_leak_finds_major_muni() -> None:
    assert _detect_geographic_leak("新宿区が活発") == "新宿区"
    assert _detect_geographic_leak("横浜市が増加") == "横浜市"


def test_detect_geographic_leak_passes_clean_text() -> None:
    assert _detect_geographic_leak("住居議題が増加傾向") is None
    assert _detect_geographic_leak("議論ボリュームの推移") is None


def test_major_muni_names_includes_specific_examples() -> None:
    assert "新宿区" in MAJOR_MUNI_NAMES
    assert "横浜市" in MAJOR_MUNI_NAMES
    assert "札幌市" in MAJOR_MUNI_NAMES


def test_detect_any_leak_combines_both_layers() -> None:
    assert _detect_any_leak("自民党が支援") == "自民党"  # Plan N 政党
    assert _detect_any_leak("東京都の議題") == "東京都"  # Plan X 県名
    assert _detect_any_leak("新宿区で議論") == "新宿区"  # Plan Z 市区
    assert _detect_any_leak("議題件数が増加") is None
