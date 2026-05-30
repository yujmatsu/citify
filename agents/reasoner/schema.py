"""MetaReasoningAgent の入出力 Pydantic スキーマ (Plan PP)。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# 既存 Citify Agent 7 種を Literal で限定
AgentName = Literal[
    "concierge",
    "translator",
    "critic",
    "heatmap_advisor",
    "timeline",
    "forecast",
    "scraper_doctor",
]

Confidence = Literal["high", "medium", "low"]


class ReasoningInspectInput(BaseModel):
    """MetaReasoningAgent への入力。

    Reviewer High #1: 3 フィールド全てで _detect_any_leak を実行 (連鎖防止)。
    """

    agent_name: AgentName = Field(description="対象 Agent (7 種)")
    raw_reasoning: str = Field(
        max_length=500,
        description="対象 Agent が出した reasoning",
    )
    agent_output_summary: str = Field(
        max_length=300,
        description="対象 Agent 最終出力の要約 (titles + summary 等)",
    )
    persona_context: str | None = Field(
        default=None,
        max_length=200,
        description="ユーザーペルソナ (年代/関心軸、Concierge/Heatmap/Forecast/Timeline 用)",
    )


class ReasoningExplanation(BaseModel):
    """MetaReasoningAgent 出力 (Gemini response_schema 強制)。

    既存 Agent の reasoning が「自己説明ログ」なら、本 schema は「第三者観測者の再構成」。
    """

    plain_summary: str = Field(
        max_length=300,
        description="raw_reasoning を平易化 + 要点抽出 (250-300 字)",
    )
    influencing_factors: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="判断に最も影響した input 要素 3-5 個 (各 60 字以内)",
    )
    counterfactuals: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="「もし X が違ったらどうなるか」2-3 個 (各 80 字以内、行動推奨禁止)",
    )
    caveats: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="判断の限界 / 不確実性 1-3 個 (各 60 字以内)",
    )
    confidence: Confidence = Field(default="medium")
    source: Literal["llm", "rule_based"] = Field(default="llm")
