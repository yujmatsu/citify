"""ScraperDoctor (Plan F): スクレイパー失敗を 2 段階 Agent で診断 + 修正提案。

2 段階構成 (Plan X / Z と一貫):
    - DiagnosticAgent: 失敗ログ → error_category + root_cause + severity
    - RepairProposalAgent: diagnostic → 修正提案 (action + rationale + code_hint + risk)

倫理ガード:
    - Self-healing は **提案のみ**、自動 PR / commit は実装しない (PROJECT.md §5)
    - RepairProposal.requires_human_review=True を schema 強制
    - DiagnosticResult / RepairProposal 両方で _detect_any_leak (Plan Z 流用)
    - LLM に渡す html_snippet は PII (email/phone/IPv4/token) を mask_pii で regex マスク
"""

from .main import DiagnosticAgent, RepairProposalAgent
from .pii import PII_PATTERNS, mask_pii
from .schema import (
    DiagnosticResult,
    ErrorCategory,
    ProposedAction,
    RepairProposal,
    ScraperFailureLog,
    ScraperHealthEntry,
    ScraperHealthResponse,
    ScraperName,
)

__all__ = [
    "PII_PATTERNS",
    "DiagnosticAgent",
    "DiagnosticResult",
    "ErrorCategory",
    "ProposedAction",
    "RepairProposal",
    "RepairProposalAgent",
    "ScraperFailureLog",
    "ScraperHealthEntry",
    "ScraperHealthResponse",
    "ScraperName",
    "mask_pii",
]
