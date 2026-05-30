"""Cost Anomaly Hunter の入出力 Pydantic スキーマ (Plan CC)。"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

ServiceName = Literal[
    "bigquery",
    "cloud_run",
    "firestore",
    "vertex_ai",
    "cloud_storage",
    "pubsub",
    "other",
]

AnomalyType = Literal["spike", "drift_up", "drift_down", "normal"]
Severity = Literal["critical", "high", "medium", "low"]
ProposedAction = Literal[
    "scale_down",
    "optimize_query",
    "investigate_logs",
    "rate_limit",
    "manual_review",
]
RiskAssessment = Literal["safe", "moderate", "risky"]


class CostObservation(BaseModel):
    """1 日 × 1 service の cost 観測点 (GCP Billing 想定、MVP は sample seed)。"""

    date: date
    service: ServiceName
    cost_jpy: float = Field(ge=0.0)
    project_id: str = "citify-dev"


class CostAnomaly(BaseModel):
    """Detector 出力: 1 観測点に対する異常スコア。"""

    date: date
    service: ServiceName
    cost_jpy: float = Field(ge=0.0)
    baseline_avg_7d: float = Field(ge=0.0)
    baseline_stddev_7d: float = Field(ge=0.0)
    z_score: float
    spike_ratio: float = Field(description="cost_jpy / baseline_avg_7d (baseline 0 なら 0)")
    anomaly_type: AnomalyType
    severity: Severity


class CostRootCauseProposal(BaseModel):
    """RootCauseAgent 出力 (LLM 構造化 + サーバー側強制)。"""

    root_cause_hypothesis: str = Field(max_length=240)
    proposed_action: ProposedAction
    rationale: str = Field(max_length=240)
    # Reviewer Critical: LLM overshoot 構造防止 (schema 上限)
    monthly_savings_estimate_jpy: int = Field(
        default=0,
        ge=0,
        le=100_000,
        description="推定削減額。Reviewer Critical: 月 10 万円上限 cap",
    )
    risk_assessment: RiskAssessment
    # 構造的安全性: Plan F と同じ、サーバー側で True 強制
    requires_human_review: bool = Field(
        default=True,
        description="**常に True**、自動 cost 削減 action 防止 (PROJECT.md §5)",
    )
    source: Literal["llm", "rule_based"] = Field(default="llm")


class CostHealthEntry(BaseModel):
    """1 異常 + その診断+提案 セット。"""

    anomaly: CostAnomaly
    proposal: CostRootCauseProposal


class CostHealthResponse(BaseModel):
    """GET /v1/cost-health のレスポンス。"""

    period_start: date
    period_end: date
    total_anomalies: int = Field(ge=0)
    by_service: dict[str, int] = Field(default_factory=dict)
    by_severity: dict[str, int] = Field(default_factory=dict)
    estimated_total_savings_jpy: int = Field(
        default=0, ge=0, description="全 proposal の monthly_savings 合計"
    )
    entries: list[CostHealthEntry] = Field(default_factory=list)
    # Reviewer Medium #4: Plan F との差別化 (横断パターン認識)
    cross_service_pattern: str | None = Field(
        default=None,
        max_length=200,
        description="同日 spike 複数 service なら rule-based パターン記述 (e.g. 'deploy 起因の可能性')",
    )
    disclaimer: str = Field(
        default=(
            "本ページの cost 削減提案は Agent 推定値です。"
            "実適用前に IAM / DBA / 経理レビュー必須。自動削減は実装されません。"
        ),
    )
