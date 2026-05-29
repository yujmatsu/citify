"""Timeline Agent の入出力 Pydantic スキーマ (Plan N)。"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from agents.relevance.schema import Interest


class CandidateSpeech(BaseModel):
    """BQ から取得した候補 speech (TimelineAgent の input、LLM context にも一部送る)。

    注意 (Reviewer Critical #1): speaker (実名) は **意図的に含めない**。
    BQ SELECT から除外し、ナラティブ生成時に人名 leak を構造的に防止する。
    """

    speech_id: str = Field(description="合成 ID 'tenant:council:schedule:order'")
    title: str = Field(default="")
    summary_first_line: str = Field(default="", max_length=120)
    meeting_date: date | None = None
    municipality_code: str
    municipality_name: str = Field(default="")
    speaker_position: str | None = None
    matched_interests: list[Interest] = Field(default_factory=list)
    relevance_score: int = Field(default=0)


class TimelineEvent(BaseModel):
    """1 マイルストーン (LLM が抽出する重要イベント)。"""

    event_date: date = Field(description="event 発生日 (field 名 `date` は Pydantic 2.13 衝突回避)")
    municipality_code: str = Field(description="5 桁自治体コード")
    municipality_name: str = Field(default="", max_length=20)
    headline: str = Field(max_length=40, description="キャッチー見出し")
    detail: str = Field(max_length=80, description="具体的な議論内容")
    source_speech_id: str = Field(description="元 speech_id (クリックで /feed/{id} 遷移)")
    importance: int = Field(default=50, ge=0, le=100, description="UI 強調用")


class TimelineNarrative(BaseModel):
    """TimelineAgent の最終出力 (Gemini response_schema として強制)。"""

    theme_label: str = Field(max_length=40, description="LLM が整形した theme 名")
    period_start: date
    period_end: date
    overall_summary: str = Field(
        default="",
        max_length=240,
        description="全体ナラティブ (200-240 字、議論の流れ)",
    )
    events: list[TimelineEvent] = Field(
        default_factory=list,
        max_length=10,
        description="重要イベント 5-10 件 (LLM 失敗時は raw 上位 5 で 0-5 件)",
    )
    source: Literal["llm", "rule_based"] = Field(
        default="llm",
        description="LLM 生成 / rule-based fallback の区別 (UI 表示)",
    )


class TimelineRequest(BaseModel):
    """API endpoint からの入力 (zod schema と一致)。"""

    user_id: str = "anon"
    theme_interest: Interest = Field(description="フォーカスする interest 軸")
    municipality_code: str | None = Field(
        default=None,
        description="None=全国、5 桁コード指定で 1 自治体に絞る",
    )
    days: int = Field(default=90, ge=7, le=365, description="期間 (日)")
