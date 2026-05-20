"""SpeechRecord を BigQuery `citify_raw.kokkai_speeches` テーブルに投入するローダー。

設計方針:
    - 100 件単位の streaming insert (insert_rows_json) — 1 万件程度までは十分高速
    - 大量データ (10 万件+) になったら load job (CSV/JSON file via GCS) に切替予定
    - errors が返ったら例外 raise (静かな失敗を避ける)
    - municipality_code は kokkai 固定の '00000' を自動付与
    - raw_json に取得時オリジナル JSON を保持 (デバッグ + 将来の re-extract)

使用例:
    loader = BigQueryLoader(project_id="citify-dev")
    inserted = loader.insert_records(records)  # records: list[SpeechRecord]
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol

from .schema import SpeechRecord

logger = logging.getLogger(__name__)

# kokkai は municipality_code = "00000" 固定 (国会レベル、自治体ではない)
KOKKAI_MUNICIPALITY_CODE = "00000"
SOURCE_NAME = "kokkai"

DEFAULT_DATASET_ID = "citify_raw"
DEFAULT_TABLE_ID = "kokkai_speeches"
DEFAULT_BATCH_SIZE = 100


class _BQClientProtocol(Protocol):
    """テスト用に google.cloud.bigquery.Client を mock 可能にするための型。"""

    def insert_rows_json(self, table: str, json_rows: list[dict]) -> list[dict]: ...


def record_to_bq_row(record: SpeechRecord, *, fetched_at: datetime | None = None) -> dict:
    """SpeechRecord -> BigQuery 行 dict (citify_raw.kokkai_speeches スキーマ準拠)。

    Args:
        record: 国会 API から取得した発言レコード
        fetched_at: 取得時刻 (default: 現在 UTC)

    Returns:
        BigQuery insert_rows_json に渡せる dict
    """
    return {
        "id": record.speech_id,
        "source": SOURCE_NAME,
        "municipality_code": KOKKAI_MUNICIPALITY_CODE,
        "session": record.session,
        "name_of_house": record.name_of_house,
        "name_of_meeting": record.name_of_meeting,
        "issue": record.issue,
        "meeting_date": record.meeting_date.isoformat(),
        "speech_order": record.speech_order,
        "speaker": record.speaker,
        "speaker_yomi": record.speaker_yomi,
        "speaker_group": record.speaker_group,
        "speaker_position": record.speaker_position,
        "speech": record.speech,
        "start_page": record.start_page,
        "speech_url": record.speech_url,
        "meeting_url": record.meeting_url,
        "raw_json": json.dumps(
            record.model_dump(by_alias=True, mode="json"),
            ensure_ascii=False,
        ),
        "fetched_at": (fetched_at or datetime.now(UTC)).isoformat(),
    }


class BigQueryLoader:
    """SpeechRecord を BigQuery に投入するローダー。

    Args:
        project_id: GCP プロジェクト ID
        dataset_id: BQ dataset (default: citify_raw)
        table_id: BQ table (default: kokkai_speeches)
        client: BQ クライアント (テスト時に mock 注入)
    """

    def __init__(
        self,
        project_id: str,
        dataset_id: str = DEFAULT_DATASET_ID,
        table_id: str = DEFAULT_TABLE_ID,
        client: _BQClientProtocol | None = None,
    ) -> None:
        if client is None:
            # Import を遅延させる: テスト時は client 注入で google-cloud-bigquery 不要
            from google.cloud import bigquery

            client = bigquery.Client(project=project_id)
        self._client = client
        self._table_ref = f"{project_id}.{dataset_id}.{table_id}"

    def insert_records(
        self,
        records: Iterable[SpeechRecord],
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> int:
        """records を batch_size 単位で BQ に streaming insert。

        Returns:
            挿入件数 (成功した合計)

        Raises:
            RuntimeError: BQ から errors が返った場合 (途中 batch 失敗時)
        """
        if batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got {batch_size}")

        batch: list[dict] = []
        total_inserted = 0
        for record in records:
            batch.append(record_to_bq_row(record))
            if len(batch) >= batch_size:
                total_inserted += self._flush(batch)
                batch = []
        if batch:
            total_inserted += self._flush(batch)
        return total_inserted

    def _flush(self, rows: list[dict]) -> int:
        """1 バッチを BQ に送信。errors 返却時は例外。"""
        errors = self._client.insert_rows_json(self._table_ref, rows)
        if errors:
            logger.error(
                "kokkai.bq_insert_errors table=%s n_rows=%d errors=%s",
                self._table_ref,
                len(rows),
                errors,
            )
            raise RuntimeError(f"BigQuery insert failed ({len(errors)} errors): {errors}")
        logger.info(
            "kokkai.bq_insert success table=%s n_rows=%d",
            self._table_ref,
            len(rows),
        )
        return len(rows)
