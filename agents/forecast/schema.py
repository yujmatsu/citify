"""Forecast Agent の入出力 Pydantic スキーマ (Plan Z)。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.relevance.schema import AgeGroup, Interest

TrendClassification = Literal["surge", "increasing", "flat", "decreasing", "crash"]
Confidence = Literal["high", "medium", "low"]


class MonthCount(BaseModel):
    """月別件数 (historical + forecast 共通)。"""

    year_month: str = Field(description="ISO 形式の年月 e.g. '2026-03'")
    speech_count: float = Field(ge=0.0, description="議題件数 (float、forecast の小数も許容)")


class ForecastPoint(BaseModel):
    """予測値 1 点 (is_forecast=True で historical と区別)。"""

    year_month: str
    speech_count: float = Field(ge=0.0)
    is_forecast: bool = True


class ForecastSeries(BaseModel):
    """Engine 出力 (純計算、LLM なし)。"""

    historical: list[MonthCount] = Field(description="過去 6-12 ヶ月の月別件数")
    forecast: list[ForecastPoint] = Field(description="未来 3 ヶ月の予測 (clip 0+)")
    trend_classification: TrendClassification = Field(description="5 分類")
    slope: float = Field(description="月あたり件数増減 (線形回帰)")
    slope_std_error: float = Field(
        default=0.0, ge=0.0, description="slope 標準誤差 (Reviewer High #2)"
    )
    confidence: Confidence = Field(description="信頼度 3 段階")
    months_in_history: int = Field(ge=0, description="historical の月数")


class ForecastNarrative(BaseModel):
    """ForecastNarrator 出力 (LLM 構造化、Reviewer Medium #5: slope/trend を含めない)。"""

    headline: str = Field(max_length=40, description="キャッチー見出し")
    reasoning: str = Field(
        max_length=240,
        description="200 字介入的説明、Chain-of-Thought ベース",
    )
    source: Literal["llm", "rule_based"] = Field(default="llm")


class PersonaContext(BaseModel):
    """Narrator への persona (Plan X HeatmapAdvisor と並列、独立定義)。"""

    user_id: str = "anon"
    age_group: AgeGroup = "25-29"
    interests: list[Interest] = Field(default_factory=list)
    focus_interest: Interest = Field(description="フォーカスする interest 軸")


class ForecastResponse(BaseModel):
    """API endpoint 出力 (Engine + Narrator 結合、frontend がそのまま zod parse)。"""

    series: ForecastSeries
    narrative: ForecastNarrative
