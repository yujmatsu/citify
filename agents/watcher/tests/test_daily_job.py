"""daily_job (P5 日次先回りJob) の test。repo/agent を mock し ADK/BQ/Firestore 不要。"""

from __future__ import annotations

import argparse

import pytest

from agents.watcher import daily_job
from agents.watcher.schema import AgentRunLog, WatcherResult, WatchInput


@pytest.mark.asyncio
async def test_daily_job_runs_all_watchlists(monkeypatch: pytest.MonkeyPatch) -> None:
    watchlists = [
        WatchInput(user_id="u1", age_group="40-49", home_municipality_code="11227"),
        WatchInput(user_id="u2", age_group="25-29", home_municipality_code="14206"),
    ]

    class FakeRepo:
        def list_all_watchlists(self) -> list[WatchInput]:
            return watchlists

    ran: list[str] = []

    class FakeAgent:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def run(
            self, w: WatchInput, town_names: dict[str, str] | None = None
        ) -> WatcherResult:
            ran.append(w.user_id)
            return WatcherResult(
                analysis=None, run_log=AgentRunLog(run_id="r", user_id=w.user_id, status="ok")
            )

    monkeypatch.setattr("agents.watcher.repo.WatcherRepository", FakeRepo)
    monkeypatch.setattr("agents.watcher.main.WatcherAgent", FakeAgent)
    monkeypatch.setattr(daily_job, "_load_municipality_names", lambda pid: {})

    rc = await daily_job._main(argparse.Namespace(project_id="citify-dev"))
    assert rc == 0
    assert ran == ["u1", "u2"]  # 全 watchlist を逐次実行


@pytest.mark.asyncio
async def test_daily_job_continues_on_user_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    watchlists = [
        WatchInput(user_id="bad", age_group="40-49", home_municipality_code="11227"),
        WatchInput(user_id="good", age_group="25-29", home_municipality_code="14206"),
    ]

    class FakeRepo:
        def list_all_watchlists(self) -> list[WatchInput]:
            return watchlists

    ran: list[str] = []

    class FakeAgent:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def run(
            self, w: WatchInput, town_names: dict[str, str] | None = None
        ) -> WatcherResult:
            if w.user_id == "bad":
                raise RuntimeError("agent boom")
            ran.append(w.user_id)
            return WatcherResult(
                analysis=None, run_log=AgentRunLog(run_id="r", user_id=w.user_id, status="ok")
            )

    monkeypatch.setattr("agents.watcher.repo.WatcherRepository", FakeRepo)
    monkeypatch.setattr("agents.watcher.main.WatcherAgent", FakeAgent)
    monkeypatch.setattr(daily_job, "_load_municipality_names", lambda pid: {})

    rc = await daily_job._main(argparse.Namespace(project_id="citify-dev"))
    assert rc == 0
    assert ran == ["good"]  # 1ユーザー失敗でも残りは続行
