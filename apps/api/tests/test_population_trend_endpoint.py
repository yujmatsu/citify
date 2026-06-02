"""GET /v1/cities/{code}/population-trend endpoint のユニットテスト (TASK-POPTREND)。"""

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


def _client_returning(rows: list[dict] | Exception) -> MagicMock:
    """query().result() が rows を返す (or 例外を投げる) BQ client mock。"""
    client = MagicMock()
    if isinstance(rows, Exception):
        client.query.side_effect = rows
    else:
        client.query.return_value.result.return_value = iter(rows)
    return client


def _setup(monkeypatch: pytest.MonkeyPatch, rows) -> TestClient:
    from apps.api import main as api_main

    api_main._POPTREND_CACHE.clear()
    monkeypatch.setattr(api_main, "_get_bq_client", lambda: _client_returning(rows))
    return TestClient(api_main.app)


# ============================================================================
# 1) census + projection を year 昇順で返し、境界年を算出
# ============================================================================


def test_returns_census_then_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"year": 2015, "population": 340000, "source": "census"},
        {"year": 2020, "population": 349000, "source": "census"},
        {"year": 2025, "population": 357971, "source": "projection"},
        {"year": 2070, "population": 341354, "source": "projection"},
    ]
    client = _setup(monkeypatch, rows)
    res = client.get("/v1/cities/13104/population-trend")
    assert res.status_code == 200
    body = res.json()
    assert [p["year"] for p in body["series"]] == [2015, 2020, 2025, 2070]
    assert body["latest_actual_year"] == 2020
    assert body["projection_start_year"] == 2025
    assert "総務省" in body["source_note"] and "国土交通省" in body["source_note"]


# ============================================================================
# 2) 同一年に census/projection があれば census 優先
# ============================================================================


def test_census_takes_priority_on_same_year(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"year": 2020, "population": 349000, "source": "census"},
        {"year": 2020, "population": 350500, "source": "projection"},  # 同年 projection は捨てる
    ]
    client = _setup(monkeypatch, rows)
    body = client.get("/v1/cities/13104/population-trend").json()
    assert len(body["series"]) == 1
    assert body["series"][0]["population"] == 349000
    assert body["series"][0]["source"] == "census"


# ============================================================================
# 3) データ未投入 (空) は空 series + 境界年 null
# ============================================================================


def test_empty_series_when_no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup(monkeypatch, [])
    body = client.get("/v1/cities/99999/population-trend").json()
    assert body["series"] == []
    assert body["latest_actual_year"] is None
    assert body["projection_start_year"] is None


# ============================================================================
# 4) BQ 失敗は graceful (空 series、500 にしない)
# ============================================================================


def test_graceful_on_bq_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup(monkeypatch, RuntimeError("BQ down"))
    res = client.get("/v1/cities/13104/population-trend")
    assert res.status_code == 200
    assert res.json()["series"] == []
