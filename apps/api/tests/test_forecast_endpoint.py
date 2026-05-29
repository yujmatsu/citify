"""GET /v1/forecast endpoint のユニットテスト (Plan Z)。"""

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


def _mock_monthly_counts(values: list[float]) -> list:
    from agents.forecast.schema import MonthCount

    return [
        MonthCount(year_month=f"2025-{m:02d}", speech_count=v)
        for m, v in enumerate(values, start=1)
    ]


def _mock_narrative(source: str = "llm"):
    from agents.forecast.schema import ForecastNarrative

    return ForecastNarrative(
        headline="住居議題は緩やかに増加",
        reasoning="議論件数が安定的に増加傾向です。",
        source=source,  # type: ignore[arg-type]
    )


def _setup_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    monthly_counts=None,
    narrative=None,
    bq_exc: Exception | None = None,
) -> TestClient:
    from apps.api import main as api_main
    from apps.api.main import _FORECAST_CACHE

    _FORECAST_CACHE.clear()

    # narrator mock
    mock_narrator = MagicMock()
    mock_narrator.narrate.return_value = narrative or _mock_narrative()
    monkeypatch.setattr(api_main, "_get_forecast_narrator", lambda: mock_narrator)

    # BQ mock
    def _mock_bq(
        user_id: str,
        theme_interest: str,
        municipality_code: str | None,
        period_start: date,
        period_end: date,
    ):
        if bq_exc is not None:
            raise bq_exc
        return (
            monthly_counts
            if monthly_counts is not None
            else _mock_monthly_counts([1, 2, 3, 4, 5, 6, 7, 8])
        )

    monkeypatch.setattr(api_main, "_fetch_forecast_monthly_counts", _mock_bq)
    return TestClient(api_main.app)


# ============================================================================
# 1) 200 + series + narrative
# ============================================================================


def test_forecast_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get(
        "/v1/forecast",
        params={"theme_interest": "住居", "user_id": "demo", "history_months": 12},
    )
    assert response.status_code == 200
    body = response.json()
    assert "series" in body
    assert "narrative" in body
    assert body["series"]["trend_classification"] == "increasing"
    assert len(body["series"]["historical"]) == 8
    assert len(body["series"]["forecast"]) == 3


# ============================================================================
# 2) rule_based fallback 透過
# ============================================================================


def test_forecast_rule_based_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch, narrative=_mock_narrative(source="rule_based"))
    response = client.get(
        "/v1/forecast",
        params={"theme_interest": "住居", "user_id": "demo"},
    )
    assert response.status_code == 200
    assert response.json()["narrative"]["source"] == "rule_based"


# ============================================================================
# 3) BQ 失敗 → 500
# ============================================================================


def test_forecast_bq_failure_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch, bq_exc=RuntimeError("BQ table missing"))
    response = client.get(
        "/v1/forecast",
        params={"theme_interest": "住居", "user_id": "demo"},
    )
    assert response.status_code == 500


# ============================================================================
# 4) 不正な theme_interest → 422
# ============================================================================


def test_forecast_rejects_invalid_interest(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get(
        "/v1/forecast",
        params={"theme_interest": "存在しない軸", "user_id": "demo"},
    )
    assert response.status_code == 422


# ============================================================================
# 5) BQ query が集計行除外 + NULL date 除外 + interest allowlist を満たす
# ============================================================================


def test_forecast_bq_query_filters_aggregate_and_null_dates() -> None:
    from unittest.mock import patch

    from apps.api import main as api_main

    captured: list[str] = []

    def _capture(sql, job_config=None):  # noqa: ARG001
        captured.append(sql)
        result = MagicMock()
        result.result.return_value = []
        return result

    mock_bq = MagicMock()
    mock_bq.query.side_effect = _capture

    with patch.object(api_main, "_get_bq_client", return_value=mock_bq):
        api_main._fetch_forecast_monthly_counts(
            user_id="demo",
            theme_interest="住居",
            municipality_code="13104",
            period_start=date(2025, 1, 1),
            period_end=date(2026, 1, 1),
        )

    assert len(captured) == 1
    sql = captured[0]
    assert "municipality_code != '00000'" in sql
    assert "municipality_code NOT LIKE '%000'" in sql
    assert "meeting_date IS NOT NULL" in sql
    assert "FORMAT_DATE" in sql
    assert "GROUP BY year_month" in sql


def test_forecast_bq_rejects_invalid_interest() -> None:
    from apps.api import main as api_main

    with pytest.raises(ValueError, match="theme_interest not in 10-axis allowlist"):
        api_main._fetch_forecast_monthly_counts(
            user_id="demo",
            theme_interest="DROP TABLE",
            municipality_code=None,
            period_start=date(2025, 1, 1),
            period_end=date(2026, 1, 1),
        )


# ============================================================================
# 6) /v1/forecast の cache hit
# ============================================================================


def test_forecast_cache_hit_on_repeat_call(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    params = {"theme_interest": "住居", "user_id": "demo"}
    r1 = client.get("/v1/forecast", params=params)
    r2 = client.get("/v1/forecast", params=params)
    assert r1.json() == r2.json()
