"""POST /v1/concierge endpoint のユニットテスト (Plan E Phase 3)。

テスト戦略:
    - FastAPI TestClient で endpoint を叩く
    - ConciergeAgent (`main._get_concierge_agent`) を MagicMock で差し替え
    - request body 検証 / response 構造 / エラー系を確認
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# google.cloud.firestore のスタブ (既存 test_reactions.py と同じ pattern)
@pytest.fixture(autouse=True)
def _stub_firestore_module() -> None:
    if "google.cloud.firestore" not in sys.modules:
        stub = types.ModuleType("google.cloud.firestore")
        stub.SERVER_TIMESTAMP = object()  # type: ignore[attr-defined]
        stub.Client = MagicMock()  # type: ignore[attr-defined]
        stub.Increment = MagicMock()  # type: ignore[attr-defined]
        sys.modules["google.cloud.firestore"] = stub


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient + ConciergeAgent mock 注入。"""
    # _get_concierge_agent を差し替え
    from agents.concierge.schema import (
        ConciergeResponse,
        MunicipalityCandidate,
        ToolCallLog,
    )

    from apps.api import main as api_main

    mock_agent = MagicMock()
    mock_agent.respond.return_value = ConciergeResponse(
        reply="新宿区がおすすめです。家賃中央値 6,000 万円、保育施設 80 件。",
        tool_calls=[
            ToolCallLog(
                name="search_municipalities",
                args={"age_group": "25-29", "interests": ["住居", "子育て"]},
                output_preview='[{"municipality_code":"13104","name":"新宿区","match_score":90}]',
                duration_ms=120,
            )
        ],
        candidates=[
            MunicipalityCandidate(
                municipality_code="13104",
                name="新宿区",
                prefecture="東京都",
                match_score=90.0,
                population_total=350000,
                matched_interests=["住居", "子育て"],
            )
        ],
        ethical_violations=[],
    )
    monkeypatch.setattr(api_main, "_get_concierge_agent", lambda: mock_agent)

    return TestClient(api_main.app)


# ============================================================================
# 正常系
# ============================================================================


def test_post_concierge_returns_reply_and_candidates(client: TestClient) -> None:
    """正常な request で reply + tool_calls + candidates が返る。"""
    payload = {
        "message": "26 歳、リモートワーク、子育て予定です",
        "persona": {
            "user_id": "demo-25-29",
            "age_group": "25-29",
            "interests": ["住居", "子育て"],
            "municipality_codes": ["13104"],
        },
    }
    response = client.post("/v1/concierge", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert "reply" in body
    assert "新宿区がおすすめ" in body["reply"]
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["name"] == "search_municipalities"
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["municipality_code"] == "13104"
    assert body["ethical_violations"] == []


def test_post_concierge_response_has_all_keys(client: TestClient) -> None:
    """response が ConciergeResponse の全 keys を含む。"""
    payload = {
        "message": "おすすめの街は?",
        "persona": {"user_id": "anon", "age_group": "25-29", "interests": ["住居"]},
    }
    response = client.post("/v1/concierge", json=payload)
    body = response.json()
    assert set(body.keys()) >= {"reply", "tool_calls", "candidates", "ethical_violations"}


# ============================================================================
# Request validation
# ============================================================================


def test_post_concierge_rejects_missing_message(client: TestClient) -> None:
    """message が欠けていたら 422。"""
    payload = {"persona": {"user_id": "anon", "age_group": "25-29"}}
    response = client.post("/v1/concierge", json=payload)
    assert response.status_code == 422


def test_post_concierge_rejects_empty_message(client: TestClient) -> None:
    """message が空文字なら 422 (min_length=1)。"""
    payload = {
        "message": "",
        "persona": {"user_id": "anon", "age_group": "25-29"},
    }
    response = client.post("/v1/concierge", json=payload)
    assert response.status_code == 422


def test_post_concierge_rejects_too_long_message(client: TestClient) -> None:
    """message が 2000 文字超なら 422 (max_length=2000)。"""
    payload = {
        "message": "x" * 2001,
        "persona": {"user_id": "anon", "age_group": "25-29"},
    }
    response = client.post("/v1/concierge", json=payload)
    assert response.status_code == 422


def test_post_concierge_accepts_minimal_persona(client: TestClient) -> None:
    """persona は全フィールド optional (default 動作)。"""
    payload = {
        "message": "おすすめの街教えて",
        "persona": {},  # default age_group=25-29, interests=[], 等
    }
    response = client.post("/v1/concierge", json=payload)
    assert response.status_code == 200


# ============================================================================
# Agent 内部エラー時の handling
# ============================================================================


def test_post_concierge_500_on_agent_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """ConciergeAgent.respond() が例外を投げたら 500。"""
    from apps.api import main as api_main

    mock_agent = MagicMock()
    mock_agent.respond.side_effect = RuntimeError("Gemini API failure")
    monkeypatch.setattr(api_main, "_get_concierge_agent", lambda: mock_agent)

    client_instance = TestClient(api_main.app)
    payload = {
        "message": "test",
        "persona": {"user_id": "anon", "age_group": "25-29"},
    }
    response = client_instance.post("/v1/concierge", json=payload)
    assert response.status_code == 500
    assert "Concierge failed" in response.json()["detail"]


# ============================================================================
# 既存 endpoint regression (health 等が壊れていない)
# ============================================================================


def test_health_endpoint_still_works(client: TestClient) -> None:
    """Plan E の endpoint 追加で既存 /health が壊れていないこと。"""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_version_endpoint_still_works(client: TestClient) -> None:
    """Plan E の endpoint 追加で既存 /version が壊れていないこと。"""
    response = client.get("/version")
    assert response.status_code == 200
    body = response.json()
    assert "version" in body
    assert "git_sha" in body


# ============================================================================
# 倫理 violation の透過
# ============================================================================


def test_post_concierge_includes_ethical_violations_in_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ConciergeAgent が ethical_violations を返したら response に含める。"""
    from agents.concierge.schema import ConciergeResponse

    from apps.api import main as api_main

    mock_agent = MagicMock()
    mock_agent.respond.return_value = ConciergeResponse(
        reply="申し訳ありません、応答内容が倫理ガイドラインに抵触したため再考します。",
        tool_calls=[],
        candidates=[],
        ethical_violations=["絶対に.{0,3}(賛成|反対)"],
    )
    monkeypatch.setattr(api_main, "_get_concierge_agent", lambda: mock_agent)

    client_instance = TestClient(api_main.app)
    payload = {
        "message": "おすすめの街教えて",
        "persona": {"user_id": "anon", "age_group": "25-29"},
    }
    response = client_instance.post("/v1/concierge", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["ethical_violations"] == ["絶対に.{0,3}(賛成|反対)"]
    assert "倫理ガイドライン" in body["reply"]


# ============================================================================
# GET /v1/concierge/history/{user_id} (Plan L+LL)
# ============================================================================


def _make_mock_memory_with_records(records_list: list[dict]) -> MagicMock:
    """ConversationMemory mock。recall_recent が指定 record を返す。"""
    from datetime import UTC, datetime

    from agents.concierge.memory import HistoryRecord

    records = [
        HistoryRecord(
            doc_id=r["doc_id"],
            user_id=r["user_id"],
            timestamp=r.get("timestamp", datetime(2026, 5, 29, 12, 0, tzinfo=UTC)),
            message=r["message"],
            reply=r.get("reply", ""),
            short_summary=r.get("short_summary", ""),
            candidates_codes=r.get("candidates_codes", []),
            matched_interests=r.get("matched_interests", []),
        )
        for r in records_list
    ]
    mock_memory = MagicMock()
    mock_memory.recall_recent.return_value = records
    return mock_memory


def test_get_history_returns_records_with_correct_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """正しい x-user-id header で 200 + items 取得。"""
    from apps.api import main as api_main

    mock_memory = _make_mock_memory_with_records(
        [
            {
                "doc_id": "user1__2026-05-29",
                "user_id": "user1",
                "message": "保育園充実な街は?",
                "short_summary": "新宿区がおすすめ...",
                "candidates_codes": ["13104"],
                "matched_interests": ["住居", "子育て"],
            }
        ]
    )
    monkeypatch.setattr(api_main, "_get_concierge_memory", lambda: mock_memory)

    client_instance = TestClient(api_main.app)
    response = client_instance.get(
        "/v1/concierge/history/user1",
        headers={"x-user-id": "user1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "user1"
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["message"] == "保育園充実な街は?"
    assert body["items"][0]["matched_interests"] == ["住居", "子育て"]


def test_get_history_403_on_user_id_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """x-user-id と path user_id 不一致なら 403 (認可)。"""
    from apps.api import main as api_main

    mock_memory = _make_mock_memory_with_records([])
    monkeypatch.setattr(api_main, "_get_concierge_memory", lambda: mock_memory)

    client_instance = TestClient(api_main.app)
    response = client_instance.get(
        "/v1/concierge/history/user1",
        headers={"x-user-id": "attacker"},
    )
    assert response.status_code == 403
    assert "demo 認可" in response.json()["detail"]


def test_get_history_403_on_missing_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """x-user-id header 自体がない場合も 403。"""
    from apps.api import main as api_main

    mock_memory = _make_mock_memory_with_records([])
    monkeypatch.setattr(api_main, "_get_concierge_memory", lambda: mock_memory)

    client_instance = TestClient(api_main.app)
    response = client_instance.get("/v1/concierge/history/user1")  # no x-user-id
    assert response.status_code == 403


def test_get_history_respects_limit_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """?limit=5 で recall_recent(limit=5) が呼ばれる。"""
    from apps.api import main as api_main

    mock_memory = _make_mock_memory_with_records([])
    monkeypatch.setattr(api_main, "_get_concierge_memory", lambda: mock_memory)

    client_instance = TestClient(api_main.app)
    response = client_instance.get(
        "/v1/concierge/history/user1?limit=5",
        headers={"x-user-id": "user1"},
    )
    assert response.status_code == 200
    mock_memory.recall_recent.assert_called_with(user_id="user1", limit=5)


def test_get_history_500_on_memory_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """ConversationMemory が例外を投げたら 500。"""
    from apps.api import main as api_main

    mock_memory = MagicMock()
    mock_memory.recall_recent.side_effect = RuntimeError("Firestore down")
    monkeypatch.setattr(api_main, "_get_concierge_memory", lambda: mock_memory)

    client_instance = TestClient(api_main.app)
    response = client_instance.get(
        "/v1/concierge/history/user1",
        headers={"x-user-id": "user1"},
    )
    assert response.status_code == 500
    assert "history fetch failed" in response.json()["detail"]
