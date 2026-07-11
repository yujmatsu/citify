"""BQ sink worker CLI: 1 つの Pub/Sub subscription を pull → BQ に投入する loop。

現在対応 sink:
    - scored_speeches: ScoredSpeech envelope → citify_curated.scored_speeches

使用例:
    python -m pkg.bq_sink_runner \\
        --project-id citify-dev \\
        --sink scored_speeches \\
        --subscription citify-speech-scored-sub \\
        --table citify-dev.citify_curated.scored_speeches \\
        --timeout-sec 120
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from pkg.bq_sink import (
    SCORED_SPEECH_COLUMN_TYPES,
    BQSink,
    scored_speech_to_bq_row,
)
from pkg.pubsub import PubSubSubscriber

logger = logging.getLogger(__name__)

# sink 名 → (converter, expected_payload_type, default_table_id, merge_keys, column_types)
SINKS: dict[str, tuple] = {
    "scored_speeches": (
        scored_speech_to_bq_row,
        "ScoredSpeech",
        "citify_curated.scored_speeches",
        ("speech_id", "user_id"),
        SCORED_SPEECH_COLUMN_TYPES,
    ),
}


def _merge_enabled() -> bool:
    """CITIFY_BQ_MERGE=1/true/yes で MERGE upsert (冪等) を有効化。既定は stream insert。

    ※ 実 BQ での 1 バッチ smoke 検証後に本番で有効化すること (streaming buffer 相性のため)。
    """
    return os.getenv("CITIFY_BQ_MERGE", "").lower() in ("1", "true", "yes")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pkg.bq_sink_runner",
        description="BQ sink worker: subscribe to Pub/Sub topic and insert to BQ",
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--sink",
        required=True,
        choices=list(SINKS.keys()),
        help="どの sink (table 種別) を実行するか",
    )
    parser.add_argument(
        "--subscription",
        required=True,
        help="入力 Pub/Sub subscription 名 (例: citify-speech-scored-sub)",
    )
    parser.add_argument(
        "--table",
        default=None,
        help="完全修飾 table ID (省略時は sink の default を使用)",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=None,
        help="N 秒後に停止 (None で永続実行)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    converter, expected_payload_type, default_table, merge_keys, column_types = SINKS[args.sink]
    table_id = args.table or default_table
    use_merge = _merge_enabled()

    sink = BQSink(
        project_id=args.project_id,
        table_id=table_id,
        converter=converter,
        expected_payload_type=expected_payload_type,
        merge_keys=merge_keys if use_merge else None,
        column_types=column_types if use_merge else None,
    )
    subscriber = PubSubSubscriber(project_id=args.project_id)

    logger.info(
        "bq_sink_runner.start sink=%s subscription=%s table=%s timeout=%s mode=%s",
        args.sink,
        args.subscription,
        table_id,
        args.timeout_sec,
        "merge" if use_merge else "stream",
    )
    subscriber.run(
        subscription=args.subscription,
        handler=sink.make_handler(),
        timeout_sec=args.timeout_sec,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
