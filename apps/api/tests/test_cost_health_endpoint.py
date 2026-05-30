"""GET /v1/cost-health endpoint tests (Plan CC Phase 3)。"""

from __future__ import annotations

import sys
import types
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _stub_firestore_module() -> None:
    if "google.cloud.firestore" not in sys.modules:
        stub = types.ModuleType("google.cloud.firestore")
        stub.SERVER_TIMESTAMP = object()  # type: ignore[attr-defined]
        stub.Client = MagicMock()  # type: ignore[attr-defined]
        stub.Increment = MagicMock()  # type: ignore[attr-defined]
        sys.modules["google.cloud.firestore"] = stub


def _mock_proposal(action: str = "optimize_query", savings: int = 25_000):
    from agents.cost_hunter.schema import CostRootCauseProposal

    return CostRootCauseProposal(
        root_cause_hypothesis="BigQuery 全件 scan",
        proposed_action=action,  # type: ignore[arg-type]
        rationale="partition pruning を導入",
        monthly_savings_estimate_jpy=savings,
        risk_assessment="moderate",
        requires_human_review=True,
        source="llm",
    )


# ============================================================================
# 1) 200 + 構造完備、sample seed 経由
# ============================================================================


def test_cost_health_200_with_sample_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    """sample seed → Detector → RootCauseAgent の連携を一気通貫で確認 (Reviewer High #2)。"""
    from apps.api import main as api_main
    from apps.api.main import _COST_HEALTH_CACHE

    _COST_HEALTH_CACHE.clear()

    # RootCauseAgent mock (LLM 不要)
    mock_agent = MagicMock()
    mock_agent.propose.return_value = _mock_proposal()
    monkeypatch.setattr(api_main, "_get_cost_root_cause_agent", lambda: mock_agent)

    client = TestClient(api_main.app)
    response = client.get("/v1/cost-health", params={"days": 30})
    assert response.status_code == 200
    body = response.json()

    # 構造完備
    assert "period_start" in body
    assert "period_end" in body
    assert "total_anomalies" in body
    assert "by_service" in body
    assert "by_severity" in body
    assert "estimated_total_savings_jpy" in body
    assert "entries" in body
    assert "cross_service_pattern" in body
    assert "disclaimer" in body

    # Reviewer High #2: spike が確実に検知される (sample seed の bigquery/cloud_run spike)
    assert body["total_anomalies"] >= 1


# ============================================================================
# 2) Cross-service pattern が検出される (Reviewer Medium #4、bigquery + cloud_run 同日 spike)
# ============================================================================


def test_cost_health_detects_cross_service_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.main import _COST_HEALTH_CACHE

    _COST_HEALTH_CACHE.clear()
    mock_agent = MagicMock()
    mock_agent.propose.return_value = _mock_proposal()
    monkeypatch.setattr(api_main, "_get_cost_root_cause_agent", lambda: mock_agent)

    client = TestClient(api_main.app)
    response = client.get("/v1/cost-health")
    body = response.json()
    # sample seed では bigquery と cloud_run が同日 (days_ago=10) で spike
    assert body["cross_service_pattern"] is not None
    assert "deploy" in body["cross_service_pattern"]
    assert "bigquery" in body["cross_service_pattern"]
    assert "cloud_run" in body["cross_service_pattern"]


# ============================================================================
# 3) Agent クラッシュは 1 件 skip で全体死しない
# ============================================================================


def test_cost_health_skips_failed_agent_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.main import _COST_HEALTH_CACHE

    _COST_HEALTH_CACHE.clear()
    mock_agent = MagicMock()
    mock_agent.propose.side_effect = RuntimeError("LLM totally broken")
    monkeypatch.setattr(api_main, "_get_cost_root_cause_agent", lambda: mock_agent)

    client = TestClient(api_main.app)
    response = client.get("/v1/cost-health")
    assert response.status_code == 200
    # 全 agent クラッシュでも response は返る、entries は空 or 少
    body = response.json()
    assert isinstance(body["entries"], list)


# ============================================================================
# 4) disclaimer 常設
# ============================================================================


def test_cost_health_disclaimer_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main
    from apps.api.main import _COST_HEALTH_CACHE

    _COST_HEALTH_CACHE.clear()
    mock_agent = MagicMock()
    mock_agent.propose.return_value = _mock_proposal()
    monkeypatch.setattr(api_main, "_get_cost_root_cause_agent", lambda: mock_agent)

    client = TestClient(api_main.app)
    response = client.get("/v1/cost-health")
    body = response.json()
    assert "自動削減は実装されません" in body["disclaimer"]


# ============================================================================
# 5) estimated_total_savings_jpy = sum of all proposals
# ============================================================================


def test_cost_health_total_savings_sums_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    """各 anomaly の monthly_savings 合計が response.estimated_total_savings_jpy に。"""
    from apps.api import main as api_main
    from apps.api.main import _COST_HEALTH_CACHE

    _COST_HEALTH_CACHE.clear()
    mock_agent = MagicMock()
    mock_agent.propose.return_value = _mock_proposal(savings=25_000)
    monkeypatch.setattr(api_main, "_get_cost_root_cause_agent", lambda: mock_agent)

    client = TestClient(api_main.app)
    response = client.get("/v1/cost-health")
    body = response.json()
    n_entries = len(body["entries"])
    assert body["estimated_total_savings_jpy"] == 25_000 * n_entries


# ============================================================================
# 6) seed loader: 相対日付 (today 起点) で変換 (Reviewer Low #6)
# ============================================================================


def test_seed_loader_converts_days_ago_to_relative_dates() -> None:
    """seed の days_ago が today - N に変換され、過去 30 日範囲内に収まる。"""
    from agents.cost_hunter import load_sample_seed

    today = date(2026, 6, 1)
    observations = load_sample_seed(reference_date=today)
    assert len(observations) > 0

    # 全 observation が過去 30 日範囲内
    for obs in observations:
        delta = (today - obs.date).days
        assert 0 < delta <= 30


def test_seed_loader_returns_empty_when_file_missing(tmp_path) -> None:
    """ファイルがない場合は空 list を返す (graceful)。"""
    from agents.cost_hunter import load_sample_seed

    result = load_sample_seed(path=tmp_path / "missing.json")
    assert result == []
