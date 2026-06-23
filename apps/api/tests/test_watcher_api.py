"""Watcher (マイ街エージェント=街選びアナリスト) endpoint の test (TASK-WATCHER Slice 3.5)。

repo / agent を monkeypatch で fake に差し替えるため ADK / Firestore / Gemini は不要。
カバー範囲:
    GET  /v1/watcher/{uid}/analysis  : 200(分析+latest_run) / 空 / 403
    GET  /v1/watcher/{uid}/watchlist : 保存済 / null / 403
    PUT  /v1/watcher/{uid}/watchlist : 保存呼出 / 国会除外 / 国会のみ 400 / enum不正400 / 403
    POST /v1/watcher/{uid}/run       : agent.run 呼出 + analysis 返却 / watchlist無し 400 / 403
"""

from __future__ import annotations

import pytest
from agents.watcher.schema import (
    AgentRunLog,
    ToolCall,
    TownAnalysis,
    TownAssessment,
    WatcherResult,
    WatchInput,
    WatchVerdict,
)
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


def _analysis() -> TownAnalysis:
    return TownAnalysis(
        verdict=WatchVerdict(
            headline="今は小田原が子育て面でリード",
            reasoning="人口は両市微減だが小田原は子育て施設が多い",
            recommended_code="27100",
        ),
        town_assessments=[
            TownAssessment(municipality_code="13104", role="home", headline="基準の街"),
            TownAssessment(municipality_code="27100", role="candidate", headline="子育て充実"),
        ],
        watch_points=["住居コストの動向"],
    )


def _run_log(n: int = 2) -> AgentRunLog:
    return AgentRunLog(
        run_id="r1",
        user_id=UID,
        towns_checked=["13104", "27100"],
        tool_calls=[
            ToolCall(tool="compare_towns", args={"municipality_codes": ["13104", "27100"]})
        ],
        n_discoveries=n,
        status="ok",
    )


class _FakeRepo:
    """WatcherRepository の最小 fake (呼び出しを記録)。"""

    def __init__(self) -> None:
        self.analysis: TownAnalysis | None = None
        self.latest: AgentRunLog | None = None
        self.watchlist: WatchInput | None = None
        self.saved_watchlist: WatchInput | None = None

    def get_latest_analysis(self, user_id: str) -> TownAnalysis | None:
        return self.analysis

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
        self.town_names: dict[str, str] | None = None

    async def run(
        self, watch: WatchInput, town_names: dict[str, str] | None = None
    ) -> WatcherResult:
        self.ran_with = watch
        self.town_names = town_names
        return WatcherResult(analysis=_analysis(), run_log=_run_log())


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
# GET analysis
# ============================================================================


def test_get_analysis_returns_verdict_and_latest_run(
    client: TestClient, fake_repo: _FakeRepo
) -> None:
    fake_repo.analysis = _analysis()
    fake_repo.latest = _run_log()
    res = client.get(f"/v1/watcher/{UID}/analysis", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["analysis"]["verdict"]["headline"].startswith("今は小田原")
    assert [t["role"] for t in body["analysis"]["town_assessments"]] == ["home", "candidate"]
    # 自律証跡 (tool_calls) が latest_run に含まれる
    assert body["latest_run"]["tool_calls"][0]["tool"] == "compare_towns"


def test_get_analysis_empty_is_200(client: TestClient, fake_repo: _FakeRepo) -> None:
    res = client.get(f"/v1/watcher/{UID}/analysis", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert body["analysis"] is None
    assert body["latest_run"] is None


def test_get_analysis_forbidden_without_matching_header(
    client: TestClient, fake_repo: _FakeRepo
) -> None:
    assert client.get(f"/v1/watcher/{UID}/analysis").status_code == 403
    assert (
        client.get(f"/v1/watcher/{UID}/analysis", headers={"x-user-id": "other"}).status_code == 403
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


def test_put_watchlist_excludes_national_diet(client: TestClient, fake_repo: _FakeRepo) -> None:
    """国会(00000)は home/watched から除外。home が国会なら watched 先頭を昇格。"""
    payload = {
        "age_group": "40-49",
        "interests": ["子育て"],
        "home_municipality_code": "00000",  # 国会 → home にしない
        "watched_codes": ["13104", "00000", "27100"],
    }
    res = client.put(f"/v1/watcher/{UID}/watchlist", json=payload, headers=AUTH)
    assert res.status_code == 200
    saved = fake_repo.saved_watchlist
    assert saved is not None
    assert saved.home_municipality_code == "13104"  # watched 先頭が昇格
    assert "00000" not in saved.all_codes()


def test_put_watchlist_only_national_diet_400(client: TestClient, fake_repo: _FakeRepo) -> None:
    payload = {
        "age_group": "40-49",
        "interests": [],
        "home_municipality_code": "00000",
        "watched_codes": ["00000"],
    }
    res = client.put(f"/v1/watcher/{UID}/watchlist", json=payload, headers=AUTH)
    assert res.status_code == 400


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


def test_run_with_body_accepts_202_and_runs_in_background(
    client: TestClient, fake_repo: _FakeRepo, fake_agent: _FakeAgent
) -> None:
    """非同期化: POST /run は 202 を返し、agent.run は背景タスクで走る。

    TestClient は応答後に BackgroundTasks を同期実行するので ran_with を検証できる。
    """
    payload = {
        "age_group": "40-49",
        "interests": ["子育て"],
        "home_municipality_code": "13104",
        "watched_codes": ["27100"],
    }
    res = client.post(f"/v1/watcher/{UID}/run", json=payload, headers=AUTH)
    assert res.status_code == 202
    assert res.json()["status"] == "running"
    # body 指定時は watchlist 保存(同期) + 背景タスクで agent.run 実行
    assert fake_repo.saved_watchlist is not None
    assert fake_agent.ran_with is not None


def test_run_without_body_uses_saved_watchlist(
    client: TestClient, fake_repo: _FakeRepo, fake_agent: _FakeAgent
) -> None:
    fake_repo.watchlist = _watch()
    res = client.post(f"/v1/watcher/{UID}/run", headers=AUTH)
    assert res.status_code == 202
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


# ============================================================================
# GET action plan (TASK-ACTIONPLAN)
# ============================================================================


def test_get_plan_empty_is_200(client: TestClient, fake_repo: _FakeRepo) -> None:
    res = client.get(f"/v1/watcher/{UID}/plan", headers=AUTH)
    assert res.status_code == 200
    assert res.json()["plan"] is None


def test_get_plan_returns_action_plan(
    client: TestClient,
    fake_repo: _FakeRepo,
    fake_agent: _FakeAgent,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_repo.analysis = _analysis()  # recommended_code=27100 (candidate)
    fake_repo.latest = _run_log()

    async def _fake_checklist(rec, name, mode, model="x"):  # noqa: ANN001, ANN202, ARG001
        return ["朝の通勤帯の混雑を見る"]

    async def _fake_local(name, code, model="x"):  # noqa: ANN001, ANN202, ARG001
        return []

    monkeypatch.setattr("agents.watcher.action_plan.generate_visit_checklist", _fake_checklist)
    monkeypatch.setattr("agents.watcher.support.extract_local_support", _fake_local)
    fake_repo.watchlist = _watch()  # 現住所/世帯 (support 判定に必要)
    res = client.get(f"/v1/watcher/{UID}/plan", headers=AUTH)
    assert res.status_code == 200
    plan = res.json()["plan"]
    assert plan is not None
    assert plan["mode"] == "relocate"
    assert plan["recommended_code"] == "27100"
    assert plan["visit_checklist"] == ["朝の通勤帯の混雑を見る"]
    assert plan["decision_summary"].startswith("今は小田原")
    assert len(plan["official_links"]) >= 1  # 27100=大阪市 は seed あり
    # TASK-SUPPORT: 支援金マッチングが付与される
    assert plan["support"]["national"] is not None
    assert plan["support"]["national"]["eligibility"] in ("likely", "conditional", "unlikely")


def test_get_plan_forbidden_without_header(client: TestClient, fake_repo: _FakeRepo) -> None:
    assert client.get(f"/v1/watcher/{UID}/plan").status_code == 403
