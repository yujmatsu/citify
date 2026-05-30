"""Scraper Doctor の入出力 Pydantic スキーマ (Plan F)。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ScraperName = Literal[
    "kaigiroku_net",
    "kokkai",
    "press_rss",
    "reinfolib",
    "voices_asp",
    "discussnet",
    "other",
]

ErrorCategory = Literal[
    "ssl_failure",
    "auth_403",
    "html_structure_change",
    "robots_disallow",
    "network_timeout",
    "rate_limit",
    "parser_logic",
    "unknown",
]

Severity = Literal["critical", "high", "medium", "low"]
Confidence = Literal["high", "medium", "low"]
ProposedAction = Literal[
    "user_agent_change",
    "retry_strategy_adjust",
    "parser_path_update",
    "drop_tenant",
    "robots_check",
    "manual_review",
]
RiskAssessment = Literal["safe", "moderate", "risky"]


class ScraperFailureLog(BaseModel):
    """1 失敗の記録 (Firestore scraper_failures collection と一致)。

    failure_id は BQ scraper_runs.run_id と互換性ある形式:
    `{scraper}__{timestamp_iso}__{seq:04d}`
    """

    failure_id: str = Field(description="`{scraper}__{timestamp_iso}__{seq:04d}` 形式")
    timestamp: datetime
    scraper: ScraperName
    tenant_id: str | None = Field(default=None, description="例: prefokayama")
    municipality_code: str | None = None
    url: str | None = Field(default=None, max_length=500)
    error_type: str = Field(max_length=80, description="例: SSLError / HTTPError 403")
    stack_trace: str = Field(default="", max_length=2000)
    html_snippet: str | None = Field(
        default=None, max_length=2000, description="PII マスク済を保存"
    )
    duration_ms: int | None = Field(default=None, ge=0)
    # 重複排除用
    html_signature: str = Field(
        default="",
        max_length=20,
        description="HTML tag-only skeleton の sha256[:16] (重複排除用)",
    )


class DiagnosticResult(BaseModel):
    """DiagnosticAgent 出力 (Gemini response_schema で強制)。"""

    error_category: ErrorCategory
    root_cause_text: str = Field(max_length=240, description="200 字、なぜ失敗したか")
    confidence: Confidence
    severity: Severity
    source: Literal["llm", "rule_based"] = Field(default="llm")


class RepairProposal(BaseModel):
    """RepairProposalAgent 出力 (Auto-PR 構造防止: requires_human_review=True 既定)。"""

    proposed_action: ProposedAction
    rationale: str = Field(max_length=240, description="なぜこの修正案か")
    code_hint: str = Field(
        default="",
        max_length=300,
        description="人間が編集する diff のヒント (実コードではない)",
    )
    risk_assessment: RiskAssessment
    # 構造的安全性 (Reviewer Critical 想定): default True、変更禁止
    requires_human_review: bool = Field(
        default=True,
        description="**常に True**、自動 PR/commit を構造的に防止 (PROJECT.md §5)",
    )
    source: Literal["llm", "rule_based"] = Field(default="llm")


class ScraperHealthEntry(BaseModel):
    """1 失敗パターンに対する完全な診断+提案 1 セット。"""

    failure: ScraperFailureLog
    diagnostic: DiagnosticResult
    proposal: RepairProposal


class ScraperHealthResponse(BaseModel):
    """GET /v1/scraper-health のレスポンス。"""

    period_start: datetime
    period_end: datetime
    total_failures: int = Field(ge=0)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_scraper: dict[str, int] = Field(default_factory=dict)
    entries: list[ScraperHealthEntry] = Field(default_factory=list, max_length=50)
    drop_candidates: list[str] = Field(
        default_factory=list,
        description="proposed_action='drop_tenant' な tenant_id 一覧",
    )
    disclaimer: str = Field(
        default=(
            "本ページの修正提案は Agent が生成したもので、自動修正は適用されません。"
            "人間レビュー後に手動で適用してください。"
        ),
        description="UI で disclaimer banner として表示する固定文言",
    )
