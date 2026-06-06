"""WatcherRepository の test (Firestore は mock、TASK-WATCHER Slice 2)。"""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.watcher.repo import WatcherRepository, _safe
from agents.watcher.schema import AgentRunLog, Discovery, ToolCall, WatchInput


def _watch() -> WatchInput:
    return WatchInput(
        user_id="demo-40-49",
        age_group="40-49",
        interests=["子育て"],
        home_municipality_code="13104",
        watched_codes=["27100"],
    )


def _disc(code="27100") -> Discovery:
    return Discovery(
        municipality_code=code,
        title="保育補助",
        summary=["拡充"],
        why_surfaced="子育て関心に合致",
        significance="high",
        source_speech_ids=["sp-1"],
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


def test_get_latest_run_via_newest_discovery() -> None:
    """最新 discovery の run_id を引いて get_run する経路。"""
    client = MagicMock()
    repo = WatcherRepository(firestore_client=client)

    disc_doc = MagicMock()
    disc_doc.to_dict.return_value = {"run_id": "r-latest"}
    (
        client.collection.return_value.where.return_value.order_by.return_value.limit.return_value.stream.return_value
    ) = [disc_doc]
    client.collection.return_value.document.return_value.get.return_value = _snap(
        True, AgentRunLog(run_id="r-latest", user_id="demo-40-49", status="ok").model_dump()
    )
    got = repo.get_latest_run("demo-40-49")
    assert got is not None and got.run_id == "r-latest"


def test_get_latest_run_no_discovery_returns_none() -> None:
    client = MagicMock()
    (
        client.collection.return_value.where.return_value.order_by.return_value.limit.return_value.stream.return_value
    ) = []
    assert WatcherRepository(firestore_client=client).get_latest_run("u") is None


# ============================================================================
# discoveries
# ============================================================================


def test_save_discoveries_batch() -> None:
    client = MagicMock()
    batch = MagicMock()
    client.batch.return_value = batch
    repo = WatcherRepository(firestore_client=client)
    n = repo.save_discoveries("demo-40-49", "r1", [_disc(), _disc("13104")])
    assert n == 2
    assert batch.set.call_count == 2
    batch.commit.assert_called_once()


def test_save_discoveries_empty_returns_zero() -> None:
    client = MagicMock()
    assert WatcherRepository(firestore_client=client).save_discoveries("u", "r1", []) == 0


def test_save_discoveries_graceful_on_failure() -> None:
    client = MagicMock()
    client.batch.side_effect = RuntimeError("down")
    assert WatcherRepository(firestore_client=client).save_discoveries("u", "r1", [_disc()]) == 0


def test_list_discoveries_parses_docs() -> None:
    client = MagicMock()
    doc = MagicMock()
    doc.to_dict.return_value = _disc().model_dump()
    (
        client.collection.return_value.where.return_value.order_by.return_value.limit.return_value.stream.return_value
    ) = [doc]
    out = WatcherRepository(firestore_client=client).list_discoveries("demo-40-49")
    assert len(out) == 1
    assert out[0].municipality_code == "27100"


def test_list_discoveries_graceful_on_failure() -> None:
    client = MagicMock()
    client.collection.return_value.where.side_effect = RuntimeError("down")
    assert WatcherRepository(firestore_client=client).list_discoveries("u") == []
