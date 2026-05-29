"""Forecast Agent (Plan Z): 議題件数の月別時系列を線形回帰 + LLM ナラティブで物語化。

2 段階構成 (Plan X / Plan N と同パターン):
    - ForecastEngine (純計算、LLM 不要): 月別件数 → 移動平均 + 線形回帰 + 3 か月予測 + trend 分類 + confidence
    - ForecastNarrator (独立 Agent、Gemini Flash + Chain-of-Thought): trend を介入的に説明

倫理ガード:
    - Plan N の POLITICAL_PERSON_PATTERNS 流用 (政治家名 / 政党名 leak)
    - Plan X の PREFECTURE_NAMES_JA 流用 (都道府県名 leak、地域推奨回避)
    - 主要市区町村名 blocklist (apps/api/_MUNI_NAME_MAP から抽出、Reviewer High #1)
"""

from .engine import (
    ForecastEngine,
    classify_trend,
    compute_confidence,
    linear_regression,
    moving_average,
)
from .main import ForecastNarrator
from .schema import (
    ForecastNarrative,
    ForecastPoint,
    ForecastResponse,
    ForecastSeries,
    MonthCount,
    PersonaContext,
    TrendClassification,
)

__all__ = [
    "ForecastEngine",
    "ForecastNarrative",
    "ForecastNarrator",
    "ForecastPoint",
    "ForecastResponse",
    "ForecastSeries",
    "MonthCount",
    "PersonaContext",
    "TrendClassification",
    "classify_trend",
    "compute_confidence",
    "linear_regression",
    "moving_average",
]
