"""翻訳 Agent の入出力 Pydantic スキーマ。

Gemini の `response_schema` で構造化出力を強制するため、出力 schema は
Pydantic で厳密に定義 (max_length 制約まで含む)。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ペルソナ年代区分 (FEATURES.md A-1 準拠)
AgeGroup = Literal["18-24", "25-29", "30-34", "35+"]

# トーン分類 (年代に応じて出し分け)
Tone = Literal["casual", "neutral", "formal"]


class TranslateInput(BaseModel):
    """翻訳 agent への入力。BQ kokkai_speeches 行 + ペルソナ情報相当。"""

    speech_id: str = Field(description="speech の一意 ID (BQ id カラム)")
    content_text: str = Field(description="speech 本文")
    speaker: str | None = Field(
        default=None, description="発言者名 (Agent 内部参照のみ、出力には使わない)"
    )
    speaker_position: str | None = Field(
        default=None, description="発言者役職 (出力時はこちらを優先、固有名詞回避)"
    )
    speaker_group: str | None = Field(
        default=None, description="所属政党 (Agent 内部参照のみ、出力禁止)"
    )
    meeting_context: str = Field(
        default="", description="会議文脈 (例: '衆議院 本会議 第16号 2026-05-18')"
    )
    age_group: AgeGroup = Field(default="25-29", description="ペルソナ年代区分")


class TranslatorOutput(BaseModel):
    """翻訳 agent からの構造化出力 (Gemini response_schema として使用)。"""

    title: str = Field(
        max_length=40,
        description="平易化タイトル (40 字以内、固有名詞回避、ジャーゴンなし)",
    )
    summary: list[str] = Field(
        min_length=3,
        max_length=3,
        description="3 行サマリ。各行 60 字以内、若者にも理解できる平易な日本語",
    )
    tone: Tone = Field(description="採用したトーン (年代に応じて casual/neutral/formal)")
    contains_politician_names: bool = Field(
        description="出力中に政治家の固有名詞が含まれているか (倫理チェック、True なら再生成必要)"
    )
    contains_political_judgment: bool = Field(
        description="出力中に賛否表明や政党推奨が含まれているか (倫理チェック、True なら再生成必要)"
    )
    notes: str = Field(
        default="",
        max_length=200,
        description="補足や補足説明 (専門用語の補足等)。空でも可",
    )

    @classmethod
    def empty(cls, reason: str) -> TranslatorOutput:
        """空の翻訳結果 (入力不正等の場合)。"""
        return cls(
            title="(翻訳できませんでした)",
            summary=[reason, "再度お試しください。", ""],
            tone="neutral",
            contains_politician_names=False,
            contains_political_judgment=False,
            notes=f"empty_reason: {reason}",
        )
