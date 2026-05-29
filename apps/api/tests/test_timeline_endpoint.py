"""GET /v1/timeline endpoint のユニットテスト (Plan N)。

テスト戦略:
    - TimelineAgent (`_get_timeline_agent`) を MagicMock で差し替え
    - BQ candidate fetch (`_fetch_timeline_candidates`) を MagicMock で差し替え
    - 200 / 422 / 500 graceful / SQL フィルタ検証 / interest allowlist
"""

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


def _mock_narrative(source: str = "llm", n_events: int = 5):
    """TimelineNarrative mock (Pydantic instance)。"""
    from agents.timeline.schema import TimelineEvent, TimelineNarrative

    events = [
        TimelineEvent(
            event_date=date(2026, 3, i + 1),
            municipality_code="13104",
            municipality_name="新宿区",
            headline=f"見出し {i}",
            detail=f"詳細 {i}",
            source_speech_id=f"muni:council:s:o_{i}",
            importance=70,
        )
        for i in range(n_events)
    ]
    return TimelineNarrative(
        theme_label="住居",
        period_start=date(2026, 2, 1),
        period_end=date(2026, 5, 1),
        overall_summary="住居問題は段階的に議論されました。",
        events=events,
        source=source,  # type: ignore[arg-type]
    )


def _mock_candidates(n: int = 5):
    """CandidateSpeech mock list。"""
    from agents.timeline.schema import CandidateSpeech

    return [
        CandidateSpeech(
            speech_id=f"muni:council:s:o_{i}",
            title=f"タイトル {i}",
            summary_first_line=f"要約 {i}",
            meeting_date=date(2026, 3, i + 1),
            municipality_code="13104",
            municipality_name="新宿区",
            speaker_position="議員",
            matched_interests=["住居"],
            relevance_score=80 - i,
        )
        for i in range(n)
    ]


def _setup_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    narrative=None,
    candidates=None,
    bq_exc: Exception | None = None,
    agent_exc: Exception | None = None,
) -> TestClient:
    """endpoint 依存を全 mock 化。"""
    from apps.api import main as api_main
    from apps.api.main import _TIMELINE_CACHE

    _TIMELINE_CACHE.clear()

    # agent mock
    mock_agent = MagicMock()
    if agent_exc is not None:
        mock_agent.narrate.side_effect = agent_exc
    else:
        mock_agent.narrate.return_value = narrative or _mock_narrative()
    monkeypatch.setattr(api_main, "_get_timeline_agent", lambda: mock_agent)

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
        return candidates if candidates is not None else _mock_candidates()

    monkeypatch.setattr(api_main, "_fetch_timeline_candidates", _mock_bq)
    return TestClient(api_main.app)


# ============================================================================
# 1) 200 + narrative + candidate_count
# ============================================================================


def test_timeline_returns_200_with_narrative(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get(
        "/v1/timeline",
        params={
            "theme_interest": "住居",
            "user_id": "demo",
            "municipality_code": "13104",
            "days": 90,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "narrative" in body
    assert body["narrative"]["theme_label"] == "住居"
    assert len(body["narrative"]["events"]) == 5
    assert body["narrative"]["source"] == "llm"
    assert body["candidate_count"] == 5


# ============================================================================
# 2) Agent が rule_based を返したら 200 で透過 (LLM 失敗 graceful)
# ============================================================================


def test_timeline_rule_based_fallback_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = _mock_narrative(source="rule_based")
    client = _setup_endpoint(monkeypatch, narrative=fallback)
    response = client.get(
        "/v1/timeline",
        params={"theme_interest": "住居", "user_id": "demo"},
    )
    assert response.status_code == 200
    assert response.json()["narrative"]["source"] == "rule_based"


# ============================================================================
# 3) BQ 失敗 → 500 graceful
# ============================================================================


def test_timeline_bq_failure_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch, bq_exc=RuntimeError("BQ table not found"))
    response = client.get(
        "/v1/timeline",
        params={"theme_interest": "住居", "user_id": "demo"},
    )
    assert response.status_code == 500
    assert "BQ timeline query failed" in response.json()["detail"]


# ============================================================================
# 4) 不正な theme_interest → 422 (Pydantic validation)
# ============================================================================


def test_timeline_rejects_invalid_theme_interest(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get(
        "/v1/timeline",
        params={"theme_interest": "存在しない軸", "user_id": "demo"},
    )
    assert response.status_code == 422


# ============================================================================
# 5) theme_interest 必須 → 422
# ============================================================================


def test_timeline_rejects_missing_theme_interest(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get("/v1/timeline", params={"user_id": "demo"})
    assert response.status_code == 422


# ============================================================================
# 6) BQ query が集計行 (XX000 / 00000) を除外する (Reviewer Critical で確立した pattern)
# ============================================================================


def test_timeline_bq_query_filters_aggregate_rows() -> None:
    """_fetch_timeline_candidates の SQL に集計行除外が含まれることを直接検証。"""
    from unittest.mock import patch

    from apps.api import main as api_main

    captured_sqls: list[str] = []

    def _capture_query(sql, job_config=None):  # noqa: ARG001
        captured_sqls.append(sql)
        result = MagicMock()
        result.result.return_value = []
        return result

    mock_bq = MagicMock()
    mock_bq.query.side_effect = _capture_query

    with patch.object(api_main, "_get_bq_client", return_value=mock_bq):
        api_main._fetch_timeline_candidates(
            user_id="demo",
            theme_interest="住居",
            municipality_code="13104",
            period_start=date(2026, 2, 1),
            period_end=date(2026, 5, 1),
        )

    assert len(captured_sqls) == 1
    sql = captured_sqls[0]
    assert "municipality_code != '00000'" in sql
    assert "municipality_code NOT LIKE '%000'" in sql
    assert "ORDER BY meeting_date ASC" in sql
    assert "LIMIT 30" in sql
    # Reviewer Critical #1: speaker 列が SELECT に含まれない
    assert "speaker_position" in sql
    # speaker (実名) が単独で SELECT に登場しないこと
    # (speaker_position と区別、'  speaker,' のような独立列パターンで確認)
    assert "\n          speaker," not in sql
    assert "SELECT speaker," not in sql


# ============================================================================
# 7) interest allowlist guard
# ============================================================================


def test_timeline_bq_rejects_invalid_interest() -> None:
    """theme_interest が 10 軸 allowlist 外なら ValueError。"""
    from apps.api import main as api_main

    with pytest.raises(ValueError, match="theme_interest not in 10-axis allowlist"):
        api_main._fetch_timeline_candidates(
            user_id="demo",
            theme_interest="DROP TABLE",
            municipality_code=None,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 5, 1),
        )


# ============================================================================
# 8) BQ query が user_id / interest / muni / 日付を param 化
# ============================================================================


def test_timeline_bq_query_uses_parameterized_inputs() -> None:
    """SQL injection 防止: ScalarQueryParameter で param 化されている。"""
    from unittest.mock import patch

    from apps.api import main as api_main

    captured_params: list = []

    def _capture_query(sql, job_config=None):  # noqa: ARG001
        if job_config:
            captured_params.append(job_config.query_parameters)
        result = MagicMock()
        result.result.return_value = []
        return result

    mock_bq = MagicMock()
    mock_bq.query.side_effect = _capture_query

    with patch.object(api_main, "_get_bq_client", return_value=mock_bq):
        api_main._fetch_timeline_candidates(
            user_id="demo",
            theme_interest="住居",
            municipality_code="13104",
            period_start=date(2026, 2, 1),
            period_end=date(2026, 5, 1),
        )

    assert len(captured_params) == 1
    param_names = {p.name for p in captured_params[0]}
    assert param_names == {"user_id", "start_date", "end_date", "interest", "muni"}
