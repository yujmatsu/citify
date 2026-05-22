"""国会会議録 (BQ kokkai_speeches) → Pub/Sub citify-speech-translate publish。

国会 API クライアントが既に BQ に投入したデータを Pub/Sub パイプライン
(translator → relevance → distributor + bq_sink) に流すブリッジ。

設計:
    - source 名は "kokkai_api" 固定 (pkg.municipality_map で 00000 にマッピング)
    - payload_type は "Speech" (kaigiroku Speech と互換、translator worker が受け取れる)
    - kokkai 固有メタ (speech_id, session, issue, speaker_yomi, speaker_group) は
      Speech.model_config = extra="allow" でそのまま payload に含める
    - municipality_code は worker 側で resolve_municipality_code() が "00000" に解決
"""

from __future__ import annotations

import logging
from typing import Any

from pkg.pubsub import MessageEnvelope, PubSubPublisher

logger = logging.getLogger(__name__)

SOURCE = "kokkai_api"

# BQ kokkai_speeches → publish 対象カラム
_SELECT_COLUMNS = """
    id, source, municipality_code, session, name_of_house, name_of_meeting,
    issue, meeting_date, speech_order, speaker, speaker_yomi, speaker_group,
    speaker_position, speech, speech_url, meeting_url
"""


def kokkai_row_to_speech_payload(row: Any) -> dict[str, Any]:
    """BQ kokkai_speeches row → Speech-style dict (translator が読める形式)。

    Args:
        row: google.cloud.bigquery.table.Row (Mapping like)
    """
    meeting_date = row.get("meeting_date")
    meeting_date_str = meeting_date.isoformat() if meeting_date else None

    return {
        # Speech (kaigiroku 互換) フィールド
        "tenant_id": row.get("name_of_house") or "kokkai",
        "council_id": str(row.get("session") or ""),
        "schedule_id": row.get("issue"),
        "meeting_date": meeting_date_str,
        "name_of_meeting": row.get("name_of_meeting") or "",
        "speech_order": int(row.get("speech_order") or 0),
        "speech_type": None,  # kokkai は ○△◎ マーク無し
        "speaker": row.get("speaker") or "(unknown)",
        "speaker_position": row.get("speaker_position"),
        "content_text": row.get("speech") or "",
        "detail_url": row.get("speech_url") or "",
        # kokkai 固有メタ (extra="allow" で保持、translator は無視)
        "kokkai_speech_id": row.get("id"),
        "kokkai_session": row.get("session"),
        "speaker_yomi": row.get("speaker_yomi"),
        "speaker_group": row.get("speaker_group"),
        "meeting_url": row.get("meeting_url"),
    }


def fetch_kokkai_rows_from_bq(
    project_id: str,
    limit: int = 50,
    days: int | None = None,
    keyword: str | None = None,
    name_of_house: str | None = None,
    name_of_meeting: str | None = None,
    order: str = "rand",
    client: Any | None = None,
) -> list[Any]:
    """BQ kokkai_speeches から行を取得。

    Args:
        project_id: GCP project
        limit: 取得上限件数
        days: 過去 N 日に絞る (None で全期間)
        keyword: speech 本文部分一致 (例: '住居')
        name_of_house: '衆議院' or '参議院'
        name_of_meeting: '本会議' / '予算委員会' 等
        order: 'rand' | 'recent' (meeting_date DESC) | 'oldest'
        client: テスト用 mock BQ client
    """
    if client is None:
        from google.cloud import bigquery

        client = bigquery.Client(project=project_id)

    from google.cloud import bigquery

    where_clauses: list[str] = ["speech IS NOT NULL"]
    params: list = [bigquery.ScalarQueryParameter("limit", "INT64", limit)]

    if days is not None:
        where_clauses.append(f"meeting_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {int(days)} DAY)")
    if keyword:
        where_clauses.append("LOWER(speech) LIKE LOWER(@keyword)")
        params.append(bigquery.ScalarQueryParameter("keyword", "STRING", f"%{keyword}%"))
    if name_of_house:
        where_clauses.append("name_of_house = @name_of_house")
        params.append(bigquery.ScalarQueryParameter("name_of_house", "STRING", name_of_house))
    if name_of_meeting:
        where_clauses.append("name_of_meeting = @name_of_meeting")
        params.append(bigquery.ScalarQueryParameter("name_of_meeting", "STRING", name_of_meeting))

    where_sql = " AND ".join(where_clauses)
    order_sql = {
        "rand": "ORDER BY RAND()",
        "recent": "ORDER BY meeting_date DESC, speech_order ASC",
        "oldest": "ORDER BY meeting_date ASC, speech_order ASC",
    }.get(order, "ORDER BY RAND()")

    sql = f"""
        SELECT{_SELECT_COLUMNS}
        FROM `{project_id}.citify_raw.kokkai_speeches`
        WHERE {where_sql}
        {order_sql}
        LIMIT @limit
    """  # noqa: S608

    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = list(client.query(sql, job_config=job_config).result(timeout=60))
    logger.info("kokkai.publish.fetched n=%d days=%s keyword=%s", len(rows), days, keyword)
    return rows


def publish_kokkai_speeches(
    project_id: str,
    topic: str,
    rows: list[Any],
    publisher: PubSubPublisher | None = None,
) -> list[str]:
    """BQ rows を Speech envelope として publish。"""
    if not rows:
        logger.info("kokkai.publish.skip n=0")
        return []

    pub = publisher or PubSubPublisher(project_id=project_id)
    msg_ids: list[str] = []

    for row in rows:
        payload = kokkai_row_to_speech_payload(row)
        envelope = MessageEnvelope(
            schema_version="v1",
            source=SOURCE,
            payload_type="Speech",
            payload=payload,
        )
        attrs = {
            "tenant_id": payload["tenant_id"],
            "council_id": payload["council_id"],
            "schedule_id": payload["schedule_id"] or "",
        }
        msg_id = pub.publish_envelope(topic, envelope, attributes=attrs)
        msg_ids.append(msg_id)

    logger.info(
        "kokkai.publish.done topic=%s n=%d (sample speaker_position=%r)",
        topic,
        len(msg_ids),
        rows[0].get("speaker_position") if rows else None,
    )
    return msg_ids


def fetch_and_publish_kokkai_speeches_from_bq(
    project_id: str,
    topic: str,
    limit: int = 50,
    days: int | None = None,
    keyword: str | None = None,
    name_of_house: str | None = None,
    name_of_meeting: str | None = None,
    order: str = "rand",
    bq_client: Any | None = None,
    publisher: PubSubPublisher | None = None,
) -> list[str]:
    """fetch + publish の一体化エントリ (CLI / 外部呼び出し用)。"""
    rows = fetch_kokkai_rows_from_bq(
        project_id=project_id,
        limit=limit,
        days=days,
        keyword=keyword,
        name_of_house=name_of_house,
        name_of_meeting=name_of_meeting,
        order=order,
        client=bq_client,
    )
    return publish_kokkai_speeches(project_id, topic, rows, publisher=publisher)
