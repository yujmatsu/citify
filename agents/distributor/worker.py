"""DistributorAgent の Pub/Sub worker (A-7)。

`citify-speech-scored` subscription から ScoredSpeech envelope を pull し、
ユーザー別にインメモリ累積した上で DistributorAgent.generate_feed() を呼び、
最新の `FeedSnapshot` を `citify-feed-snapshot` topic に publish する。

設計:
    - 1 ScoredSpeech 受信 → ユーザー別 buffer に追加 → 即 generate_feed() で再生成 → publish
    - インメモリ buffer (本ハッカソンスコープ、将来 Firestore に置換)
    - O(n²) MMR ranking だが、small batch なら問題ない
    - speech_id 重複は最新でマージ (同じ speech が異なる relevance score で再到達したら更新)

ローカル動作確認:
    python -m agents.distributor.worker \\
        --project-id citify-dev \\
        --input-subscription citify-speech-scored-sub \\
        --output-topic citify-feed-snapshot \\
        --min-relevance 50 \\
        --feed-size 10 \\
        --timeout-sec 120
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import OrderedDict
from datetime import UTC, date, datetime
from threading import Lock

from agents.relevance.schema import ScoredSpeech
from pkg.pubsub import MessageEnvelope, PubSubPublisher, PubSubSubscriber

from .main import (
    DEFAULT_FEED_SIZE,
    DEFAULT_MIN_RELEVANCE,
    DistributorAgent,
)
from .schema import FeedCandidate, FeedSnapshot

logger = logging.getLogger(__name__)

SOURCE = "distributor"

REQUIRED_KEYS = ("speech_id", "user_id", "title", "score")


def _scored_to_candidate(scored: ScoredSpeech) -> FeedCandidate:
    """ScoredSpeech → FeedCandidate 変換 (distributor.generate_feed() の入力型)。"""
    score = scored.score
    meeting_date_obj: date | None = None
    if scored.meeting_date:
        try:
            meeting_date_obj = date.fromisoformat(scored.meeting_date)
        except ValueError:
            meeting_date_obj = None

    return FeedCandidate(
        speech_id=scored.speech_id,
        title=scored.title or None,
        summary=scored.summary or None,
        tone=scored.tone,
        relevance_score=score.relevance_score,
        score_topic=score.score_topic,
        score_age=score.score_age,
        score_geographic=score.score_geographic,
        score_urgency=score.score_urgency,
        matched_interests=list(score.matched_interests),
        reasoning=score.reasoning,
        speaker_position=scored.speaker_position,
        municipality_code=scored.municipality_code,
        meeting_date=meeting_date_obj,
        meeting_url=scored.detail_url,
        name_of_meeting=scored.name_of_meeting,
    )


class _UserPool:
    """1 ユーザー分の ScoredSpeech プール (speech_id 重複排除)。

    OrderedDict で挿入順を保持しつつ、同一 speech_id の更新を可能に。
    Lock で multi-thread (Pub/Sub callback) に対応。
    """

    def __init__(self) -> None:
        self._items: OrderedDict[str, FeedCandidate] = OrderedDict()
        self._lock = Lock()

    def upsert(self, candidate: FeedCandidate) -> None:
        with self._lock:
            # 同 speech_id があれば削除してから追加 (LRU 風に最新を末尾に)
            self._items.pop(candidate.speech_id, None)
            self._items[candidate.speech_id] = candidate

    def snapshot(self) -> list[FeedCandidate]:
        with self._lock:
            return list(self._items.values())

    def size(self) -> int:
        return len(self._items)


def make_handler(
    agent: DistributorAgent,
    publisher: PubSubPublisher,
    output_topic: str,
    pools: dict[str, _UserPool],
):
    """ScoredSpeech 受信 → user pool 更新 → feed 再生成 → snapshot publish。"""

    def handler(envelope: MessageEnvelope) -> None:
        if envelope.payload_type != "ScoredSpeech":
            logger.warning(
                "worker.skip_non_scored_speech payload_type=%s source=%s",
                envelope.payload_type,
                envelope.source,
            )
            return

        missing = [k for k in REQUIRED_KEYS if k not in envelope.payload]
        if missing:
            raise ValueError(f"envelope.payload missing keys: {missing}")

        scored = ScoredSpeech.model_validate(envelope.payload)
        candidate = _scored_to_candidate(scored)

        # user pool 更新 (per user_id)
        user_pool = pools.setdefault(scored.user_id, _UserPool())
        user_pool.upsert(candidate)

        # 全候補で feed 再生成
        all_candidates = user_pool.snapshot()
        feed_items = agent.generate_feed(all_candidates)

        snapshot = FeedSnapshot(
            user_id=scored.user_id,
            generated_at=datetime.now(UTC),
            pool_size=len(all_candidates),
            items=feed_items,
        )
        out_env = MessageEnvelope.wrap(SOURCE, snapshot)
        attrs = {
            "user_id": scored.user_id,
            "pool_size": str(snapshot.pool_size),
            "feed_size": str(len(feed_items)),
        }
        publisher.publish_envelope(output_topic, out_env, attributes=attrs)

        # human-readable 要約 (debug)
        if feed_items:
            top = feed_items[0]
            logger.info(
                "worker.feed_published user=%s pool=%d feed=%d top_speech=%s top_score=%d "
                "top_title=%r",
                scored.user_id,
                snapshot.pool_size,
                len(feed_items),
                top.speech_id,
                top.relevance_score,
                top.title[:30] if top.title else "",
            )
        else:
            logger.info(
                "worker.feed_published user=%s pool=%d feed=0 (no items above min_relevance=%d)",
                scored.user_id,
                snapshot.pool_size,
                agent.min_relevance,
            )

    return handler


def run_worker(
    project_id: str,
    input_subscription: str,
    output_topic: str,
    min_relevance: int = DEFAULT_MIN_RELEVANCE,
    feed_size: int = DEFAULT_FEED_SIZE,
    timeout_sec: float | None = None,
) -> None:
    """worker 起動。"""
    agent = DistributorAgent(min_relevance=min_relevance, feed_size=feed_size)
    publisher = PubSubPublisher(project_id=project_id)
    subscriber = PubSubSubscriber(project_id=project_id)
    pools: dict[str, _UserPool] = {}

    handler = make_handler(agent, publisher, output_topic, pools)
    logger.info(
        "worker.start project=%s in_sub=%s out_topic=%s min_relevance=%d feed_size=%d timeout=%s",
        project_id,
        input_subscription,
        output_topic,
        min_relevance,
        feed_size,
        timeout_sec,
    )
    subscriber.run(subscription=input_subscription, handler=handler, timeout_sec=timeout_sec)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.distributor.worker",
        description="Distributor Pub/Sub worker (A-7)",
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--input-subscription", default="citify-speech-scored-sub")
    parser.add_argument("--output-topic", default="citify-feed-snapshot")
    parser.add_argument(
        "--min-relevance",
        type=int,
        default=DEFAULT_MIN_RELEVANCE,
        help="フィード表示閾値 (default 50)",
    )
    parser.add_argument(
        "--feed-size",
        type=int,
        default=DEFAULT_FEED_SIZE,
        help="1 ユーザーに返す item 数 (default 20)",
    )
    parser.add_argument("--timeout-sec", type=float, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    run_worker(
        project_id=args.project_id,
        input_subscription=args.input_subscription,
        output_topic=args.output_topic,
        min_relevance=args.min_relevance,
        feed_size=args.feed_size,
        timeout_sec=args.timeout_sec,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
