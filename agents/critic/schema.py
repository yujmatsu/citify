"""Critic Agent の入出力 Pydantic スキーマ (Plan D)。

設計判断:
    - CriticScores は 4 軸独立スコア (0-100)
    - CritiqueResult は scores + overall_score (4 軸平均) + feedback + passed フラグ
    - overall_score の算出 + ethics<60 強制 revise トリガーは CriticAgent 側で実施
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CriticScores(BaseModel):
    """4 軸の評価スコア (各 0-100)。Gemini response_schema で構造化出力。"""

    faithfulness: int = Field(
        ge=0,
        le=100,
        description="原典忠実度: 100=正確 / 0=事実誤認・捏造",
    )
    simplicity: int = Field(
        ge=0,
        le=100,
        description="平易さ: 100=18-24歳が辞書なしで理解可能 / 0=専門用語残存",
    )
    tone: int = Field(
        ge=0,
        le=100,
        description="トーン適合: 100=age_group の TONE_GUIDANCE に準拠 / 0=不適合",
    )
    ethics: int = Field(
        ge=0,
        le=100,
        description="倫理: 100=政治家名/政党/賛否なし / 0=固有名詞・賛否表明あり",
    )


class CritiqueResult(BaseModel):
    """Critic の最終評価結果 (CriticAgent.critique の戻り値)。"""

    scores: CriticScores = Field(description="4 軸スコア")
    overall_score: int = Field(
        ge=0,
        le=100,
        description="4 軸単純平均 (round)",
    )
    feedback: str = Field(
        default="",
        max_length=500,
        description="改善 feedback (revise 時 prompt に注入)",
    )
    passed: bool = Field(
        description="threshold 以上 かつ ethics>=60 なら True (revise 不要)",
    )

    @classmethod
    def empty_skip(cls, reason: str) -> CritiqueResult:
        """empty draft 等で critique skip 時の placeholder。"""
        return cls(
            scores=CriticScores(faithfulness=0, simplicity=0, tone=0, ethics=0),
            overall_score=0,
            feedback=f"critique_skipped: {reason}",
            passed=False,
        )
