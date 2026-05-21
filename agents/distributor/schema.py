"""配信 Agent の入出力 Pydantic スキーマ。

FeedCandidate = A-5 翻訳 + A-6 スコア + speech メタの統合
FeedItem      = FeedCandidate + ランキング後メタ (final_rank, adjusted_score, display_reason)
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class FeedCandidate(BaseModel):
    """A-5 + A-6 の合成結果。1 つの speech に対する評価済データ。"""

    speech_id: str

    # A-5 翻訳結果 (省略可、その場合 raw speech から代替表示)
    title: str | None = Field(default=None, description="A-5 翻訳タイトル (40 字以内)")
    summary: list[str] | None = Field(default=None, description="A-5 翻訳 3 行サマリ")
    tone: str | None = Field(default=None, description="casual / neutral / formal")

    # A-6 関連性スコア
    relevance_score: int = Field(ge=0, le=100, description="A-6 4 軸合計スコア")
    score_topic: int = Field(default=0, ge=0, le=25)
    score_age: int = Field(default=0, ge=0, le=25)
    score_geographic: int = Field(default=0, ge=0, le=25)
    score_urgency: int = Field(default=0, ge=0, le=25)
    matched_interests: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="", max_length=200)

    # speech メタ
    speaker_position: str | None = Field(default=None, description="役職 (固有名詞でない)")
    municipality_code: str = Field(default="00000")
    meeting_date: date | None = Field(default=None)
    meeting_url: str | None = Field(default=None)
    name_of_meeting: str | None = Field(default=None)


class FeedItem(BaseModel):
    """ランキング後の feed 1 項目。FeedCandidate + A-7 ランキングメタ。"""

    # FeedCandidate からそのまま継承するフィールド
    speech_id: str
    title: str | None
    summary: list[str] | None
    tone: str | None
    relevance_score: int
    matched_interests: list[str]
    reasoning: str
    speaker_position: str | None
    municipality_code: str
    meeting_date: date | None
    meeting_url: str | None
    name_of_meeting: str | None

    # A-7 でのランキング結果
    final_rank: int = Field(ge=1, description="フィード内の最終順位 (1-based)")
    adjusted_score: float = Field(description="多様性/新鮮さ調整後のスコア")
    display_reason: str = Field(max_length=120, description="ユーザーに表示する理由")
    diversity_penalty: float = Field(
        default=0.0, description="この item に課された多様性ペナルティ (debug)"
    )
    freshness_boost: int = Field(default=0, description="新鮮さ補正 (debug、+5 / 0 / -5)")
