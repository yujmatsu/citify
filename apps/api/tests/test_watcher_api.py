"""Watcher (マイ街エージェント) endpoint のユニットテスト (TASK-WATCHER Slice 3)。

repo / agent を monkeypatch で fake に差し替えるため ADK / Firestore / Gemini は不要。
カバー範囲:
    GET  /v1/watcher/{uid}/discoveries : 200(発見+latest_run) / 空 / 403
    GET  /v1/watcher/{uid}/watchlist   : 保存済 / null / 403
    PUT  /v1/watcher/{uid}/watchlist   : 保存呼出 / enum 不正 400 / 403
    POST /v1/watcher/{uid}/run         : agent.run 呼出 + persist / watchlist 無し 400 / 403
"""

from __future__ import annotations

import pytest
from agents.watcher.schema import AgentRunLog, Discovery, ToolCall, WatcherResult, WatchInput
from fastapi.testclient import TestClient

UID = "demo-40-49"
AUTH = {"x-user-id": UID}


def _watch() -> WatchInput:
    return WatchInput(
        user_id=UID,
        age_group="40-49",
        interests=["子育て"],
        home_municipality_code="13104",
        watched_codes=["27100"],
    )


def _disc() -> Discovery:
    return Discovery(
        municipality_code="27100",
        title="保育補助の拡充",
        summary=["来年度から拡充"],
        why_surfaced="子育て関心 × あなたの気になる街",
        significance="high",
        source_speech_ids=["sp-1"],
    )


def _run_log(n: int = 1) -> AgentRunLog:
    return AgentRunLog(
        run_id="r1",
        user_id=UID,
        towns_checked=["13104", "27100"],
        tool_calls=[ToolCall(tool="search_speeches", args={"municipality_code": "27100"})],
        n_discoveries=n,
        status="ok",
    )


class _FakeRepo:
    """WatcherRepository の最小 fake (呼び出しを記録)。"""

    def __init__(self) -> None:
        self.discoveries: list[Discovery] = []
        self.latest: AgentRunLog | None = None
        self.watchlist: WatchInput | None = None
        self.saved_watchlist: WatchInput | None = None

    def list_discoveries(self, user_id: str, limit: int = 20) -> list[Discovery]:
        return self.discoveries

    def get_latest_run(self, user_id: str) -> AgentRunLog | None:
        return self.latest

    def get_watchlist(self, user_id: str) -> WatchInput | None:
        return self.watchlist

    def save_watchlist(self, watch: WatchInput) -> bool:
        self.saved_watchlist = watch
        return True


class _FakeAgent:
    """WatcherAgent の fake (run を非同期で返す、ADK 不要)。"""

    def __init__(self) -> None:
        self.ran_with: WatchInput | None = None

    async def run(self, watch: WatchInput) -> WatcherResult:
        self.ran_with = watch
        return WatcherResult(discoveries=[_disc()], run_log=_run_log())


@pytest.fixture()
def fake_repo(monkeypatch: pytest.MonkeyPatch) -> _FakeRepo:
    from apps.api import main

    repo = _FakeRepo()
    monkeypatch.setattr(main, "_watcher_repo_cache", repo)
    return repo


@pytest.fixture()
def fake_agent(monkeypatch: pytest.MonkeyPatch) -> _FakeAgent:
    from apps.api import main

    agent = _FakeAgent()
    monkeypatch.setattr(main, "_watcher_agent_cache", agent)
    return agent


@pytest.fixture()
def client() -> TestClient:
    from apps.api import main

    return TestClient(main.app)


# ============================================================================
# GET discoveries
# ============================================================================


def test_get_discoveries_returns_items_and_latest_run(
    client: TestClient, fake_repo: _FakeRepo
) -> None:
    fake_repo.discoveries = [_disc()]
    fake_repo.latest = _run_log()
    res = client.get(f"/v1/watcher/{UID}/discoveries", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert body["discoveries"][0]["why_surfaced"]
    # 自律証跡 (tool_calls) が latest_run に含まれる
    assert body["latest_run"]["tool_calls"][0]["tool"] == "search_speeches"


def test_get_discoveries_empty_is_200(client: TestClient, fake_repo: _FakeRepo) -> None:
    res = client.get(f"/v1/watcher/{UID}/discoveries", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["latest_run"] is None


def test_get_discoveries_forbidden_without_matching_header(
    client: TestClient, fake_repo: _FakeRepo
) -> None:
    assert client.get(f"/v1/watcher/{UID}/discoveries").status_code == 403
    assert (
        client.get(f"/v1/watcher/{UID}/discoveries", headers={"x-user-id": "other"}).status_code
        == 403
    )


# ============================================================================
# GET / PUT watchlist
# ============================================================================


def test_get_watchlist_hit_and_null(client: TestClient, fake_repo: _FakeRepo) -> None:
    assert client.get(f"/v1/watcher/{UID}/watchlist", headers=AUTH).json() is None
    fake_repo.watchlist = _watch()
    body = client.get(f"/v1/watcher/{UID}/watchlist", headers=AUTH).json()
    assert body["home_municipality_code"] == "13104"


def test_put_watchlist_saves(client: TestClient, fake_repo: _FakeRepo) -> None:
    payload = {
        "age_group": "40-49",
        "interests": ["子育て"],
        "home_municipality_code": "13104",
        "watched_codes": ["27100"],
    }
    res = client.put(f"/v1/watcher/{UID}/watchlist", json=payload, headers=AUTH)
    assert res.status_code == 200
    assert fake_repo.saved_watchlist is not None
    assert fake_repo.saved_watchlist.home_municipality_code == "13104"


def test_put_watchlist_invalid_age_group_400(client: TestClient, fake_repo: _FakeRepo) -> None:
    payload = {
        "age_group": "999",  # enum 外 → WatchInput 構築で ValidationError
        "interests": [],
        "home_municipality_code": "13104",
        "watched_codes": [],
    }
    res = client.put(f"/v1/watcher/{UID}/watchlist", json=payload, headers=AUTH)
    assert res.status_code == 400


def test_put_watchlist_forbidden(client: TestClient, fake_repo: _FakeRepo) -> None:
    payload = {"age_group": "40-49", "home_municipality_code": "13104", "watched_codes": []}
    res = client.put(f"/v1/watcher/{UID}/watchlist", json=payload, headers={"x-user-id": "x"})
    assert res.status_code == 403


# ============================================================================
# POST run
# ============================================================================


def test_run_with_body_invokes_agent_and_saves(
    client: TestClient, fake_repo: _FakeRepo, fake_agent: _FakeAgent
) -> None:
    payload = {
        "age_group": "40-49",
        "interests": ["子育て"],
        "home_municipality_code": "13104",
        "watched_codes": ["27100"],
    }
    res = client.post(f"/v1/watcher/{UID}/run", json=payload, headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["run_log"]["tool_calls"][0]["tool"] == "search_speeches"
    assert len(body["discoveries"]) == 1
    # body 指定時は watchlist も保存される
    assert fake_repo.saved_watchlist is not None
    assert fake_agent.ran_with is not None


def test_run_without_body_uses_saved_watchlist(
    client: TestClient, fake_repo: _FakeRepo, fake_agent: _FakeAgent
) -> None:
    fake_repo.watchlist = _watch()
    res = client.post(f"/v1/watcher/{UID}/run", headers=AUTH)
    assert res.status_code == 200
    assert fake_agent.ran_with is not None
    assert fake_agent.ran_with.home_municipality_code == "13104"


def test_run_without_body_and_no_watchlist_400(
    client: TestClient, fake_repo: _FakeRepo, fake_agent: _FakeAgent
) -> None:
    res = client.post(f"/v1/watcher/{UID}/run", headers=AUTH)
    assert res.status_code == 400


def test_run_forbidden(client: TestClient, fake_repo: _FakeRepo, fake_agent: _FakeAgent) -> None:
    res = client.post(f"/v1/watcher/{UID}/run", headers={"x-user-id": "x"})
    assert res.status_code == 403
