"""BigQueryLoader のユニットテスト (google-cloud-bigquery を mock、実 BQ 不要)。"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from scrapers.kokkai.bq_loader import (
    KOKKAI_MUNICIPALITY_CODE,
    SOURCE_NAME,
    BigQueryLoader,
    record_to_bq_row,
)
from scrapers.kokkai.schema import SpeechRecord


def _make_record(speech_id: str = "id-1", order: int = 1) -> SpeechRecord:
    """テスト用 SpeechRecord ファクトリ。"""
    return SpeechRecord.model_validate(
        {
            "speechID": speech_id,
            "issueID": f"issue-{speech_id}",
            "session": 215,
            "nameOfHouse": "衆議院",
            "nameOfMeeting": "本会議",
            "issue": "第16号",
            "date": "2026-05-18",
            "speechOrder": order,
            "speaker": "石破茂",
            "speakerYomi": "イシバ シゲル",
            "speakerGroup": "自由民主党",
            "speakerPosition": "内閣総理大臣",
            "speech": "ただいまから本会議を開きます。",
            "startPage": 1,
            "speechURL": "https://kokkai.ndl.go.jp/txt/sample/1",
            "meetingURL": "https://kokkai.ndl.go.jp/#/detail?minId=sample",
        }
    )


class _MockBQClient:
    """google.cloud.bigquery.Client.insert_rows_json を mock。

    inserted: 過去呼び出しの履歴 [(table_ref, rows), ...]
    return_errors: 次の呼び出しで返すエラー (default: 空 = 成功)
    """

    def __init__(self, return_errors: list[dict] | None = None) -> None:
        self.inserted: list[tuple[str, list[dict]]] = []
        self.return_errors = return_errors or []

    def insert_rows_json(self, table: str, json_rows: list[dict]) -> list[dict]:
        self.inserted.append((table, json_rows))
        return self.return_errors


def test_record_to_bq_row_maps_all_fields():
    """SpeechRecord の全フィールドが BQ row に正しくマッピングされる。"""
    record = _make_record()
    fetched_at = datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC)
    row = record_to_bq_row(record, fetched_at=fetched_at)

    assert row["id"] == "id-1"
    assert row["source"] == SOURCE_NAME == "kokkai"
    assert row["municipality_code"] == KOKKAI_MUNICIPALITY_CODE == "00000"
    assert row["session"] == 215
    assert row["name_of_house"] == "衆議院"
    assert row["name_of_meeting"] == "本会議"
    assert row["meeting_date"] == "2026-05-18"
    assert row["speech_order"] == 1
    assert row["speaker"] == "石破茂"
    assert row["speaker_group"] == "自由民主党"
    assert row["speech"] == "ただいまから本会議を開きます。"
    assert row["start_page"] == 1
    assert row["fetched_at"] == "2026-05-21T00:00:00+00:00"


def test_record_to_bq_row_raw_json_round_trip():
    """raw_json は元 record を JSON で再構築できる文字列。"""
    record = _make_record()
    row = record_to_bq_row(record)
    raw = json.loads(row["raw_json"])
    # alias 化された camelCase キーで保持
    assert raw["speechID"] == "id-1"
    assert raw["date"] == "2026-05-18"
    assert raw["speakerGroup"] == "自由民主党"


def test_loader_inserts_single_batch():
    """records < batch_size の場合、1 回の flush で全件 insert。"""
    mock_client = _MockBQClient()
    loader = BigQueryLoader(
        project_id="test-project",
        dataset_id="citify_raw",
        table_id="kokkai_speeches",
        client=mock_client,
    )
    records = [_make_record(f"id-{i}", i) for i in range(5)]

    inserted = loader.insert_records(records, batch_size=100)

    assert inserted == 5
    assert len(mock_client.inserted) == 1
    table_ref, rows = mock_client.inserted[0]
    assert table_ref == "test-project.citify_raw.kokkai_speeches"
    assert len(rows) == 5
    assert rows[0]["id"] == "id-0"


def test_loader_splits_into_multiple_batches():
    """records > batch_size の場合、batch_size 単位で分割 insert。"""
    mock_client = _MockBQClient()
    loader = BigQueryLoader(project_id="test-project", client=mock_client)
    records = [_make_record(f"id-{i}", i) for i in range(250)]

    inserted = loader.insert_records(records, batch_size=100)

    assert inserted == 250
    # 100 + 100 + 50 = 3 batch
    assert len(mock_client.inserted) == 3
    assert len(mock_client.inserted[0][1]) == 100
    assert len(mock_client.inserted[1][1]) == 100
    assert len(mock_client.inserted[2][1]) == 50


def test_loader_raises_on_bq_errors():
    """BQ から errors が返ったら RuntimeError raise。"""
    mock_client = _MockBQClient(
        return_errors=[{"index": 0, "errors": [{"reason": "invalid", "message": "bad row"}]}]
    )
    loader = BigQueryLoader(project_id="test-project", client=mock_client)
    records = [_make_record("id-1", 1)]

    with pytest.raises(RuntimeError, match="BigQuery insert failed"):
        loader.insert_records(records)


def test_loader_invalid_batch_size():
    """batch_size < 1 で ValueError。"""
    loader = BigQueryLoader(project_id="test-project", client=_MockBQClient())
    with pytest.raises(ValueError, match="batch_size"):
        loader.insert_records([_make_record()], batch_size=0)
