"""① concierge の本物 ADK 親子経路 (arespond / AdkConciergeRunner) のテスト。

google.adk はこのサンドボックスで import 不可のため fake モジュールを注入し、
Runner.run_async に固定 event ストリームを差し込んで検証する
(実 ADK Runner の I/O は本番 smoke で検証、watcher と同じ規約)。
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from agents.concierge.main import ConciergeAgent
from agents.concierge.schema import ConciergeRequest, UserPersonaInput


def _make_request(message: str = "26歳、子育て予定") -> ConciergeRequest:
    return ConciergeRequest(
        message=message,
        persona=UserPersonaInput(
            user_id="demo-25-29",
            age_group="25-29",
            interests=["住居", "子育て"],
            municipality_codes=["13104"],
        ),
    )


# --------------------------------------------------------------------------- arespond


async def test_arespond_delegates_to_adk_runner_and_finalizes() -> None:
    runner = AsyncMock()
    runner.run.return_value = {
        "reply": "岡山市と札幌市がおすすめです",
        "tool_calls": [
            {"name": "search_municipalities", "args": {}, "output": "ok", "duration_ms": 5}
        ],
        "candidates": [],
    }
    agent = ConciergeAgent(adk_runner=runner)
    resp = await agent.arespond(_make_request())

    runner.run.assert_awaited_once()
    assert resp.reply == "岡山市と札幌市がおすすめです"
    assert len(resp.tool_calls) == 1 and resp.tool_calls[0].name == "search_municipalities"
    assert resp.ethical_violations == []


async def test_arespond_applies_ethics_gate() -> None:
    runner = AsyncMock()
    runner.run.return_value = {
        "reply": "この候補に投票を推奨します",
        "tool_calls": [],
        "candidates": [],
    }
    agent = ConciergeAgent(adk_runner=runner)
    resp = await agent.arespond(_make_request())
    assert resp.ethical_violations  # 禁止語検出
    assert "投票を推奨" not in resp.reply  # 中立文言に差し替え


async def test_arespond_raises_when_no_adk_runner() -> None:
    agent = ConciergeAgent()  # adk_runner 未注入
    with pytest.raises(NotImplementedError):
        await agent.arespond(_make_request())


# --------------------------------------------------------------------------- AdkConciergeRunner


def _part(*, fc: Any = None, fr: Any = None, text: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(function_call=fc, function_response=fr, text=text)


def _event(parts: list[Any], *, final: bool = False) -> SimpleNamespace:
    content = SimpleNamespace(parts=parts)
    return SimpleNamespace(content=content, is_final_response=lambda: final)


def _install_fake_adk(monkeypatch: pytest.MonkeyPatch, events: list[Any]) -> None:
    """google.adk / .sessions / google.genai.types を fake 注入し、run_async に events を流す。"""

    class _FakeRunner:
        def __init__(self, agent: Any, app_name: str, session_service: Any) -> None:
            self._events = events

        async def run_async(self, **_: Any):
            for e in self._events:
                yield e

    class _FakeSS:
        async def create_session(self, **_: Any) -> None:
            return None

    adk_mod = types.ModuleType("google.adk")
    adk_mod.Runner = _FakeRunner  # type: ignore[attr-defined]
    sessions_mod = types.ModuleType("google.adk.sessions")
    sessions_mod.InMemorySessionService = _FakeSS  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google.adk", adk_mod)
    monkeypatch.setitem(sys.modules, "google.adk.sessions", sessions_mod)

    # google.genai.types に Content/Part を用意 (conftest stub は薄いので補う)
    genai_types = sys.modules.get("google.genai.types") or types.ModuleType("google.genai.types")
    genai_types.Content = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    genai_types.Part = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google.genai.types", genai_types)


async def test_adk_runner_extracts_reply_toolcalls_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agents.concierge.adk_runner import AdkConciergeRunner

    events = [
        _event([_part(fc=SimpleNamespace(name="search_municipalities", args={"q": "子育て"}))]),
        _event(
            [
                _part(
                    fr=SimpleNamespace(
                        name="search_municipalities",
                        response={"result": [{"municipality_code": "33100", "name": "岡山市"}]},
                    )
                )
            ]
        ),
        _event([_part(text="岡山市がおすすめです")], final=True),
    ]
    _install_fake_adk(monkeypatch, events)

    # as_agent() が実 ADK Agent を作らないよう fake concierge を注入
    fake_concierge = SimpleNamespace(as_agent=lambda: object())
    runner = AdkConciergeRunner(project_id="citify-dev", adk_concierge=fake_concierge)
    result = await runner.run(_make_request(), persona_desc="- 年代: 25-29")

    assert result["reply"] == "岡山市がおすすめです"
    assert [tc["name"] for tc in result["tool_calls"]] == ["search_municipalities"]
    assert result["candidates"] == [{"municipality_code": "33100", "name": "岡山市"}]


async def test_adk_runner_result_flows_through_arespond(monkeypatch: pytest.MonkeyPatch) -> None:
    """AdkConciergeRunner → ConciergeAgent.arespond の一気通貫 (candidates が正規化される)。"""
    from agents.concierge.adk_runner import AdkConciergeRunner

    events = [
        _event(
            [
                _part(
                    fr=SimpleNamespace(
                        name="search_municipalities",
                        response={
                            "result": [
                                {
                                    "municipality_code": "33100",
                                    "name": "岡山市",
                                    "prefecture": "岡山県",
                                    "match_score": 88.0,
                                    "matched_interests": ["子育て"],
                                }
                            ]
                        },
                    )
                )
            ]
        ),
        _event([_part(text="岡山市が合いそうです")], final=True),
    ]
    _install_fake_adk(monkeypatch, events)
    fake_concierge = SimpleNamespace(as_agent=lambda: object())
    agent = ConciergeAgent(
        adk_runner=AdkConciergeRunner(project_id="citify-dev", adk_concierge=fake_concierge)
    )
    resp = await agent.arespond(_make_request())
    assert resp.reply == "岡山市が合いそうです"
    assert len(resp.candidates) == 1 and resp.candidates[0].municipality_code == "33100"
