"""GET /v1/reasoning/explain endpoint tests (Plan PP)。"""

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


def _mock_explanation(source: str = "llm"):
    from agents.reasoner.schema import ReasoningExplanation

    return ReasoningExplanation(
        plain_summary="Agent は過去半年の月別議題数を分析し、安定した増加傾向を検出しました。",
        influencing_factors=["過去 6 か月の月別件数", "線形回帰の slope"],
        counterfactuals=["もし期間が短ければ信頼度は低くなります"],
        caveats=["線形外挿は季節性を無視します"],
        confidence="medium",
        source=source,  # type: ignore[arg-type]
    )


def _setup_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    explanation=None,
    explain_exc: Exception | None = None,
) -> TestClient:
    from apps.api import main as api_main

    mock_reasoner = MagicMock()
    if explain_exc is not None:
        mock_reasoner.explain.side_effect = explain_exc
    else:
        mock_reasoner.explain.return_value = explanation or _mock_explanation()
    monkeypatch.setattr(api_main, "_get_meta_reasoner", lambda: mock_reasoner)

    return TestClient(api_main.app)


# ============================================================================
# 1) 200 + 全フィールド構造
# ============================================================================


def test_reasoning_explain_200(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get(
        "/v1/reasoning/explain",
        params={
            "agent_name": "forecast",
            "raw_reasoning": "過去 6 か月で件数が増加",
            "agent_output_summary": "住居議題は増加傾向",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "plain_summary" in body
    assert "influencing_factors" in body
    assert "counterfactuals" in body
    assert "caveats" in body
    assert "confidence" in body
    assert body["source"] == "llm"


# ============================================================================
# 2) rule_based fallback 透過
# ============================================================================


def test_reasoning_explain_rule_based_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch, explanation=_mock_explanation(source="rule_based"))
    response = client.get(
        "/v1/reasoning/explain",
        params={
            "agent_name": "concierge",
            "raw_reasoning": "若者向け候補を提示",
            "agent_output_summary": "新宿区候補",  # Note: leak は agent 側で防御済前提
        },
    )
    assert response.status_code == 200
    assert response.json()["source"] == "rule_based"


# ============================================================================
# 3) 不正な agent_name → 422
# ============================================================================


def test_reasoning_explain_rejects_unknown_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get(
        "/v1/reasoning/explain",
        params={
            "agent_name": "unknown_agent",  # Literal 外
            "raw_reasoning": "...",
            "agent_output_summary": "...",
        },
    )
    assert response.status_code == 422


# ============================================================================
# 4) Agent.explain クラッシュ → 500
# ============================================================================


def test_reasoning_explain_500_on_agent_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch, explain_exc=RuntimeError("LLM totally broken"))
    response = client.get(
        "/v1/reasoning/explain",
        params={
            "agent_name": "forecast",
            "raw_reasoning": "...",
            "agent_output_summary": "...",
        },
    )
    assert response.status_code == 500


# ============================================================================
# 5) raw_reasoning 必須
# ============================================================================


def test_reasoning_explain_rejects_missing_raw_reasoning(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get(
        "/v1/reasoning/explain",
        params={"agent_name": "forecast", "agent_output_summary": "x"},
    )
    assert response.status_code == 422


# ============================================================================
# 6) persona_context は optional
# ============================================================================


def test_reasoning_explain_accepts_missing_persona(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get(
        "/v1/reasoning/explain",
        params={
            "agent_name": "translator",
            "raw_reasoning": "若者向けに平易化",
            "agent_output_summary": "casual トーンで 3 行",
        },
    )
    assert response.status_code == 200
