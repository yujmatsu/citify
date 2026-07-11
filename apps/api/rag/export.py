"""BigQuery `citify_raw.kokkai_speeches` から speech を GCS に export。

各 speech を 1 つの .txt ファイルとして GCS に置き、Vertex AI RAG Engine の
`import_files()` で取り込めるようにする。

ファイル形式:
    gs://{bucket}/{prefix}/{speech_id}.txt
        # メタデータヘッダ (RAG embedding が拾える)
        Speaker: 石破茂 (自由民主党, 内閣総理大臣)
        House: 衆議院
        Meeting: 本会議 (第16号)
        Date: 2026-05-18
        URL: https://kokkai.ndl.go.jp/...

        # Speech 本文
        ただいまから本会議を開きます…
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

logger = logging.getLogger(__name__)

DEFAULT_BQ_SOURCE = "citify-dev.citify_raw.kokkai_speeches"
DEFAULT_STAGING_PREFIX = "kokkai"  # gs://bucket/kokkai/{speech_id}.txt


@dataclass(frozen=True)
class SpeechExportRow:
    """BQ から取り出した speech 1 件 (export 用、Pydantic に依存しない軽量版)。"""

    id: str
    speaker: str | None
    speaker_group: str | None
    speaker_position: str | None
    name_of_house: str | None
    name_of_meeting: str | None
    issue: str | None
    meeting_date: date | None
    speech_url: str | None
    meeting_url: str | None
    speech: str
    # 多ソース対応 (国会 / 自治体議事録)。RAG doc に metadata として埋め、検索結果の
    # 出所 (国会 vs 地方) 判別と将来のフィルタに使う。既定 None (国会=source 列から)。
    source: str | None = None
    municipality_code: str | None = None


class _BQClientProto(Protocol):
    """テスト用、google.cloud.bigquery.Client.query を mock 可能にする。"""

    def query(self, query: str) -> object: ...  # noqa: ARG002


class _GCSBucketProto(Protocol):
    """テスト用、google.cloud.storage.Bucket を mock 可能にする。"""

    def blob(self, name: str) -> object: ...  # noqa: ARG002


def format_speech_for_rag(row: SpeechExportRow) -> str:
    """SpeechExportRow を RAG 取り込み用 .txt 形式に整形。

    embedding model が文脈を理解しやすいよう、metadata header + 本文の 2 部構成。
    """
    speaker_parts = [row.speaker or "(発言者不明)"]
    if row.speaker_group:
        speaker_parts.append(row.speaker_group)
    if row.speaker_position:
        speaker_parts.append(row.speaker_position)
    speaker_line = speaker_parts[0]
    if len(speaker_parts) > 1:
        speaker_line += f" ({', '.join(speaker_parts[1:])})"

    meeting_parts = [p for p in [row.name_of_meeting, row.issue] if p]
    meeting_line = " ".join(meeting_parts) if meeting_parts else "(会議不明)"

    header_lines = [
        f"Speaker: {speaker_line}",
        f"House: {row.name_of_house or '(不明)'}",
        f"Meeting: {meeting_line}",
        f"Date: {row.meeting_date.isoformat() if row.meeting_date else '(日付不明)'}",
    ]
    # 出所メタデータ (国会 / 自治体)。検索結果の出所判別・フィルタ用。
    if row.source:
        header_lines.append(f"Source: {row.source}")
    if row.municipality_code:
        header_lines.append(f"Municipality: {row.municipality_code}")
    if row.speech_url:
        header_lines.append(f"URL: {row.speech_url}")
    if row.meeting_url and row.meeting_url != row.speech_url:
        header_lines.append(f"MeetingURL: {row.meeting_url}")

    header = "\n".join(header_lines)
    return f"{header}\n\n{row.speech}\n"


def _row_get(row: object, key: str) -> object | None:
    """BQ Row / dict どちらからも安全に取り出す (テスト mock は dict)。"""
    try:
        return row[key]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        return None


def _query_distinct_speeches(
    bq_client: _BQClientProto,
    bq_source: str,
    limit: int | None = None,
    *,
    source_label: str | None = None,
    municipality_code: str | None = None,
) -> Iterator[SpeechExportRow]:
    """BQ に DISTINCT id で query を投げて SpeechExportRow を yield。

    multi-keyword 投入で重複した id を 1 件に絞り、最新 fetched_at を採用。
    source / municipality_code はテーブル列 `source`/`municipality_code` から拾う
    (kokkai_speeches は両列を持つ)。列が無いソースでは source_label/municipality_code
    引数で定数上書きできる。
    """
    limit_clause = f"LIMIT {limit}" if limit else ""
    sql = f"""
        WITH deduped AS (
            SELECT
                id, speaker, speaker_group, speaker_position,
                name_of_house, name_of_meeting, issue,
                meeting_date, speech_url, meeting_url, speech,
                source, municipality_code,
                ROW_NUMBER() OVER (PARTITION BY id ORDER BY fetched_at DESC) AS rn
            FROM `{bq_source}`
        )
        SELECT
            id, speaker, speaker_group, speaker_position,
            name_of_house, name_of_meeting, issue,
            meeting_date, speech_url, meeting_url, speech,
            source, municipality_code
        FROM deduped
        WHERE rn = 1 AND speech IS NOT NULL
        ORDER BY meeting_date DESC
        {limit_clause}
    """  # noqa: S608 (bq_source は呼び出し側がコントロール)

    logger.info(
        "rag.export.query bq_source=%s limit=%s source_label=%s", bq_source, limit, source_label
    )
    job = bq_client.query(sql)
    for row in job:  # type: ignore[attr-defined]
        yield SpeechExportRow(
            id=row["id"],
            speaker=row["speaker"],
            speaker_group=row["speaker_group"],
            speaker_position=row["speaker_position"],
            name_of_house=row["name_of_house"],
            name_of_meeting=row["name_of_meeting"],
            issue=row["issue"],
            meeting_date=row["meeting_date"],
            speech_url=row["speech_url"],
            meeting_url=row["meeting_url"],
            speech=row["speech"],
            source=source_label or _row_get(row, "source"),  # type: ignore[arg-type]
            municipality_code=municipality_code or _row_get(row, "municipality_code"),  # type: ignore[arg-type]
        )


def _upload_speech(
    bucket: _GCSBucketProto,
    prefix: str,
    row: SpeechExportRow,
) -> str:
    """1 speech を GCS に upload。返り値は blob name。"""
    blob_name = f"{prefix}/{row.id}.txt"
    blob = bucket.blob(blob_name)
    blob.upload_from_string(  # type: ignore[attr-defined]
        format_speech_for_rag(row),
        content_type="text/plain; charset=utf-8",
    )
    return blob_name


def export_speeches_to_gcs(
    bucket_name: str,
    bq_source: str = DEFAULT_BQ_SOURCE,
    prefix: str = DEFAULT_STAGING_PREFIX,
    limit: int | None = None,
    project_id: str | None = None,
    bq_client: _BQClientProto | None = None,
    gcs_bucket: _GCSBucketProto | None = None,
    on_progress: object | None = None,
    source_label: str | None = None,
    municipality_code: str | None = None,
) -> int:
    """BQ から DISTINCT speech を取り出し、各 1 ファイルとして GCS に export。

    Args:
        bucket_name: GCS bucket 名 (例: citify-dev-rag-staging)
        bq_source: BQ ソーステーブル (project.dataset.table 形式)
        prefix: GCS prefix (default: kokkai)
        limit: 上限 (None = 全件)
        project_id: GCP project ID (BQ / GCS client 自動生成時に使用)
        bq_client: テスト用注入
        gcs_bucket: テスト用注入
        on_progress: progress callback (uploaded: int) -> None

    Returns:
        upload した件数
    """
    if bq_client is None or gcs_bucket is None:
        # 遅延 import: テスト時は完全 mock
        from google.cloud import bigquery, storage

        if bq_client is None:
            bq_client = bigquery.Client(project=project_id)
        if gcs_bucket is None:
            gcs_client = storage.Client(project=project_id)
            gcs_bucket = gcs_client.bucket(bucket_name)

    uploaded = 0
    for row in _query_distinct_speeches(
        bq_client, bq_source, limit, source_label=source_label, municipality_code=municipality_code
    ):
        _upload_speech(gcs_bucket, prefix, row)
        uploaded += 1
        if uploaded % 100 == 0:
            logger.info("rag.export.progress uploaded=%d", uploaded)
        if on_progress is not None:
            on_progress(uploaded)  # type: ignore[operator]

    logger.info("rag.export.done uploaded=%d bucket=%s prefix=%s", uploaded, bucket_name, prefix)
    return uploaded


def iter_rows_for_test(rows: Iterable[SpeechExportRow]) -> Iterator[SpeechExportRow]:
    """テスト用ヘルパー: iterable を iterator に。"""
    yield from rows
