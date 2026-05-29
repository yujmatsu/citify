"""HeatmapAdvisor Agent (Plan X): ペルソナを踏まえて全国ヒートマップの色付け指標を選定。

入力: ペルソナ (年代/関心軸/自由記述)
出力: HeatmapAdvice (metric_column / direction / reasoning / persona_summary)

設計:
    - Gemini Flash + Chain-of-Thought (内部思考 → 候補 3 つ → 最適 1 つ)
    - LLM 失敗時は FALLBACK_METRIC_BY_INTEREST 固定 mapping で graceful degrade
    - 倫理ガード: reasoning に 47 都道府県名を含めない (個別地域推奨禁止)
    - Concierge tool として再利用しない、完全独立 Agent (Plan X miniplan Out of Scope)
"""

from .main import FALLBACK_METRIC_BY_INTEREST, HeatmapAdvisor
from .schema import HeatmapAdvice, HeatmapMetricSpec, PersonaContext

__all__ = [
    "FALLBACK_METRIC_BY_INTEREST",
    "HeatmapAdvice",
    "HeatmapAdvisor",
    "HeatmapMetricSpec",
    "PersonaContext",
]
