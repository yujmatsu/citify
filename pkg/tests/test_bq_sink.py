"""pkg.bq_sink のテスト (BigQuery クライアントは mock)。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pkg.bq_sink import (
    SCORED_SPEECH_COLUMN_TYPES,
    BQSink,
    build_merge_params,
    build_merge_sql,
    scored_speech_to_bq_row,
)
from pkg.pubsub import MessageEnvelope

# ============================================================================
# scored_speech_to_bq_row
# ============================================================================


def _make_scored_envelope(speech_id: str = "prefokayama:177:4:0") -> MessageEnvelope:
    payload = {
        "speech_id": speech_id,
        "user_id": "u-1",
        "municipality_code": "33000",
        "title": "若者向けタイトル",
        "summary": ["L1", "L2", "L3"],
        "detail_url": "https://example.com/m/1",
        "meeting_date": "2025-03-05",
        "score": {
            "relevance_score": 75,
            "score_topic": 25,
            "score_age": 15,
            "score_geographic": 20,
            "score_urgency": 15,
            "matched_interests": ["住居", "雇用"],
            "reasoning": "ペルソナと一致",
            "contains_political_judgment": False,
        },
        "speaker_position": "知事",
        "name_of_meeting": "令和7年2月定例会",
        "tone": "casual",
    }
    return MessageEnvelope(
        schema_version="v1",
        source="relevance",
        payload_type="ScoredSpeech",
        payload=payload,
    )


def test_scored_speech_to_bq_row_extracts_fields():
    env = _make_scored_envelope()
    row = scored_speech_to_bq_row(env)

    assert row["speech_id"] == "prefokayama:177:4:0"
    assert row["user_id"] == "u-1"
    assert row["municipality_code"] == "33000"
    assert row["title"] == "若者向けタイトル"
    assert row["summary"] == ["L1", "L2", "L3"]
    assert row["detail_url"] == "https://example.com/m/1"
    assert row["meeting_date"] == "2025-03-05"
    assert row["relevance_score"] == 75
    assert row["score_topic"] == 25
    assert row["matched_interests"] == ["住居", "雇用"]
    assert row["reasoning"] == "ペルソナと一致"
    assert row["speaker_position"] == "知事"
    assert row["tone"] == "casual"
    assert row["message_id"] is None  # default
    # ingested_at は UTC ISO 文字列
    assert row["ingested_at"].endswith("+00:00")


def test_scored_speech_to_bq_row_handles_missing_optional():
    """optional フィールドが欠落していても落ちない。"""
    minimal = MessageEnvelope(
        schema_version="v1",
        source="relevance",
        payload_type="ScoredSpeech",
        payload={
            "speech_id": "x",
            "user_id": "u",
            "score": {"relevance_score": 0},
        },
    )
    row = scored_speech_to_bq_row(minimal)
    assert row["speech_id"] == "x"
    assert row["municipality_code"] is None
    assert row["title"] is None
    assert row["summary"] == []
    assert row["meeting_date"] is None
    assert row["matched_interests"] == []
    assert row["relevance_score"] == 0


def test_scored_speech_to_bq_row_rejects_wrong_payload_type():
    env = MessageEnvelope(
        schema_version="v1",
        source="x",
        payload_type="TranslatedSpeech",  # 違う型
        payload={"foo": "bar"},
    )
    with pytest.raises(ValueError, match="expected payload_type"):
        scored_speech_to_bq_row(env)


def test_scored_speech_to_bq_row_missing_required_raises_permanent():
    """M1: ScoredSpeech だが speech_id/user_id 欠落 → PermanentMessageError (ack-drop 対象)。"""
    from pkg.pubsub import PermanentMessageError

    env = MessageEnvelope(
        schema_version="v1",
        source="x",
        payload_type="ScoredSpeech",
        payload={"user_id": "demo-25-29"},  # speech_id 欠落
    )
    with pytest.raises(PermanentMessageError, match="missing required keys"):
        scored_speech_to_bq_row(env)


# ============================================================================
# BQSink
# ============================================================================


def _make_mock_bq_client(errors: list | None = None) -> MagicMock:
    """insert_rows_json を mock した BQ クライアント。"""
    client = MagicMock()
    client.insert_rows_json.return_value = errors or []
    return client


def test_bq_sink_insert_envelope_succeeds():
    client = _make_mock_bq_client()
    sink = BQSink(
        project_id="citify-dev",
        table_id="citify_curated.scored_speeches",
        converter=scored_speech_to_bq_row,
        expected_payload_type="ScoredSpeech",
        client=client,
    )

    env = _make_scored_envelope()
    sink.insert_envelope(env, message_id="msg-001")

    client.insert_rows_json.assert_called_once()
    args, _ = client.insert_rows_json.call_args
    assert args[0] == "citify_curated.scored_speeches"
    assert len(args[1]) == 1
    row = args[1][0]
    assert row["speech_id"] == "prefokayama:177:4:0"
    assert row["message_id"] == "msg-001"  # 上書き反映


def test_bq_sink_insert_envelope_raises_on_bq_errors():
    """BQ insert errors が返ると RuntimeError。"""
    client = _make_mock_bq_client(errors=[{"index": 0, "errors": [{"reason": "invalid"}]}])
    sink = BQSink(
        project_id="citify-dev",
        table_id="t.t",
        converter=scored_speech_to_bq_row,
        expected_payload_type="ScoredSpeech",
        client=client,
    )

    with pytest.raises(RuntimeError, match="BQ insert failed"):
        sink.insert_envelope(_make_scored_envelope())


def test_bq_sink_rejects_wrong_payload_type():
    sink = BQSink(
        project_id="citify-dev",
        table_id="t.t",
        converter=scored_speech_to_bq_row,
        expected_payload_type="ScoredSpeech",
        client=_make_mock_bq_client(),
    )

    env = MessageEnvelope(
        schema_version="v1",
        source="x",
        payload_type="TranslatedSpeech",
        payload={"foo": "bar"},
    )
    with pytest.raises(ValueError, match="expected payload_type"):
        sink.insert_envelope(env)


def test_bq_sink_handler_skips_non_expected_payload():
    """make_handler() の handler は非対応 type を warning skip。"""
    client = _make_mock_bq_client()
    sink = BQSink(
        project_id="citify-dev",
        table_id="t.t",
        converter=scored_speech_to_bq_row,
        expected_payload_type="ScoredSpeech",
        client=client,
    )
    handler = sink.make_handler()

    env = MessageEnvelope(
        schema_version="v1",
        source="x",
        payload_type="TranslatedSpeech",
        payload={"foo": "bar"},
    )
    handler(env)  # 例外なし

    client.insert_rows_json.assert_not_called()


def test_bq_sink_handler_inserts_on_expected_payload():
    client = _make_mock_bq_client()
    sink = BQSink(
        project_id="citify-dev",
        table_id="t.t",
        converter=scored_speech_to_bq_row,
        expected_payload_type="ScoredSpeech",
        client=client,
    )
    handler = sink.make_handler()

    handler(_make_scored_envelope())

    client.insert_rows_json.assert_called_once()


def test_bq_sink_handler_propagates_insert_failure():
    """BQ insert 失敗時、handler は例外を伝播 → subscriber が nack。"""
    client = _make_mock_bq_client(errors=[{"index": 0, "errors": [{"reason": "x"}]}])
    sink = BQSink(
        project_id="citify-dev",
        table_id="t.t",
        converter=scored_speech_to_bq_row,
        expected_payload_type="ScoredSpeech",
        client=client,
    )

    with pytest.raises(RuntimeError, match="BQ insert failed"):
        sink.make_handler()(_make_scored_envelope())


# ============================================================================
# MERGE upsert (冪等パス、opt-in)
# ============================================================================


def test_build_merge_sql_shape():
    sql = build_merge_sql(
        "d.scored_speeches", ["speech_id", "user_id", "title"], ("speech_id", "user_id")
    )
    assert "MERGE `d.scored_speeches` T" in sql
    assert "T.speech_id = S.speech_id AND T.user_id = S.user_id" in sql
    assert "WHEN MATCHED THEN UPDATE SET title = S.title" in sql
    assert "WHEN NOT MATCHED THEN INSERT (speech_id, user_id, title)" in sql
    # PK は UPDATE SET に含めない
    assert "speech_id = S.speech_id," not in sql.split("UPDATE SET")[1]


def test_build_merge_params_types():
    row = {
        "speech_id": "x",
        "summary": ["a", "b"],
        "meeting_date": "2025-03-05",
        "ingested_at": "2026-07-02T00:00:00+00:00",
        "relevance_score": 75,
        "title": None,
    }
    params = {p.name: p for p in build_merge_params(row, SCORED_SPEECH_COLUMN_TYPES)}
    # ARRAY<STRING>
    assert params["summary"].array_type == "STRING"
    assert params["summary"].values == ["a", "b"]
    # DATE は ISO str → date に coerce
    from datetime import date, datetime

    assert params["meeting_date"].value == date(2025, 3, 5)
    # TIMESTAMP は ISO str → datetime に coerce
    assert isinstance(params["ingested_at"].value, datetime)
    # INT64 / STRING(None)
    assert params["relevance_score"].type_ == "INT64"
    assert params["title"].value is None


def test_bq_sink_merge_path_calls_query_not_insert():
    """merge_keys + column_types 指定時は MERGE (client.query) を使い、追記しない。"""
    client = MagicMock()
    job = MagicMock()
    job.result.return_value = None
    client.query.return_value = job

    sink = BQSink(
        project_id="citify-dev",
        table_id="citify_curated.scored_speeches",
        converter=scored_speech_to_bq_row,
        expected_payload_type="ScoredSpeech",
        client=client,
        merge_keys=("speech_id", "user_id"),
        column_types=SCORED_SPEECH_COLUMN_TYPES,
    )
    sink.insert_envelope(_make_scored_envelope())

    client.query.assert_called_once()
    client.insert_rows_json.assert_not_called()
    sql = client.query.call_args.args[0]
    assert "MERGE" in sql and "WHEN MATCHED" in sql and "WHEN NOT MATCHED" in sql
    job.result.assert_called_once()
