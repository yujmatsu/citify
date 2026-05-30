"""agents/relevance/cache.py のテスト (Firestore はすべて mock、TASK-CACHE)。"""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.relevance.cache import (
    PROMPT_VERSION,
    RelevanceCacheRepository,
)
from agents.relevance.schema import PersonaRelevanceOutput


def _make_output(user_id: str, score: int = 75) -> PersonaRelevanceOutput:
    return PersonaRelevanceOutput(
        user_id=user_id,
        relevance_score=score,
        score_topic=20,
        score_age=20,
        score_geographic=20,
        score_urgency=15,
        matched_interests=["住居", "税"],
        reasoning="ペルソナ関心軸と speech の合致度が高い",
        contains_political_judgment=False,
    )


def _doc_dict(user_id: str, score: int = 75, prompt_version: str = PROMPT_VERSION) -> dict:
    return {
        "speech_id": "衆議院:221:第4号:60",
        "user_id": user_id,
        "relevance_output": _make_output(user_id, score).model_dump(),
        "prompt_version": prompt_version,
    }


def _make_snap(doc_id: str, exists: bool, data: dict | None = None) -> MagicMock:
    snap = MagicMock()
    snap.id = doc_id
    snap.exists = exists
    snap.to_dict.return_value = data
    return snap


# ============================================================================
# 1) get_cached: hit / miss
# ============================================================================


def test_get_cached_hit_returns_output() -> None:
    client = MagicMock()
    doc_id = "衆議院_221_第4号_60__demo-25-29"
    client.collection.return_value.document.return_value.get.return_value = _make_snap(
        doc_id, exists=True, data=_doc_dict("demo-25-29", score=80)
    )
    repo = RelevanceCacheRepository(firestore_client=client)

    out = repo.get_cached("衆議院:221:第4号:60", "demo-25-29")
    assert out is not None
    assert out.user_id == "demo-25-29"
    assert out.relevance_score == 80


def test_get_cached_miss_returns_none() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _make_snap(
        "x", exists=False
    )
    repo = RelevanceCacheRepository(firestore_client=client)
    assert repo.get_cached("speech-1", "demo-25-29") is None


# ============================================================================
# 2) batch_get: partial result (get_all mock)
# ============================================================================


def test_batch_get_returns_only_hits() -> None:
    client = MagicMock()
    # 3 persona 中 demo-18-24 / demo-30-39 が hit、demo-25-29 は miss
    snaps = [
        _make_snap("衆議院_221_第4号_60__demo-18-24", True, _doc_dict("demo-18-24", 60)),
        _make_snap("衆議院_221_第4号_60__demo-25-29", False, None),
        _make_snap("衆議院_221_第4号_60__demo-30-39", True, _doc_dict("demo-30-39", 70)),
    ]
    client.get_all.return_value = iter(snaps)
    repo = RelevanceCacheRepository(firestore_client=client)

    result = repo.batch_get("衆議院:221:第4号:60", ["demo-18-24", "demo-25-29", "demo-30-39"])
    assert set(result.keys()) == {"demo-18-24", "demo-30-39"}
    assert result["demo-18-24"].relevance_score == 60
    assert result["demo-30-39"].relevance_score == 70


def test_batch_get_empty_user_ids_returns_empty() -> None:
    client = MagicMock()
    repo = RelevanceCacheRepository(firestore_client=client)
    assert repo.batch_get("speech-1", []) == {}
    client.get_all.assert_not_called()


# ============================================================================
# 3) graceful failure (Firestore down) — save / get_cached
# ============================================================================


def test_save_graceful_on_firestore_failure() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.set.side_effect = RuntimeError(
        "Firestore down"
    )
    repo = RelevanceCacheRepository(firestore_client=client)
    assert repo.save("speech-1", "demo-25-29", _make_output("demo-25-29")) is False


def test_get_cached_graceful_on_firestore_failure() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.side_effect = RuntimeError(
        "Firestore down"
    )
    repo = RelevanceCacheRepository(firestore_client=client)
    assert repo.get_cached("speech-1", "demo-25-29") is None


# ============================================================================
# 4) doc_id エスケープ (`:` / `/` / `__` 含む speech_id でも衝突しない)
# ============================================================================


def test_make_doc_id_escapes_and_avoids_collision() -> None:
    # `:` と `/` は `_` にエスケープ
    assert (
        RelevanceCacheRepository._make_doc_id("衆議院:221:第4号:60", "demo-25-29")
        == "衆議院_221_第4号_60__demo-25-29"
    )
    assert RelevanceCacheRepository._make_doc_id("a/b", "u") == "a_b__u"

    # `__` を既に含む speech_id でも user_id は末尾区切りで区別できる
    id_a = RelevanceCacheRepository._make_doc_id("press__rss", "demo-18-24")
    id_b = RelevanceCacheRepository._make_doc_id("press__rss", "demo-25-29")
    assert id_a != id_b
    assert id_a.endswith("__demo-18-24")


# ============================================================================
# 5) TTL field が expires_at に cached_at + ttl_days で設定される
# ============================================================================


def test_save_sets_expires_at_with_ttl() -> None:
    client = MagicMock()
    captured: dict = {}
    client.collection.return_value.document.return_value.set.side_effect = lambda data: (
        captured.update(data)
    )
    repo = RelevanceCacheRepository(firestore_client=client, ttl_days=7)

    assert repo.save("speech-1", "demo-25-29", _make_output("demo-25-29")) is True
    assert "cached_at" in captured
    assert "expires_at" in captured
    delta = captured["expires_at"] - captured["cached_at"]
    assert abs(delta.total_seconds() - 7 * 86400) < 5
    assert captured["prompt_version"] == PROMPT_VERSION


# ============================================================================
# 6) prompt_version 不一致は miss 扱い (Reviewer Medium)
# ============================================================================


def test_get_cached_prompt_version_mismatch_is_miss() -> None:
    client = MagicMock()
    client.collection.return_value.document.return_value.get.return_value = _make_snap(
        "x", exists=True, data=_doc_dict("demo-25-29", prompt_version="v0.9-old")
    )
    repo = RelevanceCacheRepository(firestore_client=client, prompt_version="v1.0")
    # doc は存在するが prompt_version 不一致 → None (古い score を配信しない)
    assert repo.get_cached("衆議院:221:第4号:60", "demo-25-29") is None
