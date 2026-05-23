"""影響度 Agent の入出力 Pydantic スキーマ。

10 関心軸は FEATURES.md A-1 に準拠 (住居・雇用・結婚・子育て・税・起業・防災・医療・教育・移住)。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AgeGroup = Literal["18-24", "25-29", "30-39", "40-49", "50+"]

# 10 関心軸 (FEATURES.md A-1 準拠)
Interest = Literal[
    "住居",
    "雇用",
    "結婚",
    "子育て",
    "税",
    "起業",
    "防災",
    "医療",
    "教育",
    "移住",
]
ALL_INTERESTS: tuple[Interest, ...] = (
    "住居",
    "雇用",
    "結婚",
    "子育て",
    "税",
    "起業",
    "防災",
    "医療",
    "教育",
    "移住",
)


class UserPersona(BaseModel):
    """ユーザーペルソナ (オンボーディングで入力された値の最小セット)。"""

    user_id: str = Field(default="anonymous", description="ユーザー ID (匿名でも可、log 用)")
    age_group: AgeGroup
    interests: list[Interest] = Field(default_factory=list, description="関心軸 (最大 10)")
    municipality_codes: list[str] = Field(
        default_factory=list,
        description="登録自治体コード (5 桁、'00000' は国会レベル)",
    )


class RelevanceInput(BaseModel):
    """影響度 Agent への入力。speech メタ + ペルソナ。

    `translated_summary` が渡された場合 (A-5 出力連携) はそちらを優先評価。
    """

    speech_id: str
    content_text: str = Field(description="speech 本文 (translated_summary 非存在時にこちらを評価)")
    translated_summary: list[str] | None = Field(
        default=None, description="A-5 翻訳後の 3 行サマリ"
    )
    title: str | None = Field(default=None, description="A-5 翻訳後のタイトル")
    speaker_position: str | None = Field(default=None, description="役職 (固有名詞でない)")
    meeting_context: str = Field(default="", description="会議文脈")
    municipality_code: str = Field(
        default="00000", description="speech 元自治体コード ('00000' = 国会)"
    )
    user: UserPersona


class RelevanceOutput(BaseModel):
    """影響度 Agent の構造化出力 (Gemini response_schema 用)。

    各 dimension は 0-25、合計が relevance_score (0-100)。
    """

    relevance_score: int = Field(ge=0, le=100, description="4 軸合計 (0-100)")
    score_topic: int = Field(
        ge=0, le=25, description="トピック関連性 (ペルソナ関心軸 × 発言テーマ)"
    )
    score_age: int = Field(ge=0, le=25, description="年代適合性 (ペルソナ年代に直接影響するか)")
    score_geographic: int = Field(
        ge=0, le=25, description="地理関連性 (登録自治体と speech 元自治体の合致)"
    )
    score_urgency: int = Field(
        ge=0, le=25, description="緊急性 (具体的予算/法案で高、抽象議論で低)"
    )
    matched_interests: list[Interest] = Field(
        default_factory=list,
        description="ペルソナ関心軸のうち、この speech に合致するもの",
    )
    reasoning: str = Field(
        max_length=200, description="関連性スコアの簡潔な理由 (事実ベース、200 字以内)"
    )
    contains_political_judgment: bool = Field(
        description="reasoning に賛否表明/政党推奨が含まれているか (倫理チェック)"
    )

    @classmethod
    def below_threshold(cls, reason: str = "") -> RelevanceOutput:
        """スコア計算失敗時の安全な default (フィード非表示)。"""
        return cls(
            relevance_score=0,
            score_topic=0,
            score_age=0,
            score_geographic=0,
            score_urgency=0,
            matched_interests=[],
            reasoning=reason or "評価できなかったため非表示",
            contains_political_judgment=False,
        )


class PersonaRelevanceOutput(BaseModel):
    """1 ペルソナ分の relevance 評価結果 (Phase Y: multi-persona fan-out 用)。

    RelevanceOutput と同じ 4 軸 + user_id を持つ (Gemini 出力の list 要素)。
    """

    user_id: str = Field(description="評価対象ペルソナの user_id (入力の user_id をそのまま返す)")
    relevance_score: int = Field(ge=0, le=100)
    score_topic: int = Field(ge=0, le=25)
    score_age: int = Field(ge=0, le=25)
    score_geographic: int = Field(ge=0, le=25)
    score_urgency: int = Field(ge=0, le=25)
    matched_interests: list[Interest] = Field(default_factory=list)
    reasoning: str = Field(max_length=200)
    contains_political_judgment: bool

    def to_relevance_output(self) -> RelevanceOutput:
        """既存の RelevanceOutput に変換 (user_id を捨てる)。"""
        return RelevanceOutput(
            relevance_score=self.relevance_score,
            score_topic=self.score_topic,
            score_age=self.score_age,
            score_geographic=self.score_geographic,
            score_urgency=self.score_urgency,
            matched_interests=list(self.matched_interests),
            reasoning=self.reasoning,
            contains_political_judgment=self.contains_political_judgment,
        )


class MultiPersonaRelevanceOutput(BaseModel):
    """Gemini 1 リクエストで N ペルソナを採点した結果 (Phase Y)。"""

    results: list[PersonaRelevanceOutput] = Field(
        description="各ペルソナの評価結果 (入力順に並ぶ)",
    )


class ScoredSpeech(BaseModel):
    """relevance worker → distributor (A-7) への publish payload。

    1 つの speech × 1 人のユーザーペルソナに対する relevance score を持つ。
    将来 user DB ができたら 1 speech → N users で fan-out する想定。
    """

    speech_id: str = Field(description="合成 ID 'tenant:council:schedule:order'")
    user_id: str = Field(description="ペルソナ ID (匿名なら 'anonymous')")
    municipality_code: str
    title: str = Field(description="A-5 翻訳タイトル (downstream 表示用)")
    summary: list[str] = Field(description="A-5 翻訳 3 行サマリ")
    detail_url: str = Field(description="原典 URL (引用必須)")
    meeting_date: str | None = Field(default=None, description="ISO 日付文字列 or None")
    score: RelevanceOutput = Field(description="relevance スコア + 内訳")

    # distributor (A-7) のランキング・多様性算定に必要なメタ
    speaker_position: str | None = Field(default=None, description="役職 (diversity penalty 用)")
    name_of_meeting: str | None = Field(default=None, description="会議名 (display 用)")
    tone: str | None = Field(default=None, description="A-5 翻訳トーン (casual/neutral/formal)")
