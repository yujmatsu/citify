"""CostRootCauseAgent tests (Plan CC Phase 2)。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.cost_hunter.main import (
    MAX_MONTHLY_SAVINGS_CAP,
    CostRootCauseAgent,
    _enforce_safety_constraints,
)
from agents.cost_hunter.schema import (
    CostAnomaly,
    CostRootCauseProposal,
    ServiceName,
)


def _make_anomaly(
    service: ServiceName = "bigquery",
    anomaly_type: str = "spike",
    spike_ratio: float = 3.0,
    z_score: float = 5.0,
    cost_jpy: float = 600.0,
    severity: str = "critical",
) -> CostAnomaly:
    return CostAnomaly(
        date=date(2026, 5, 20),
        service=service,
        cost_jpy=cost_jpy,
        baseline_avg_7d=200.0,
        baseline_stddev_7d=20.0,
        z_score=z_score,
        spike_ratio=spike_ratio,
        anomaly_type=anomaly_type,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
    )


def _mock_proposal(
    action: str = "optimize_query",
    savings: int = 30_000,
    risk: str = "moderate",
    rationale: str = "BigQuery 全件 scan を解消、partition pruning を追加",
    hypothesis: str = "重い ANALYZE クエリで scan 量が baseline の 3x に増加",
    source: str = "llm",
) -> CostRootCauseProposal:
    return CostRootCauseProposal(
        root_cause_hypothesis=hypothesis,
        proposed_action=action,  # type: ignore[arg-type]
        rationale=rationale,
        monthly_savings_estimate_jpy=savings,
        risk_assessment=risk,  # type: ignore[arg-type]
        requires_human_review=True,
        source=source,  # type: ignore[arg-type]
    )


# ============================================================================
# 1) LLM 成功 path
# ============================================================================


def test_propose_returns_llm_proposal_on_success() -> None:
    expected = _mock_proposal()
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=expected, text="")

    agent = CostRootCauseAgent(client=client)
    result = agent.propose(_make_anomaly())
    assert result.source == "llm"
    assert result.proposed_action == "optimize_query"
    assert result.requires_human_review is True


# ============================================================================
# 2) LLM 失敗 → rule_based fallback (anomaly_type/service マッピング)
# ============================================================================


def test_propose_falls_back_on_llm_exception() -> None:
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("LLM down")

    agent = CostRootCauseAgent(client=client)
    result = agent.propose(_make_anomaly(service="bigquery"))
    assert result.source == "rule_based"
    assert result.proposed_action == "optimize_query"  # bigquery default
    assert "(rule-based)" in result.rationale
    assert result.monthly_savings_estimate_jpy == 0  # rule_based は推定なし


# ============================================================================
# 3) 倫理 leak in rationale → fallback
# ============================================================================


def test_propose_falls_back_on_leak_in_rationale() -> None:
    leaky = _mock_proposal(rationale="東京都リージョンの BigQuery が異常")
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky, text="")

    agent = CostRootCauseAgent(client=client)
    result = agent.propose(_make_anomaly())
    assert result.source == "rule_based"
    assert "東京都" not in result.rationale


# ============================================================================
# 4) Reviewer Critical: monthly_savings_estimate_jpy が schema le=100_000 で reject
# ============================================================================


def test_proposal_schema_rejects_savings_over_cap() -> None:
    """schema 上限 le=100_000 で 100_001 は ValidationError。"""
    import pytest as _pytest
    from pydantic import ValidationError

    with _pytest.raises(ValidationError):
        CostRootCauseProposal(
            root_cause_hypothesis="x",
            proposed_action="optimize_query",
            rationale="x",
            monthly_savings_estimate_jpy=100_001,  # cap 超過
            risk_assessment="safe",
        )


# ============================================================================
# 5) Reviewer Critical: server-side savings clamp (LLM が cap 内でも server で min 適用)
# ============================================================================


def test_enforce_safety_clamps_savings_to_cap() -> None:
    """schema cap 内でも 100_000 で clamp (二重防御)。"""
    proposal = _mock_proposal(savings=99_999)
    enforced = _enforce_safety_constraints(proposal, _make_anomaly())
    assert enforced.monthly_savings_estimate_jpy == 99_999  # 範囲内ならそのまま

    proposal2 = _mock_proposal(savings=50_000)
    enforced2 = _enforce_safety_constraints(proposal2, _make_anomaly())
    assert enforced2.monthly_savings_estimate_jpy == 50_000


def test_max_monthly_savings_cap_constant() -> None:
    assert MAX_MONTHLY_SAVINGS_CAP == 100_000


# ============================================================================
# 6) Reviewer High #3: scale_down + vertex_ai → 自動 risky 上書き
# ============================================================================


def test_enforce_safety_overrides_to_risky_for_scale_down_vertex_ai() -> None:
    """LLM が safe で返してもサーバー側で risky 強制。"""
    proposal = _mock_proposal(action="scale_down", risk="safe")
    enforced = _enforce_safety_constraints(proposal, _make_anomaly(service="vertex_ai"))
    assert enforced.risk_assessment == "risky"


def test_enforce_safety_overrides_to_risky_for_scale_down_cloud_run() -> None:
    proposal = _mock_proposal(action="scale_down", risk="moderate")
    enforced = _enforce_safety_constraints(proposal, _make_anomaly(service="cloud_run"))
    assert enforced.risk_assessment == "risky"


def test_enforce_safety_keeps_moderate_for_scale_down_bigquery() -> None:
    """bigquery scale_down は user impact 低 → moderate のまま (上書きしない)。"""
    proposal = _mock_proposal(action="scale_down", risk="moderate")
    enforced = _enforce_safety_constraints(proposal, _make_anomaly(service="bigquery"))
    assert enforced.risk_assessment == "moderate"  # 上書きされない


# ============================================================================
# 7) Reviewer + Plan F 一貫: requires_human_review=True 強制
# ============================================================================


def test_enforce_safety_forces_requires_human_review_true() -> None:
    """LLM が False を返してもサーバー側で True に強制 (Plan F と同パターン)。"""
    sneaky = _mock_proposal()
    sneaky.requires_human_review = False  # LLM が False を返しても...

    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=sneaky, text="")
    agent = CostRootCauseAgent(client=client)

    result = agent.propose(_make_anomaly())
    assert result.requires_human_review is True  # 強制 True


# ============================================================================
# 8) RootCauseProposal schema default で requires_human_review=True
# ============================================================================


def test_proposal_schema_default_requires_human_review_true() -> None:
    proposal = CostRootCauseProposal(
        root_cause_hypothesis="x",
        proposed_action="optimize_query",
        rationale="x",
        risk_assessment="safe",
    )
    assert proposal.requires_human_review is True


# ============================================================================
# 9) rule_based fallback: service 別の default action マッピング
# ============================================================================


def test_rule_based_action_mapping_for_each_service() -> None:
    """LLM 失敗時の rule_based action が service ごとに適切。"""
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("LLM down")
    agent = CostRootCauseAgent(client=client)

    bq = agent.propose(_make_anomaly(service="bigquery"))
    assert bq.proposed_action == "optimize_query"

    cr_low = agent.propose(_make_anomaly(service="cloud_run", spike_ratio=1.3))
    assert cr_low.proposed_action == "investigate_logs"

    cr_high = agent.propose(_make_anomaly(service="cloud_run", spike_ratio=2.5))
    assert cr_high.proposed_action == "rate_limit"

    fs = agent.propose(_make_anomaly(service="firestore"))
    assert fs.proposed_action == "optimize_query"
