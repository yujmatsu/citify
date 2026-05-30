"""CostAnomalyHunter Agents (Plan CC、最後の余裕枠 COULD):

GCP リソース cost data から異常スパイク検知 + 根本原因診断 + 削減提案。
Plan F (Scraper Doctor) と類似の 2 段階構成 (Detector 純計算 + RootCauseAgent LLM)。

倫理ガード:
    - Self-healing は **提案のみ**、自動 cost 削減 action は実行しない (PROJECT.md §5)
    - CostRootCauseProposal.requires_human_review=True を schema 強制
    - monthly_savings_estimate_jpy は schema で le=100_000 上限 cap (Reviewer Critical)
    - scale_down + vertex_ai/cloud_run の組合せは自動で risky 上書き (Reviewer High #3)
"""

from .detector import CostAnomalyDetector, classify_severity, detect_cross_service_pattern
from .main import CostRootCauseAgent
from .schema import (
    CostAnomaly,
    CostHealthEntry,
    CostHealthResponse,
    CostObservation,
    CostRootCauseProposal,
    ServiceName,
)
from .seed_loader import load_sample_seed

__all__ = [
    "CostAnomaly",
    "CostAnomalyDetector",
    "CostHealthEntry",
    "CostHealthResponse",
    "CostObservation",
    "CostRootCauseAgent",
    "CostRootCauseProposal",
    "ServiceName",
    "classify_severity",
    "detect_cross_service_pattern",
    "load_sample_seed",
]
