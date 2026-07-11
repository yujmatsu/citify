"""OpsCrew: 運用 SRE マルチエージェントクルーの I/O スキーマ。

Watcher と同じ「計画→並列専門家→統合→批判→人間ゲート」パターンを、
プロダクトではなく **自分たちの運用** (スクレイパー健全性 / コスト異常 / データ鮮度)
に適用する。既存の scraper_doctor / cost_hunter を専門家として合成する。

安全原則 (PROJECT.md §5 / scraper_doctor・cost_hunter と一貫):
    - すべての改善提案は `requires_human_review=True` を **サーバー側で強制**。
    - 自動実行は一切しない。クルーは「診断と提案」までで人間ゲートの前で止まる。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]
RiskAssessment = Literal["safe", "moderate", "risky"]
OpsStatus = Literal["ok", "empty", "error"]
OpsDomain = Literal["scraper_health", "cost", "data_freshness"]


class OpsToolCall(BaseModel):
    """クルーが呼んだツール/専門家の1手 (自律トレース可視化用)。"""

    tool: str
    args: dict = Field(default_factory=dict)


class OpsFinding(BaseModel):
    """1 専門家ドメインの所見。"""

    domain: OpsDomain
    headline: str = Field(default="", max_length=160)
    key_points: list[str] = Field(default_factory=list)
    severity: str = Field(default="none", description="critical/high/medium/low/none (専門家由来)")
    confidence: Confidence = "medium"
    source_refs: list[str] = Field(default_factory=list, description="failure_id / service 等")


class OpsRemediationProposal(BaseModel):
    """改善提案。自動実行はせず必ず人間レビュー前提 (requires_human_review 強制 True)。"""

    domain: OpsDomain
    action: str = Field(max_length=80)
    rationale: str = Field(default="", max_length=400)
    risk_assessment: RiskAssessment = "moderate"
    requires_human_review: bool = Field(default=True, description="**常に True** (自動実行防止)")
    source: Literal["llm", "rule_based"] = "rule_based"


class OpsVerdict(BaseModel):
    """クルーの統合結論。"""

    headline: str = Field(default="", max_length=160)
    reasoning: str = Field(default="", max_length=600)
    top_priority_domain: OpsDomain | None = None
    confidence: Confidence = "medium"
    requires_human_review: bool = Field(default=True, description="**常に True**")


class OpsAssessment(BaseModel):
    """1 回の運用アセスメントの完全な結果 (verdict + 所見 + 提案 + 透明性)。"""

    verdict: OpsVerdict
    findings: list[OpsFinding] = Field(default_factory=list)
    proposals: list[OpsRemediationProposal] = Field(default_factory=list)
    critique_note: str = Field(default="", max_length=600, description="批判エージェントの指摘")
    investigation_plan: list[str] = Field(default_factory=list)


class OpsRunLog(BaseModel):
    """自律実行の証跡 (Watcher AgentRunLog と同型)。"""

    run_id: str = ""
    targets_checked: list[str] = Field(default_factory=list)
    tool_calls: list[OpsToolCall] = Field(default_factory=list)
    n_findings: int = 0
    token_cost: int | None = None
    status: OpsStatus = "ok"
    note: str = ""


class OpsCrewResult(BaseModel):
    """OpsCrewAgent.run の返り値。"""

    assessment: OpsAssessment | None = None
    run_log: OpsRunLog
