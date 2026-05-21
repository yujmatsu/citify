"""Pub/Sub envelope → BigQuery 永続化の薄いラッパ。

設計:
    - google-cloud-bigquery への import を遅延化 (テストで mock 注入可能)
    - 1 envelope = 1 BQ row (`insert_rows_json` で stream insert)
    - 失敗時は handler が例外を raise → subscriber が nack → 自動再試行
    - 重複は `message_id` カラムで downstream クエリ側 dedup (BQ MERGE は不要)

Trade-off:
    - 大量バッチ (>1000 件/秒) には streaming insert は不向きだが、ハッカソン規模では十分
    - schema 変更時は Terraform 経由で table を再作成
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pkg.pubsub import MessageEnvelope

logger = logging.getLogger(__name__)


class _BQClientProto(Protocol):
    """google.cloud.bigquery.Client の必要メソッドだけ抽出 (mock 用)。"""

    def insert_rows_json(self, table: str, rows: list[dict[str, Any]]) -> list[dict]: ...


# ============================================================================
# Converters (payload_type → BQ row dict)
# ============================================================================


def scored_speech_to_bq_row(envelope: MessageEnvelope) -> dict[str, Any]:
    """ScoredSpeech envelope → citify_curated.scored_speeches row。

    Args:
        envelope: MessageEnvelope (payload_type='ScoredSpeech' であること)

    Returns:
        BQ insert_rows_json に渡せる dict (datetime は ISO 文字列)
    """
    if envelope.payload_type != "ScoredSpeech":
        raise ValueError(f"expected payload_type='ScoredSpeech', got {envelope.payload_type!r}")

    p = envelope.payload
    score = p.get("score") or {}

    return {
        "speech_id": p["speech_id"],
        "user_id": p["user_id"],
        "municipality_code": p.get("municipality_code"),
        "title": p.get("title"),
        "summary": list(p.get("summary") or []),  # ARRAY<STRING>
        "detail_url": p.get("detail_url"),
        "meeting_date": p.get("meeting_date") or None,  # DATE (ISO 文字列 or None)
        "relevance_score": int(score.get("relevance_score", 0)),
        "score_topic": int(score.get("score_topic", 0)),
        "score_age": int(score.get("score_age", 0)),
        "score_geographic": int(score.get("score_geographic", 0)),
        "score_urgency": int(score.get("score_urgency", 0)),
        "matched_interests": list(score.get("matched_interests") or []),
        "reasoning": score.get("reasoning"),
        "speaker_position": p.get("speaker_position"),
        "name_of_meeting": p.get("name_of_meeting"),
        "tone": p.get("tone"),
        "message_id": None,  # subscriber が message.message_id を後で詰める
        "ingested_at": datetime.now(UTC).isoformat(),
    }


# ============================================================================
# Sink
# ============================================================================


EnvelopeConverter = Callable[[MessageEnvelope], dict[str, Any]]


class BQSink:
    """envelope → BQ row 変換 + insert を集約。

    Args:
        project_id: GCP project ID
        table_id: 完全修飾 table ID ('project.dataset.table' or 'dataset.table')
        converter: envelope → row dict (payload_type に応じて選ぶ)
        expected_payload_type: 期待する envelope.payload_type (これ以外は skip)
        client: テスト用 mock 注入
    """

    def __init__(
        self,
        project_id: str,
        table_id: str,
        converter: EnvelopeConverter,
        expected_payload_type: str,
        client: _BQClientProto | None = None,
    ) -> None:
        self.project_id = project_id
        self.table_id = table_id
        self.converter = converter
        self.expected_payload_type = expected_payload_type
        self._client = client

    def _ensure_client(self) -> _BQClientProto:
        if self._client is not None:
            return self._client
        from google.cloud import bigquery

        self._client = bigquery.Client(project=self.project_id)
        return self._client

    def insert_envelope(self, envelope: MessageEnvelope, message_id: str | None = None) -> None:
        """1 envelope を BQ row に変換して insert。

        Raises:
            ValueError: envelope.payload_type が expected と違う
            RuntimeError: BQ insert に失敗 (errors が返った)
        """
        if envelope.payload_type != self.expected_payload_type:
            raise ValueError(
                f"expected payload_type={self.expected_payload_type!r}, "
                f"got {envelope.payload_type!r}"
            )

        row = self.converter(envelope)
        if message_id is not None:
            row["message_id"] = message_id

        client = self._ensure_client()
        errors = client.insert_rows_json(self.table_id, [row])
        if errors:
            raise RuntimeError(f"BQ insert failed table={self.table_id} errors={errors}")

        logger.debug(
            "bq_sink.inserted table=%s payload_type=%s row_pk=%s",
            self.table_id,
            envelope.payload_type,
            row.get("speech_id") or row.get("id"),
        )

    def make_handler(self) -> Callable[[MessageEnvelope], None]:
        """PubSubSubscriber.run() に渡せる handler を生成。

        非対応 payload_type は skip (warning ログのみ)、対応 type は insert。
        """

        def handler(envelope: MessageEnvelope) -> None:
            if envelope.payload_type != self.expected_payload_type:
                logger.warning(
                    "bq_sink.skip_unexpected_payload_type expected=%s got=%s",
                    self.expected_payload_type,
                    envelope.payload_type,
                )
                return
            self.insert_envelope(envelope)
            logger.info(
                "bq_sink.handler_ok table=%s payload_type=%s",
                self.table_id,
                envelope.payload_type,
            )

        return handler
