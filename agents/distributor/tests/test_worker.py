"""agents/distributor/worker.py のテスト (Pub/Sub は mock、ranking は実体)。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agents.distributor.main import DistributorAgent
from agents.distributor.schema import FeedSnapshot
from agents.distributor.worker import (
    SOURCE,
    _scored_to_candidate,
    _UserPool,
    make_handler,
)
from agents.relevance.schema import RelevanceOutput, ScoredSpeech
from pkg.pubsub import MessageEnvelope, PubSubPublisher

# ============================================================================
# Helpers
# ============================================================================


def _make_scored(
    speech_id: str = "prefokayama:177:4:0",
    user_id: str = "u-1",
    relevance_score: int = 70,
    matched: list[str] | None = None,
    speaker_position: str | None = "知事",
    meeting_date: str | None = "2025-03-05",
    title: str = "サンプル翻訳タイトル",
    municipality_code: str = "33000",
) -> ScoredSpeech:
    return ScoredSpeech(
        speech_id=speech_id,
        user_id=user_id,
        municipality_code=municipality_code,
        title=title,
        summary=["L1", "L2", "L3"],
        detail_url="https://example.com/m/1",
        meeting_date=meeting_date,
        score=RelevanceOutput(
            relevance_score=relevance_score,
            score_topic=20,
            score_age=15,
            score_geographic=20,
            score_urgency=15,
            matched_interests=matched or [],
            reasoning="test",
            contains_political_judgment=False,
        ),
        speaker_position=speaker_position,
        name_of_meeting="令和7年2月定例会 03月05日-04号",
        tone="casual",
    )


def _make_envelope(scored: ScoredSpeech) -> MessageEnvelope:
    return MessageEnvelope.wrap("relevance", scored)


def _make_mock_publisher() -> tuple[PubSubPublisher, MagicMock]:
    client = MagicMock()
    client.topic_path.side_effect = lambda p, t: f"projects/{p}/topics/{t}"
    future = MagicMock()
    future.result.return_value = "msg-feed-1"
    client.publish.return_value = future
    return PubSubPublisher(project_id="citify-dev", client=client), client


# ============================================================================
# _scored_to_candidate
# ============================================================================


def test_scored_to_candidate_maps_fields():
    scored = _make_scored(matched=["住居", "税"])
    cand = _scored_to_candidate(scored)

    assert cand.speech_id == "prefokayama:177:4:0"
    assert cand.title == "サンプル翻訳タイトル"
    assert cand.summary == ["L1", "L2", "L3"]
    assert cand.tone == "casual"
    assert cand.relevance_score == 70
    assert cand.matched_interests == ["住居", "税"]
    assert cand.speaker_position == "知事"
    assert cand.municipality_code == "33000"
    assert cand.meeting_url == "https://example.com/m/1"
    # meeting_date を date 型に変換
    from datetime import date

    assert cand.meeting_date == date(2025, 3, 5)


def test_scored_to_candidate_handles_invalid_date():
    scored = _make_scored(meeting_date="not-a-date")
    cand = _scored_to_candidate(scored)
    assert cand.meeting_date is None


def test_scored_to_candidate_handles_none_date():
    scored = _make_scored(meeting_date=None)
    cand = _scored_to_candidate(scored)
    assert cand.meeting_date is None


# ============================================================================
# _UserPool (upsert + dedupe + snapshot)
# ============================================================================


def test_user_pool_upsert_dedupes_by_speech_id():
    pool = _UserPool()
    pool.upsert(_scored_to_candidate(_make_scored(speech_id="a", relevance_score=60)))
    pool.upsert(_scored_to_candidate(_make_scored(speech_id="b", relevance_score=70)))
    # 同じ speech_id を高い score で再投入
    pool.upsert(_scored_to_candidate(_make_scored(speech_id="a", relevance_score=80)))

    snap = pool.snapshot()
    assert pool.size() == 2  # speech_id 重複は dedupe
    by_id = {c.speech_id: c for c in snap}
    assert by_id["a"].relevance_score == 80  # 最新で上書き


def test_user_pool_snapshot_preserves_latest_order():
    pool = _UserPool()
    pool.upsert(_scored_to_candidate(_make_scored(speech_id="a")))
    pool.upsert(_scored_to_candidate(_make_scored(speech_id="b")))
    pool.upsert(_scored_to_candidate(_make_scored(speech_id="a")))  # update
    ids = [c.speech_id for c in pool.snapshot()]
    # 更新された a が末尾 (OrderedDict pop+set のため)
    assert ids == ["b", "a"]


# ============================================================================
# make_handler (ScoredSpeech → FeedSnapshot publish)
# ============================================================================


def test_handler_publishes_feed_snapshot():
    agent = DistributorAgent(min_relevance=50, feed_size=10)
    pub, client = _make_mock_publisher()
    pools: dict = {}
    handler = make_handler(agent, pub, "citify-feed-snapshot", pools)

    handler(_make_envelope(_make_scored(speech_id="a", relevance_score=80)))

    # publish 検証
    client.publish.assert_called_once()
    args, kwargs = client.publish.call_args
    assert args[0] == "projects/citify-dev/topics/citify-feed-snapshot"
    assert kwargs["user_id"] == "u-1"
    assert kwargs["source"] == SOURCE
    assert kwargs["pool_size"] == "1"
    assert kwargs["feed_size"] == "1"

    payload = json.loads(args[1].decode("utf-8"))
    assert payload["payload_type"] == "FeedSnapshot"
    snap = payload["payload"]
    assert snap["user_id"] == "u-1"
    assert snap["pool_size"] == 1
    assert len(snap["items"]) == 1
    assert snap["items"][0]["speech_id"] == "a"
    assert snap["items"][0]["final_rank"] == 1


def test_handler_filters_below_min_relevance():
    """min_relevance 未満は feed_items に含まれない (pool には残る)。"""
    agent = DistributorAgent(min_relevance=50, feed_size=10)
    pub, client = _make_mock_publisher()
    pools: dict = {}
    handler = make_handler(agent, pub, "out", pools)

    handler(_make_envelope(_make_scored(speech_id="a", relevance_score=30)))

    payload = json.loads(client.publish.call_args[0][1].decode("utf-8"))
    snap = payload["payload"]
    assert snap["pool_size"] == 1  # pool には入った
    assert snap["items"] == []  # でも feed_items は空


def test_handler_accumulates_across_messages():
    """複数 ScoredSpeech を受け取ると pool が累積、feed が再生成される。"""
    agent = DistributorAgent(min_relevance=50, feed_size=10)
    pub, client = _make_mock_publisher()
    pools: dict = {}
    handler = make_handler(agent, pub, "out", pools)

    handler(
        _make_envelope(_make_scored(speech_id="a", relevance_score=60, speaker_position="議長"))
    )
    handler(
        _make_envelope(_make_scored(speech_id="b", relevance_score=80, speaker_position="知事"))
    )
    handler(
        _make_envelope(_make_scored(speech_id="c", relevance_score=70, speaker_position="部長"))
    )

    assert client.publish.call_count == 3
    last_payload = json.loads(client.publish.call_args[0][1].decode("utf-8"))
    snap = last_payload["payload"]
    assert snap["pool_size"] == 3
    assert len(snap["items"]) == 3
    # 最高スコア (b=80) が rank=1
    assert snap["items"][0]["speech_id"] == "b"


def test_handler_per_user_pools_are_isolated():
    """異なる user_id のメッセージは独立した pool で処理される。"""
    agent = DistributorAgent(min_relevance=50, feed_size=10)
    pub, client = _make_mock_publisher()
    pools: dict = {}
    handler = make_handler(agent, pub, "out", pools)

    handler(_make_envelope(_make_scored(speech_id="a", user_id="u-1", relevance_score=70)))
    handler(_make_envelope(_make_scored(speech_id="b", user_id="u-2", relevance_score=80)))

    # 2 つの user pool が独立
    assert pools["u-1"].size() == 1
    assert pools["u-2"].size() == 1
    # 最後の publish は u-2 のもの (pool_size=1)
    last_payload = json.loads(client.publish.call_args[0][1].decode("utf-8"))
    assert last_payload["payload"]["user_id"] == "u-2"
    assert last_payload["payload"]["pool_size"] == 1


def test_handler_skips_non_scored_speech():
    agent = DistributorAgent()
    pub, client = _make_mock_publisher()
    handler = make_handler(agent, pub, "out", {})

    env = MessageEnvelope(
        schema_version="v1",
        source="other",
        payload_type="TranslatedSpeech",  # 期待しない型
        payload={"foo": "bar"},
    )
    handler(env)
    client.publish.assert_not_called()


def test_handler_raises_on_missing_required_keys():
    agent = DistributorAgent()
    pub, _ = _make_mock_publisher()
    handler = make_handler(agent, pub, "out", {})

    env = MessageEnvelope(
        schema_version="v1",
        source="relevance",
        payload_type="ScoredSpeech",
        payload={"speech_id": "x"},  # user_id / title / score 欠落
    )
    with pytest.raises(ValueError, match="missing"):
        handler(env)


# ============================================================================
# FeedSnapshot Pydantic
# ============================================================================


def test_feed_snapshot_round_trip():
    """FeedSnapshot を JSON シリアライズ→デシリアライズで復元できる。"""
    from datetime import UTC, datetime

    snap = FeedSnapshot(
        user_id="u-1",
        generated_at=datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC),
        pool_size=3,
        items=[],
    )
    data = snap.model_dump_json()
    restored = FeedSnapshot.model_validate_json(data)
    assert restored.user_id == "u-1"
    assert restored.pool_size == 3
