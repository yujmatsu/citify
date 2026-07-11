"""GET /v1/ops/health endpoint tests (Ops Crew)。"""

from __future__ import annotations

import sys
import types
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


def _fake_result():
    from agents.ops_crew.schema import (
        OpsAssessment,
        OpsCrewResult,
        OpsFinding,
        OpsRemediationProposal,
        OpsRunLog,
        OpsToolCall,
        OpsVerdict,
    )

    assessment = OpsAssessment(
        verdict=OpsVerdict(
            headline="スクレイパー要対応",
            reasoning="403 が多発",
            top_priority_domain="scraper_health",
            confidence="high",
            requires_human_review=True,
        ),
        findings=[
            OpsFinding(
                domain="scraper_health", headline="3 件失敗", severity="high", confidence="medium"
            )
        ],
        proposals=[
            OpsRemediationProposal(
                domain="scraper_health",
                action="user_agent_change",
                rationale="UA変更",
                source="rule_based",
            )
        ],
        critique_note="根拠は妥当",
    )
    return OpsCrewResult(
        assessment=assessment,
        run_log=OpsRunLog(
            run_id="abc",
            targets_checked=["scraper_health"],
            tool_calls=[OpsToolCall(tool="scraper.diagnose", args={"failure_id": "x"})],
            n_findings=1,
            status="ok",
        ),
    )


class _FakeCrew:
    async def run(self, **_: object):
        return _fake_result()


def _patch(monkeypatch: pytest.MonkeyPatch) -> object:
    from apps.api import main as api_main

    api_main._OPS_HEALTH_CACHE.clear()
    monkeypatch.setattr(api_main, "_get_ops_crew_agent", lambda: _FakeCrew())
    monkeypatch.setattr(api_main, "_ops_freshness_hours", lambda: 3.0)
    monkeypatch.delenv("OPS_ADMIN_TOKEN", raising=False)
    return api_main


def test_ops_health_200_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _patch(monkeypatch)
    client = TestClient(api_main.app)
    r = client.get("/v1/ops/health")
    assert r.status_code == 200
    body = r.json()
    assert body["assessment"]["verdict"]["requires_human_review"] is True
    assert body["assessment"]["verdict"]["top_priority_domain"] == "scraper_health"
    assert body["run_log"]["status"] == "ok"
    assert body["freshness_hours"] == 3.0
    assert body["assessment"]["proposals"][0]["requires_human_review"] is True


def test_ops_health_admin_token_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    api_main = _patch(monkeypatch)
    monkeypatch.setenv("OPS_ADMIN_TOKEN", "secret-xyz")
    client = TestClient(api_main.app)

    # トークン無し → 403
    assert client.get("/v1/ops/health").status_code == 403
    # 誤トークン → 403
    assert client.get("/v1/ops/health", headers={"x-admin-token": "wrong"}).status_code == 403
    # 正トークン → 200
    ok = client.get("/v1/ops/health", headers={"x-admin-token": "secret-xyz"})
    assert ok.status_code == 200
