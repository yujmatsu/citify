"""WatcherRepository の test (Firestore は mock、TASK-WATCHER Slice 2)。"""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.watcher.repo import WatcherRepository, _safe
from agents.watcher.schema import (
    AgentRunLog,
    ToolCall,
    TownAnalysis,
    TownAssessment,
    WatchInput,
    WatchVerdict,
)


def _watch() -> WatchInput:
    return WatchInput(
        user_id="demo-40-49",
        age_group="40-49",
        interests=["子育て"],
        home_municipality_code="13104",
        watched_codes=["27100"],
    )


def _analysis() -> TownAnalysis:
    return TownAnalysis(
        verdict=WatchVerdict(headline="今は小田原が優勢", reasoning="子育て施設が多い"),
        town_assessments=[
            TownAssessment(municipality_code="27100", role="candidate", headline="子育て充実"),
        ],
        watch_points=["住居コストの動向"],
    )


def _snap(exists: bool, data: dict | None = None) -> MagicMock:
    s = MagicMock()
    s.exists = exists
    s.to_dict.return_value = data
    return s


# ============================================================================
# _safe / watchlist
# ============================================================================


def test_safe_escapes_id() -> None:
    assert _safe("a/b:c") == "a_b_c"


def test_save_and_get_watchlist() -> None:
    client = MagicMock()
    repo = WatcherRepository(firestore_client=client)
    assert repo.save_watchlist(_watch()) is True

    client.collection.return_value.document.return_value.get.return_value = _snap(
        True, _watch().model_dump()
    )
    got = repo.get_watchlist("demo-40-49")
    assert got is not None
    assert got.home_municipality_code == "13104"


def test_get_watchlist_miss_returns_none() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _snap(False)
    assert WatcherRepository(firestore_client=client).get_watchlist("x") is None


def test_save_watchlist_graceful_on_failure() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.set.side_effect = RuntimeError("down")
    assert WatcherRepository(firestore_client=client).save_watchlist(_watch()) is False


# ============================================================================
# runs
# ============================================================================


def test_save_run_requires_run_id() -> None:
    client = MagicMock()
    repo = WatcherRepository(firestore_client=client)
    log = AgentRunLog(run_id="", user_id="u", tool_calls=[ToolCall(tool="search_speeches")])
    assert repo.save_run(log) is False  # run_id 空は skip
    log2 = AgentRunLog(run_id="r1", user_id="u")
    assert repo.save_run(log2) is True


def test_save_run_adds_created_at() -> None:
    """save_run の payload に created_at (latest 判定用の補助列) が付く。"""
    client = MagicMock()
    repo = WatcherRepository(firestore_client=client)
    assert repo.save_run(AgentRunLog(run_id="r1", user_id="u")) is True
    payload = client.collection.return_value.document.return_value.set.call_args.args[0]
    assert "created_at" in payload


def test_get_run_hit_and_miss() -> None:
    client = MagicMock()
    repo = WatcherRepository(firestore_client=client)
    # hit
    client.collection.return_value.document.return_value.get.return_value = _snap(
        True, AgentRunLog(run_id="r1", user_id="u", n_discoveries=2).model_dump()
    )
    got = repo.get_run("r1")
    assert got is not None and got.n_discoveries == 2
    # empty run_id → None (Firestore 非アクセス)
    assert repo.get_run("") is None
    # miss
    client.collection.return_value.document.return_value.get.return_value = _snap(False)
    assert repo.get_run("nope") is None


def test_get_latest_run_via_latest_analysis_doc() -> None:
    """最新 analysis ドキュメント (doc-id=user) の run_id を引いて get_run する経路。"""
    client = MagicMock()
    repo = WatcherRepository(firestore_client=client)

    # 1回目 get = analysis doc (run_id 入り)、2回目 get = run doc
    client.collection.return_value.document.return_value.get.side_effect = [
        _snap(True, {"run_id": "r-latest", "verdict": {"headline": "x"}}),
        _snap(True, AgentRunLog(run_id="r-latest", user_id="demo-40-49", status="ok").model_dump()),
    ]
    got = repo.get_latest_run("demo-40-49")
    assert got is not None and got.run_id == "r-latest"


def test_get_latest_run_no_analysis_returns_none() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _snap(False)
    assert WatcherRepository(firestore_client=client).get_latest_run("u") is None


# ============================================================================
# analyses
# ============================================================================


def test_save_analysis_sets_doc_keyed_by_user() -> None:
    client = MagicMock()
    repo = WatcherRepository(firestore_client=client)
    assert repo.save_analysis("demo-40-49", "r1", _analysis()) is True
    # doc id は user_id (最新のみ上書き、composite index 不要)
    client.collection.return_value.document.assert_called_with(_safe("demo-40-49"))
    payload = client.collection.return_value.document.return_value.set.call_args.args[0]
    assert payload["user_id"] == "demo-40-49"
    assert payload["run_id"] == "r1"
    assert "created_at" in payload
    assert payload["verdict"]["headline"] == "今は小田原が優勢"


def test_save_analysis_graceful_on_failure() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.set.side_effect = RuntimeError("down")
    assert WatcherRepository(firestore_client=client).save_analysis("u", "r1", _analysis()) is False


def test_get_latest_analysis_parses_doc() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _snap(
        True, _analysis().model_dump()
    )
    out = WatcherRepository(firestore_client=client).get_latest_analysis("demo-40-49")
    assert out is not None
    assert out.verdict.headline == "今は小田原が優勢"
    assert out.town_assessments[0].municipality_code == "27100"


def test_get_latest_analysis_none_when_empty() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _snap(False)
    assert WatcherRepository(firestore_client=client).get_latest_analysis("u") is None


def test_get_latest_analysis_graceful_on_failure() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.side_effect = RuntimeError("down")
    assert WatcherRepository(firestore_client=client).get_latest_analysis("u") is None
