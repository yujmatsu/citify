"""watcher tools の test (BQ は mock 注入、TASK-WATCHER Slice 1)。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.watcher import tools as wt


@pytest.fixture(autouse=True)
def _reset_factory():
    yield
    wt.set_bq_client_factory(None)


def _client_returning(rows: list[dict] | Exception) -> MagicMock:
    client = MagicMock()
    if isinstance(rows, Exception):
        client.query.side_effect = rows
    else:
        client.query.return_value.result.return_value = iter(rows)
    return client


# ============================================================================
# search_speeches
# ============================================================================


def test_search_speeches_maps_rows() -> None:
    rows = [
        {
            "speech_id": "sp-1",
            "title": "新保育補助",
            "summary": ["補助拡充"],
            "relevance_score": 82,
            "matched_interests": ["子育て"],
            "detail_url": "https://x/1",
            "meeting_date": "2026-05-20",
        }
    ]
    wt.set_bq_client_factory(lambda: _client_returning(rows))
    out = wt.search_speeches("11227", "demo-40-49", interest="子育て")
    assert len(out) == 1
    assert out[0]["speech_id"] == "sp-1"
    assert out[0]["matched_interests"] == ["子育て"]


def test_search_speeches_graceful_on_bq_failure() -> None:
    wt.set_bq_client_factory(lambda: _client_returning(RuntimeError("BQ down")))
    assert wt.search_speeches("11227", "demo-40-49") == []


# ============================================================================
# fetch_population_trend
# ============================================================================


def test_population_trend_computes_2070_change() -> None:
    rows = [
        {"year": 2020, "population": 100000, "source": "census"},
        {"year": 2025, "population": 99000, "source": "projection"},
        {"year": 2070, "population": 60000, "source": "projection"},
    ]
    wt.set_bq_client_factory(lambda: _client_returning(rows))
    out = wt.fetch_population_trend("11227")
    assert out["latest_actual_year"] == 2020
    # (60000-100000)/100000*100 = -40.0
    assert out["projection_2070_change_pct"] == -40.0
    assert len(out["series"]) == 3


def test_population_trend_graceful_on_failure() -> None:
    wt.set_bq_client_factory(lambda: _client_returning(RuntimeError("BQ down")))
    out = wt.fetch_population_trend("11227")
    assert out["series"] == []
    assert out["projection_2070_change_pct"] is None
