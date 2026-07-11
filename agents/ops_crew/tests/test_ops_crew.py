"""OpsCrewAgent の単体テスト。

全依存 (sub-agents / repo / detector / seed / synth client) を注入し、
live LLM / GCP を一切呼ばずに、合成・並列・統合・安全ゲートを検証する。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from agents.cost_hunter.schema import CostAnomaly, CostObservation, CostRootCauseProposal
from agents.ops_crew.main import OpsCrewAgent
from agents.scraper_doctor.schema import DiagnosticResult, RepairProposal, ScraperFailureLog

# --------------------------------------------------------------------------- fakes


def _failure(fid: str = "kaigiroku_net__2026-06-01__0001") -> ScraperFailureLog:
    return ScraperFailureLog(
        failure_id=fid,
        timestamp=datetime(2026, 6, 1, tzinfo=UTC),
        scraper="kaigiroku_net",
        error_type="HTTPError 403",
        html_signature=fid[-8:],
    )


class _FakeFailureRepo:
    def __init__(self, failures: list[ScraperFailureLog]) -> None:
        self._f = failures

    def fetch_recent(self, days: int = 7, limit: int = 50) -> list[ScraperFailureLog]:
        return list(self._f)

    def load_sample_seed(self) -> list[ScraperFailureLog]:
        return list(self._f)


class _FakeDiagnostic:
    def __init__(self, severity: str = "high") -> None:
        self._sev = severity

    def diagnose(self, failure: ScraperFailureLog) -> DiagnosticResult:
        return DiagnosticResult(
            error_category="auth_403",
            root_cause_text="403 が返っている",
            confidence="medium",
            severity=self._sev,
            source="rule_based",
        )


class _FakeRepair:
    def __init__(self, action: str = "user_agent_change", risk: str = "moderate") -> None:
        self._action = action
        self._risk = risk

    def propose(self, diag: DiagnosticResult, failure: ScraperFailureLog) -> RepairProposal:
        return RepairProposal(
            proposed_action=self._action,
            rationale="UA を変える",
            risk_assessment=self._risk,
            source="rule_based",
        )


class _FakeDetector:
    def __init__(self, anomalies: list[CostAnomaly]) -> None:
        self._a = anomalies

    def detect_anomalies(self, observations: list[CostObservation]) -> list[CostAnomaly]:
        return list(self._a)


class _FakeRootCause:
    def propose(self, anomaly: CostAnomaly, trend_summary: str = "") -> CostRootCauseProposal:
        return CostRootCauseProposal(
            root_cause_hypothesis="クエリ増",
            proposed_action="optimize_query",
            rationale="スキャン量削減",
            monthly_savings_estimate_jpy=5000,
            risk_assessment="safe",
            source="rule_based",
        )


def _anomaly(service: str = "bigquery", severity: str = "critical") -> CostAnomaly:
    return CostAnomaly(
        date=date(2026, 6, 1),
        service=service,
        cost_jpy=1000.0,
        baseline_avg_7d=100.0,
        baseline_stddev_7d=10.0,
        z_score=9.0,
        spike_ratio=10.0,
        anomaly_type="spike",
        severity=severity,
    )


class _FakeSynthClient:
    """models.generate_content が canned JSON text を返す fake。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self.models = SimpleNamespace(generate_content=self._gen)

    def _gen(self, **_: Any) -> Any:
        return SimpleNamespace(text=self._text)


class _RaisingSynthClient:
    def __init__(self) -> None:
        self.models = SimpleNamespace(generate_content=self._gen)

    def _gen(self, **_: Any) -> Any:
        raise RuntimeError("synth down")


def _crew(**overrides: Any) -> OpsCrewAgent:
    defaults: dict[str, Any] = {
        "failure_repo": _FakeFailureRepo([_failure()]),
        "diagnostic_agent": _FakeDiagnostic(),
        "repair_agent": _FakeRepair(),
        "cost_detector": _FakeDetector([_anomaly()]),
        "cost_root_cause_agent": _FakeRootCause(),
        "cost_seed_loader": lambda: [
            CostObservation(date=date(2026, 6, 1), service="bigquery", cost_jpy=1000.0)
        ],
        "synth_client": _FakeSynthClient(
            '{"headline":"要対応","reasoning":"403多発","top_priority_domain":"scraper_health","confidence":"high"}'
        ),
    }
    defaults.update(overrides)
    return OpsCrewAgent(project_id="citify-dev", **defaults)


# --------------------------------------------------------------------------- tests


async def test_run_produces_assessment_with_findings_and_proposals() -> None:
    result = await _crew().run(use_sample=True)
    assert result.assessment is not None
    domains = {f.domain for f in result.assessment.findings}
    assert "scraper_health" in domains and "cost" in domains
    assert result.run_log.status == "ok"
    assert result.run_log.n_findings == len(result.assessment.findings)
    assert len(result.assessment.proposals) >= 2


async def test_all_proposals_and_verdict_require_human_review() -> None:
    result = await _crew().run(use_sample=True)
    assert result.assessment is not None
    assert result.assessment.verdict.requires_human_review is True
    assert all(p.requires_human_review for p in result.assessment.proposals)


async def test_llm_verdict_used_when_synth_client_returns_json() -> None:
    result = await _crew().run(use_sample=True)
    assert result.assessment is not None
    assert result.assessment.verdict.top_priority_domain == "scraper_health"
    assert result.assessment.verdict.confidence == "high"


async def test_rule_based_fallback_when_synth_client_raises() -> None:
    result = await _crew(synth_client=_RaisingSynthClient()).run(use_sample=True)
    assert result.assessment is not None
    # fallback verdict は confidence low + 重大度最大ドメイン
    assert result.assessment.verdict.confidence == "low"
    assert result.assessment.verdict.top_priority_domain in ("scraper_health", "cost")


async def test_empty_when_no_findings() -> None:
    crew = _crew(
        failure_repo=_FakeFailureRepo([]),
        cost_detector=_FakeDetector([]),
    )
    result = await crew.run(use_sample=True)
    assert result.assessment is None
    assert result.run_log.status == "empty"


async def test_destructive_action_upgraded_to_risky() -> None:
    # cost の scale_down は破壊的ヒント → risky に引き上げ
    class _ScaleDownRootCause(_FakeRootCause):
        def propose(self, anomaly: CostAnomaly, trend_summary: str = "") -> CostRootCauseProposal:
            return CostRootCauseProposal(
                root_cause_hypothesis="過剰インスタンス",
                proposed_action="scale_down",
                rationale="インスタンス削減",
                monthly_savings_estimate_jpy=8000,
                risk_assessment="safe",
                source="rule_based",
            )

    result = await _crew(cost_root_cause_agent=_ScaleDownRootCause()).run(use_sample=True)
    assert result.assessment is not None
    cost_props = [p for p in result.assessment.proposals if p.domain == "cost"]
    assert cost_props and all(p.risk_assessment == "risky" for p in cost_props)


async def test_freshness_specialist_flags_stale_data() -> None:
    result = await _crew(
        failure_repo=_FakeFailureRepo([]),
        cost_detector=_FakeDetector([]),
    ).run(use_sample=True, freshness_hours=80.0)
    assert result.assessment is not None
    fresh = [f for f in result.assessment.findings if f.domain == "data_freshness"]
    assert fresh and fresh[0].severity in ("high", "medium")


async def test_freshness_ok_produces_no_finding() -> None:
    result = await _crew(
        failure_repo=_FakeFailureRepo([]),
        cost_detector=_FakeDetector([]),
    ).run(use_sample=True, freshness_hours=2.0)
    # scraper/cost も空 → 全体 empty
    assert result.run_log.status == "empty"


async def test_run_never_raises_on_specialist_error() -> None:
    class _BoomRepo:
        def fetch_recent(self, days: int = 7, limit: int = 50) -> list[ScraperFailureLog]:
            raise RuntimeError("firestore down")

        def load_sample_seed(self) -> list[ScraperFailureLog]:
            raise RuntimeError("seed down")

    # scraper が壊れても cost 所見で assessment は返る (graceful)
    result = await _crew(failure_repo=_BoomRepo()).run(use_sample=True)
    assert result.assessment is not None
    assert {f.domain for f in result.assessment.findings} == {"cost"}


async def test_tool_calls_traced() -> None:
    result = await _crew().run(use_sample=True)
    tools = {tc.tool for tc in result.run_log.tool_calls}
    assert "scraper.diagnose" in tools
    assert "cost.root_cause" in tools


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
