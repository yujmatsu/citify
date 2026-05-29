"""HeatmapAdvisor の入出力 Pydantic スキーマ (Plan X)。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agents.relevance.schema import AgeGroup, Interest

# 色付けの方向性 (低いほど良い / 高いほど良い)
Direction = Literal["lower_is_better", "higher_is_better"]


class PersonaContext(BaseModel):
    """HeatmapAdvisor への入力 persona。Concierge と同形式 (再利用ではなく独立定義)。"""

    user_id: str = Field(default="anon")
    age_group: AgeGroup = Field(default="25-29")
    interests: list[Interest] = Field(default_factory=list)
    free_form_context: str = Field(default="", max_length=500)
    # フォーカスする関心軸 (UI セレクタで明示指定、interests に含まれていればそれを優先)
    focus_interest: Interest = Field(description="今回 heatmap で見たい軸")


class HeatmapMetricSpec(BaseModel):
    """municipality_stats の 1 列を「指標」として識別する仕様。"""

    column: str = Field(
        description="municipality_stats テーブルの列名 (e.g. used_apartment_median_price_man_yen)",
    )
    label_ja: str = Field(
        max_length=40,
        description="日本語ラベル (UI 表示用)",
    )
    direction: Direction = Field(description="色付け方向性")
    unit: str = Field(default="", max_length=20, description="単位 (例: 万円, 件, %)")


class HeatmapAdvice(BaseModel):
    """HeatmapAdvisor の出力 (LLM response_schema として強制)。"""

    metric_column: str = Field(description="選定した指標の列名")
    metric_label_ja: str = Field(max_length=40, description="UI 表示用日本語ラベル")
    direction: Direction = Field(description="色付け方向性")
    unit: str = Field(default="", max_length=20, description="単位")
    reasoning: str = Field(
        max_length=300,
        description="選定理由 (200-300 字)。47 都道府県名禁止、地域推奨禁止 (ethics guard)",
    )
    persona_summary: str = Field(
        max_length=120,
        description="ペルソナ要約 (UI banner 用、100-120 字)",
    )
    source: Literal["llm", "rule_based"] = Field(
        default="llm",
        description="LLM 選定か fallback ルールか (UI 表示で区別可能)",
    )
