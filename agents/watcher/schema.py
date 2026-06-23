"""マイ街エージェント (Watcher) の入出力スキーマ (TASK-WATCHER Slice 1)。

自律型 Civic Watch Agent: ユーザーのウォッチ街(住む街 + 気になる街)の新着から、
本人に意味があるものを *エージェントが自分で判断・調査して* 見つける。
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator

from agents.relevance.schema import AgeGroup, Interest

Confidence = Literal["high", "medium", "low"]


class WatchInput(BaseModel):
    """1 ユーザー分のウォッチ・コンテキスト (エージェント実行の入力)。"""

    user_id: str
    age_group: AgeGroup
    interests: list[Interest] = Field(default_factory=list)
    home_municipality_code: str = Field(description="住む街 (5 桁)")
    watched_codes: list[str] = Field(
        default_factory=list, description="気になる街 (home 含め上限 5)"
    )
    # TASK-ONBOARDING: 前提整理 (全て省略可・後方互換)
    priorities: list[Interest] = Field(
        default_factory=list, description="特に重視する関心軸 上位3 (順位順)"
    )
    household: str = Field(default="", description="家族構成 single/couple/family_kids/other")
    budget_man: int | None = Field(default=None, description="住まいの予算上限 (万円)")
    free_form_context: str = Field(default="", description="移住の背景・動機 (自由記述)")

    MAX_TOWNS: ClassVar[int] = 5

    def all_codes(self) -> list[str]:
        """home + watched を重複なしで返す (home 先頭、上限 MAX_TOWNS で truncate)。

        上限超過は ValidationError で止めず先頭 N 件に truncate (graceful 思想)。
        """
        seen: list[str] = []
        for c in [self.home_municipality_code, *self.watched_codes]:
            if c and c not in seen:
                seen.append(c)
        return seen[: self.MAX_TOWNS]


class TownAssessment(BaseModel):
    """1 つの街(住む街=基準 or 気になる街=候補)の多軸評価。

    LLM 出力を取りこぼさないため文字数・スコアは validator で *切り詰め/clamp* し、
    制約超過でも ValidationError にしない (parse 失敗で analysis が空になるのを防ぐ)。
    """

    municipality_code: str
    role: Literal["home", "candidate"] = Field(
        description="home=住む街(基準) / candidate=気になる街(移住候補)"
    )
    headline: str = Field(description="この街の一言評価 (簡潔に)")
    strengths: list[str] = Field(
        default_factory=list, description="あなたにとっての強み (人口/子育て/住居/医療/議題)"
    )
    concerns: list[str] = Field(
        default_factory=list, description="あなたにとっての懸念 (人口減/コスト等)"
    )
    population_outlook: str = Field(
        default="", description="人口の将来見通し (2070 まで) の短い説明"
    )
    recent_signal: str = Field(default="", description="直近議題から拾った 1 つの動き (任意)")
    source_speech_ids: list[str] = Field(
        default_factory=list, description="根拠とした議題 speech_id (引用必須、A11)"
    )
    fit_score: int = Field(default=50, description="あなたへの適合度 0-100")
    confidence: Confidence = Field(
        default="medium", description="この評価の確信度 (データの厚みに応じて、A7)"
    )

    @field_validator("fit_score", mode="before")
    @classmethod
    def _clamp_fit(cls, v: object) -> int:
        try:
            n = int(v)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 50
        return max(0, min(100, n))


class WatchVerdict(BaseModel):
    """エージェントの"生きた結論" (移るべきか/移るならどこか)。差別化の核。"""

    headline: str = Field(description="生きた結論 1 行 (例: 今のところ小田原が優勢)")
    reasoning: str = Field(
        default="", description="なぜその結論か (人口/子育て/住居/議題の多軸統合)"
    )
    recommended_code: str | None = Field(
        default=None, description="現時点の推し街コード (住み続けるべきなら home の code)"
    )
    confidence: Confidence = Field(default="medium", description="結論全体の確信度 (A7)")
    contains_political_judgment: bool = Field(
        default=False, description="倫理チェック: 賛否表明/政党推奨を含むか"
    )


class SpecialistFinding(BaseModel):
    """専門エージェント1人のドメイン所見 (P3 マルチエージェント、A5)。"""

    domain: str = Field(description="担当ドメイン (population/fiscal/living_safety/topics)")
    headline: str = Field(default="", description="このドメインの一言所見")
    key_points: list[str] = Field(default_factory=list, description="要点 (街比較を含む)")
    confidence: Confidence = Field(default="medium", description="所見の確信度")
    source_speech_ids: list[str] = Field(
        default_factory=list, description="根拠とした議題 speech_id (A11)"
    )


class Critique(BaseModel):
    """Critic(自己批判)の出力 (A1)。草案の根拠・見落とし・引用整合を検証。"""

    issues: list[str] = Field(default_factory=list, description="論理/整合の問題点")
    missing_axes: list[str] = Field(default_factory=list, description="見落とした評価軸")
    grounding_failures: list[str] = Field(
        default_factory=list, description="根拠(引用)が無い/弱い主張"
    )
    needs_revision: bool = Field(default=False, description="修正が必要か")


class Advocacy(BaseModel):
    """Devil's Advocate(反論役)の出力 (A9)。反対の結論を主張し弱点を突く。"""

    counter_verdict: str = Field(default="", description="反対の結論(例: 実は小田原が良い)")
    strongest_points: list[str] = Field(
        default_factory=list, description="その根拠として最も強い点"
    )


class TownAnalysis(BaseModel):
    """エージェント 1 実行の最終アウトプット (比較 + 生きた結論)。"""

    verdict: WatchVerdict
    town_assessments: list[TownAssessment] = Field(default_factory=list)
    watch_points: list[str] = Field(
        default_factory=list, description="次の決め手になりうる変化 (継続ウォッチの観点)"
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="確定のために何が分かれば良いか (A7: エージェントが認識する不確実性)",
    )
    # P2: 検証と反論の透明性 (A1 / A9)
    critique_note: str = Field(
        default="", description="自己批判で何を再確認/修正したか (A1、透明性)"
    )
    devils_advocate: str = Field(
        default="", description="反論役が提示した反対視点の要約 (A9、透明性)"
    )
    # P3: 専門家の所見 (A5、コードで付与。LLM 統合の元データ)
    specialist_findings: list[SpecialistFinding] = Field(default_factory=list)
    # P4: 前回分析からの変化 (A3、コードで付与)
    changes_since_last: list[str] = Field(default_factory=list)
    # Lv3: Coordinator が自分で立てた調査計画 (自律性の可視化、coordinator モードのみ)
    investigation_plan: list[str] = Field(
        default_factory=list,
        description="エージェントが最初に宣言した調査方針 (record_plan、自律性の証跡)",
    )


class OfficialLink(BaseModel):
    """移住アクションプランの公式/信頼ポータルへの誘導リンク (TASK-ACTIONPLAN)。"""

    label: str
    url: str


class NationalSupport(BaseModel):
    """国の移住支援金(地方創生移住支援事業)の判定結果 (TASK-SUPPORT、断定せず"可能性")。"""

    eligibility: Literal["likely", "conditional", "unlikely"] = "unlikely"
    amount_man: int | None = Field(default=None, description="概算上限(万円)、対象外は None")
    child_addition: bool = Field(default=False, description="18歳未満の子加算の可能性(子育て世帯)")
    requirements: str = Field(default="", description="満たすべき要件(就業/テレワーク/起業 等)")
    official_url: str = Field(default="", description="一次情報(自治体公式 or 国ポータル)")
    note: str = Field(default="", description="前提・判定理由(現住所/移住先)")


class LocalSupport(BaseModel):
    """自治体独自の支援(LLM抽出、TASK-SUPPORT P2)。金額は断定せず公式で要確認。"""

    name: str
    summary: str = ""
    official_url: str = ""
    source_url: str = Field(default="", description="抽出のグラウンディング出典")


class RelocationSupport(BaseModel):
    """移住支援金マッチング結果 (国制度＋自治体独自)。"""

    national: NationalSupport | None = None
    local: list[LocalSupport] = Field(default_factory=list)


class ActionPlan(BaseModel):
    """移住アクションプラン (TASK-ACTIONPLAN)。Watcher の結論を行動に変換した持ち帰り1枚。

    結論は生成せず TownAnalysis を再利用 (4つ目の結論を作らない)。生成は visit_checklist のみ。
    mode=stay は「住み続ける」推奨時の据え置きモード (窓口非表示・訪問→自街再点検)。
    """

    mode: Literal["relocate", "stay"] = "relocate"
    recommended_code: str
    recommended_name: str
    role: Literal["home", "candidate"] = "candidate"
    decision_summary: str = Field(default="", description="結論 1 行 (verdict.headline 再利用)")
    reasons: list[str] = Field(default_factory=list, description="なぜこの街か (再利用)")
    open_questions: list[str] = Field(default_factory=list, description="残る確認事項 (再利用)")
    visit_checklist: list[str] = Field(
        default_factory=list, description="現地で確認すべき街固有の項目 (生成)"
    )
    official_links: list[OfficialLink] = Field(
        default_factory=list, description="移住相談窓口/信頼ポータル (stay は空)"
    )
    support: RelocationSupport | None = Field(
        default=None, description="移住支援金マッチング (TASK-SUPPORT、未判定は None)"
    )
    run_id: str = Field(default="", description="元になった分析の run_id (キャッシュ鍵)")
    generated_at: str = Field(default="", description="生成時刻 ISO8601")


class ToolCall(BaseModel):
    """エージェントが自律的に実行したツール呼び出し 1 回の記録 (①の自律証跡)。"""

    tool: str
    args: dict = Field(default_factory=dict)


class AgentRunLog(BaseModel):
    """1 回の自律実行ログ (agent_runs 相当、透明性 + コスト監視)。"""

    run_id: str = Field(default="", description="一意な実行 ID (logs↔discoveries の join 用)")
    user_id: str
    towns_checked: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(
        default_factory=list, description="LLM が自分で選んで呼んだツール列 = 自律性の証跡"
    )
    n_discoveries: int = 0
    token_cost: int | None = Field(
        default=None, description="最終 event の usage (取れなければ None)"
    )
    status: Literal["ok", "empty", "error", "max_iterations"] = "ok"
    note: str = ""


class WatcherResult(BaseModel):
    """エージェント 1 実行の最終結果。"""

    analysis: TownAnalysis | None = Field(
        default=None, description="比較 + 生きた結論 (parse 失敗時は None)"
    )
    run_log: AgentRunLog
