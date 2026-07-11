"""Pub/Sub envelope → BigQuery 永続化の薄いラッパ。

書き込みモード (2種):
    1. **stream insert (既定)**: `insert_rows_json` で 1 envelope = 1 row を追記。
       Pub/Sub は at-least-once なので再配信時は行が重複する。重複は読み取り側の
       view (`scored_speeches_latest`, PARTITION BY speech_id,user_id ORDER BY ingested_at)
       で最新のみ抽出して吸収する。
    2. **MERGE upsert (opt-in, `merge_keys` 指定時)**: `(speech_id,user_id)` を PK に
       MERGE し、再配信で行を増やさず更新する = **冪等**。これにより基底テーブルに
       重複が溜まらず、view の全走査コストも消える (W5/W6 対策)。
       ※ streaming buffer との相性・実 BQ 検証が必要なため、worker では環境変数
       `CITIFY_BQ_MERGE` での opt-in とし、既定は stream insert のまま (本番挙動不変)。

設計:
    - google-cloud-bigquery への import を遅延化 (テストで mock 注入可能)
    - 失敗時は handler が例外を raise → subscriber が nack → 自動再試行
    - schema 変更時は Terraform 経由で table を再作成
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Protocol

from pkg.pubsub import MessageEnvelope, PermanentMessageError

logger = logging.getLogger(__name__)

# scored_speeches の列 → BQ 型 (MERGE の query parameter 型付けに使用)。
SCORED_SPEECH_COLUMN_TYPES: dict[str, str] = {
    "speech_id": "STRING",
    "user_id": "STRING",
    "municipality_code": "STRING",
    "title": "STRING",
    "summary": "ARRAY<STRING>",
    "detail_url": "STRING",
    "meeting_date": "DATE",
    "relevance_score": "INT64",
    "score_topic": "INT64",
    "score_age": "INT64",
    "score_geographic": "INT64",
    "score_urgency": "INT64",
    "matched_interests": "ARRAY<STRING>",
    "reasoning": "STRING",
    "speaker_position": "STRING",
    "name_of_meeting": "STRING",
    "tone": "STRING",
    "message_id": "STRING",
    "ingested_at": "TIMESTAMP",
}


class _BQClientProto(Protocol):
    """google.cloud.bigquery.Client の必要メソッドだけ抽出 (mock 用)。"""

    def insert_rows_json(self, table: str, rows: list[dict[str, Any]]) -> list[dict]: ...

    def query(self, query: str, *args: Any, **kwargs: Any) -> Any: ...


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

    # M1: 必須キー欠落は再送しても復旧しない (poison-pill) → PermanentMessageError で ack-drop。
    # 直接 p["..."] だと KeyError → nack → DLQ 未設定購読で無限再送ストームになる。
    speech_id = p.get("speech_id")
    user_id = p.get("user_id")
    if not speech_id or not user_id:
        raise PermanentMessageError(
            f"ScoredSpeech payload missing required keys "
            f"(speech_id={speech_id!r}, user_id={user_id!r})"
        )

    return {
        "speech_id": speech_id,
        "user_id": user_id,
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
# MERGE upsert helpers (冪等書き込み)
# ============================================================================


def build_merge_sql(table_id: str, columns: list[str], merge_keys: tuple[str, ...]) -> str:
    """1 row を merge_keys を PK に upsert する MERGE 文を組む。

    列値は named query parameter (`@col`) で渡す (SQL インジェクション安全)。
    """
    non_keys = [c for c in columns if c not in merge_keys]
    using = ", ".join(f"@{c} AS {c}" for c in columns)
    on = " AND ".join(f"T.{k} = S.{k}" for k in merge_keys)
    update_set = (
        ", ".join(f"{c} = S.{c}" for c in non_keys) or f"{merge_keys[0]} = S.{merge_keys[0]}"
    )
    insert_cols = ", ".join(columns)
    insert_vals = ", ".join(f"S.{c}" for c in columns)
    return (
        f"MERGE `{table_id}` T "  # noqa: S608 (table_id は env 由来、列名は row.keys() 由来)
        f"USING (SELECT {using}) S ON {on} "
        f"WHEN MATCHED THEN UPDATE SET {update_set} "
        f"WHEN NOT MATCHED THEN INSERT ({insert_cols}) VALUES ({insert_vals})"
    )


def build_merge_params(row: dict[str, Any], column_types: dict[str, str]) -> list[Any]:
    """row + 列型定義から BigQuery query parameter のリストを組む。

    ARRAY<T> は ArrayQueryParameter、DATE/TIMESTAMP は ISO 文字列を date/datetime に
    パースしてから ScalarQueryParameter に渡す (None はそのまま NULL)。
    """
    from google.cloud import bigquery

    params: list[Any] = []
    for col, value in row.items():
        bq_type = column_types.get(col, "STRING")
        if bq_type.startswith("ARRAY<"):
            elem = bq_type[len("ARRAY<") : -1] or "STRING"
            params.append(bigquery.ArrayQueryParameter(col, elem, list(value or [])))
            continue
        coerced = value
        if value is not None and bq_type == "DATE" and isinstance(value, str):
            coerced = date.fromisoformat(value)
        elif value is not None and bq_type == "TIMESTAMP" and isinstance(value, str):
            coerced = datetime.fromisoformat(value)
        params.append(bigquery.ScalarQueryParameter(col, bq_type, coerced))
    return params


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
        merge_keys: tuple[str, ...] | None = None,
        column_types: dict[str, str] | None = None,
    ) -> None:
        self.project_id = project_id
        self.table_id = table_id
        self.converter = converter
        self.expected_payload_type = expected_payload_type
        self._client = client
        # merge_keys + column_types が両方あれば MERGE upsert (冪等)。無ければ stream insert。
        self.merge_keys = merge_keys
        self.column_types = column_types

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
        if self.merge_keys and self.column_types:
            self._merge_row(client, row)
        else:
            errors = client.insert_rows_json(self.table_id, [row])
            if errors:
                raise RuntimeError(f"BQ insert failed table={self.table_id} errors={errors}")

        logger.debug(
            "bq_sink.persisted mode=%s table=%s payload_type=%s row_pk=%s",
            "merge" if self.merge_keys else "stream",
            self.table_id,
            envelope.payload_type,
            row.get("speech_id") or row.get("id"),
        )

    def _merge_row(self, client: _BQClientProto, row: dict[str, Any]) -> None:
        """1 row を `merge_keys` を PK に MERGE upsert (冪等)。型は column_types 由来。"""
        from google.cloud import bigquery

        assert self.merge_keys is not None and self.column_types is not None
        sql = build_merge_sql(self.table_id, list(row.keys()), self.merge_keys)
        params = build_merge_params(row, self.column_types)
        job = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params))
        job.result()  # 完了待ち (エラーは例外 → nack → 再試行)

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
