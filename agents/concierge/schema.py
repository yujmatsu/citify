"""Concierge Agent の入出力 + tool パラメータ Pydantic スキーマ (Plan E)。

ADK Agent / FunctionTool 経由で LLM が tool 引数を組み立てるため、
schema は厳密に定義 (LLM が schema を読んで適切な引数を作る)。

設計判断:
    - Citify の interest 軸 (住居/子育て/...) は agents.relevance.schema.Interest を再利用
    - municipality_code は 5 桁文字列 (BQ scored_speeches schema と整合)
    - constraint は dict[str, float] で柔軟性を確保 (将来 numeric/categorical 混在)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.relevance.schema import AgeGroup, Interest

# ============================================================================
# Tool 1: search_municipalities
# ============================================================================


class ConstraintFilter(BaseModel):
    """search_municipalities の絞り込み制約 (全フィールド optional)。"""

    max_avg_rent_man: float | None = Field(
        default=None,
        ge=0,
        description="中古マンション平均価格の上限 (万円)。これより高い自治体は除外",
    )
    min_childcare_count: int | None = Field(
        default=None,
        ge=0,
        description="保育所/幼稚園数の下限。これより少ない自治体は除外",
    )
    min_medical_count: int | None = Field(
        default=None,
        ge=0,
        description="医療機関数の下限。これより少ない自治体は除外",
    )
    min_population: int | None = Field(
        default=None,
        ge=0,
        description="総人口の下限 (例: 5万人以上の市)",
    )
    max_population: int | None = Field(
        default=None,
        ge=0,
        description="総人口の上限 (例: 過疎の村は除外)",
    )
    require_positive_population_growth: bool = Field(
        default=False,
        description="True なら 2025→2050 の人口推計が正方向 (流入予測) の自治体のみ",
    )
    prefecture_codes: list[str] = Field(
        default_factory=list,
        description="絞り込み都道府県コード (2 桁、例: ['13', '14'])。空ならフィルタなし",
    )


class MunicipalityCandidate(BaseModel):
    """search_municipalities の出力 (1 候補)。"""

    municipality_code: str = Field(description="5 桁自治体コード")
    name: str = Field(description="自治体名 (例: '世田谷区')")
    prefecture: str = Field(description="都道府県名 (例: '東京都')")
    match_score: float = Field(
        ge=0.0,
        le=100.0,
        description=(
            "0-100 で計算された total スコア。"
            "計算式: interests hit × 25 (max 50) + constraint pass × 25 + "
            "population_growth_positive_bonus × 10 + base 15 (clamp 0-100)"
        ),
    )
    # 主要統計サマリ (LLM が trade-off を語るための素材)
    population_total: int | None = None
    youth_share_pct: float | None = None
    used_apartment_median_price_man_yen: float | None = None
    childcare_facility_count: int | None = None
    medical_facility_count: int | None = None
    population_change_pct: float | None = None  # e-Stat 直近国勢調査ベース (TASK-POPFIX)
    matched_interests: list[Interest] = Field(
        default_factory=list, description="どの interest 軸に hit したか"
    )
    summary_text: str = Field(
        default="",
        description=("LLM に渡す『この街の一言サマリ』。tool 内で生成、後段の reasoning 材料"),
    )


class SearchMunicipalitiesArgs(BaseModel):
    """LLM が search_municipalities を呼ぶときの引数 (ADK Tool input schema)。"""

    age_group: AgeGroup = Field(description="ユーザーの年代")
    interests: list[Interest] = Field(
        min_length=1,
        max_length=5,
        description="ユーザーの関心軸 (1-5 個、agents.relevance.schema.Interest)",
    )
    constraints: ConstraintFilter | None = Field(
        default=None, description="絞り込み制約 (optional、None なら全自治体対象)"
    )
    limit: int = Field(default=5, ge=1, le=20, description="返却件数 (default 5)")


# ============================================================================
# Tool 2: compare_municipalities
# ============================================================================


class ComparisonRow(BaseModel):
    """compare_municipalities の 1 自治体行。"""

    municipality_code: str
    name: str
    prefecture: str
    top_speeches: list[dict] = Field(
        default_factory=list,
        description="この自治体で interest に一致する上位議題 (各 dict: title, summary, relevance_score, detail_url)",
    )


class ComparisonTable(BaseModel):
    """compare_municipalities の出力 (複数自治体の同テーマ比較)。"""

    interest: Interest = Field(description="比較対象テーマ")
    rows: list[ComparisonRow] = Field(description="各自治体の議題リスト (入力順)")
    neutral_observation: str | None = Field(
        default=None,
        max_length=400,
        description=(
            "Gemini で生成した中立観察 (各自治体の違いを 200-400 字で要約、政治的判断なし)"
        ),
    )


class CompareMunicipalitiesArgs(BaseModel):
    """compare_municipalities tool の引数。"""

    municipality_codes: list[str] = Field(
        min_length=2,
        max_length=3,
        description="比較対象の 5 桁 municipality_code (2-3 件)",
    )
    interest: Interest = Field(description="比較する関心軸 (例: '子育て')")
    limit: int = Field(default=3, ge=1, le=5, description="各自治体の上位議題件数")
    include_observation: bool = Field(default=True, description="True なら Gemini で中立観察を生成")


# ============================================================================
# Tool 3: fetch_city_dashboard
# ============================================================================


class TopicCount(BaseModel):
    """街ダッシュボードの interest 別議題数。"""

    interest: Interest
    count: int = Field(ge=0)


class CityDashboardSummary(BaseModel):
    """fetch_city_dashboard の出力。"""

    municipality_code: str
    name: str
    prefecture: str
    stats: dict = Field(default_factory=dict, description="主要統計指標 (key-value)")
    topic_counts: list[TopicCount] = Field(
        default_factory=list, description="関心軸別の議題数 (降順)"
    )
    top_speeches: list[dict] = Field(
        default_factory=list,
        description=("relevance 順上位議題 (各 dict: title, summary, relevance_score, detail_url)"),
    )


class FetchCityDashboardArgs(BaseModel):
    """fetch_city_dashboard tool の引数。"""

    municipality_code: str = Field(min_length=5, max_length=5)
    user_id: Literal["demo-18-24", "demo-25-29", "demo-30-39", "demo-40-49", "demo-50+"] = Field(
        description="ペルソナ ID (採点コンテキスト)"
    )
    limit: int = Field(default=10, ge=1, le=30)


# ============================================================================
# Tool 4: fetch_city_speeches
# ============================================================================


class ScoredSpeechSummary(BaseModel):
    """fetch_city_speeches の 1 件。"""

    speech_id: str
    title: str | None = None
    summary: list[str] = Field(default_factory=list)
    relevance_score: int = Field(ge=0, le=100)
    matched_interests: list[Interest] = Field(default_factory=list)
    detail_url: str | None = None
    meeting_date: str | None = None  # ISO date string


class FetchCitySpeechesArgs(BaseModel):
    """fetch_city_speeches tool の引数。"""

    municipality_code: str = Field(min_length=5, max_length=5)
    interest: Interest | None = Field(default=None, description="None なら interest フィルタなし")
    user_id: Literal["demo-18-24", "demo-25-29", "demo-30-39", "demo-40-49", "demo-50+"] = Field(
        default="demo-25-29", description="ペルソナ ID"
    )
    limit: int = Field(default=5, ge=1, le=20)


# ============================================================================
# Concierge Agent 入出力 (FastAPI endpoint と Agent core で共有)
# ============================================================================


class UserPersonaInput(BaseModel):
    """Concierge に渡すユーザーペルソナ (簡略版、relevance.UserPersona と互換)。"""

    user_id: str = Field(default="anonymous")
    age_group: AgeGroup = Field(default="25-29")
    interests: list[Interest] = Field(default_factory=list)
    municipality_codes: list[str] = Field(
        default_factory=list,
        description="現在の登録自治体 (移住前の現住所等)、空可",
    )
    free_form_context: str = Field(
        default="",
        max_length=500,
        description="フリー記述 (例: '介護で実家に戻る予定')、Concierge の判断材料",
    )


class ToolCallLog(BaseModel):
    """1 つの tool 呼び出しの log (Concierge response に含めて UI で表示用)。"""

    model_config = ConfigDict(extra="allow")

    name: str = Field(description="tool 関数名")
    args: dict = Field(default_factory=dict, description="呼び出し引数")
    output_preview: str = Field(
        default="",
        max_length=300,
        description="出力の short preview (JSON文字列の最初の 300 文字)",
    )
    duration_ms: int = Field(default=0, ge=0)


class ConciergeRequest(BaseModel):
    """POST /v1/concierge の request body。"""

    message: str = Field(min_length=1, max_length=2000, description="ユーザーの自由文")
    persona: UserPersonaInput = Field(description="ユーザープロファイル")


class ConciergeResponse(BaseModel):
    """POST /v1/concierge の response body。"""

    reply: str = Field(description="Concierge Agent からの返答テキスト")
    tool_calls: list[ToolCallLog] = Field(
        default_factory=list, description="この response 生成中に呼ばれた tool 履歴"
    )
    candidates: list[MunicipalityCandidate] = Field(
        default_factory=list,
        description="search_municipalities が呼ばれた場合の TOP N 候補 (UI cards 用)",
    )
    ethical_violations: list[str] = Field(
        default_factory=list,
        description="post-validation で検出された倫理違反 (空ならクリア)",
    )
