"""KokkaiClient のユニットテスト (httpx.MockTransport ベース、実ネットワーク不要)。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from scrapers.kokkai.client import KokkaiClient
from scrapers.kokkai.schema import SpeechRecord

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _make_record(i: int) -> dict:
    """テスト用の最小レコード生成。"""
    return {
        "speechID": f"id-{i}",
        "issueID": f"issue-{i}",
        "session": 215,
        "nameOfHouse": "衆議院",
        "nameOfMeeting": "本会議",
        "issue": "第1号",
        "date": "2026-05-18",
        "speechOrder": i,
        "speaker": f"speaker-{i}",
        "speech": f"speech body {i}",
        "speechURL": "https://example.com/speech",
        "meetingURL": "https://example.com/meeting",
    }


def _make_transport(responses: list[dict]) -> httpx.MockTransport:
    """list[response_dict] を順番に返す MockTransport。"""
    state = {"call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(state["call_count"], len(responses) - 1)
        state["call_count"] += 1
        return httpx.Response(200, json=responses[idx])

    return httpx.MockTransport(handler)


async def test_fetch_single_page_parses_fixture():
    """sample_response.json から 2 件パースできる。"""
    fixture = _load_fixture("sample_response.json")
    transport = _make_transport([fixture])

    async with KokkaiClient(transport=transport, rate_limit_sec=0) as client:
        records = [
            r
            async for r in client.fetch_speeches(
                from_date=date(2026, 5, 1),
                until_date=date(2026, 5, 21),
            )
        ]

    assert len(records) == 2
    assert isinstance(records[0], SpeechRecord)
    assert records[0].speaker == "石破茂"
    assert records[0].speaker_group == "自由民主党"
    assert records[0].name_of_house == "衆議院"
    assert records[1].speech_order == 2


async def test_pagination_follows_next_record_position():
    """nextRecordPosition がある間 ページネーションが続く。"""
    page1 = {
        "numberOfRecords": 50,
        "numberOfReturn": 30,
        "startRecord": 1,
        "nextRecordPosition": 31,
        "speechRecord": [_make_record(i) for i in range(30)],
    }
    page2 = {
        "numberOfRecords": 50,
        "numberOfReturn": 20,
        "startRecord": 31,
        "nextRecordPosition": None,
        "speechRecord": [_make_record(30 + i) for i in range(20)],
    }
    transport = _make_transport([page1, page2])

    async with KokkaiClient(transport=transport, rate_limit_sec=0) as client:
        records = [
            r
            async for r in client.fetch_speeches(
                from_date=date(2026, 5, 1),
                until_date=date(2026, 5, 21),
                page_size=30,
            )
        ]

    assert len(records) == 50
    assert records[0].speech_id == "id-0"
    assert records[-1].speech_id == "id-49"


async def test_max_total_stops_early():
    """max_total に達したら次ページに進まず終了。"""
    fixture = _load_fixture("sample_response.json")
    transport = _make_transport([fixture])

    async with KokkaiClient(transport=transport, rate_limit_sec=0) as client:
        records = [
            r
            async for r in client.fetch_speeches(
                from_date=date(2026, 5, 1),
                until_date=date(2026, 5, 21),
                max_total=1,
            )
        ]

    assert len(records) == 1
    assert records[0].speaker == "石破茂"


async def test_keyword_passed_as_query_param():
    """keyword 引数が API の `any` パラメタとして送信される。"""
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            json={
                "numberOfRecords": 0,
                "numberOfReturn": 0,
                "startRecord": 1,
                "speechRecord": [],
            },
        )

    transport = httpx.MockTransport(handler)
    async with KokkaiClient(transport=transport, rate_limit_sec=0) as client:
        _ = [
            r
            async for r in client.fetch_speeches(
                from_date=date(2026, 5, 1),
                until_date=date(2026, 5, 21),
                keyword="少子化",
                speaker="石破茂",
                name_of_house="衆議院",
            )
        ]

    params = captured["params"]
    assert params["any"] == "少子化"
    assert params["speaker"] == "石破茂"
    assert params["nameOfHouse"] == "衆議院"
    assert params["recordPacking"] == "json"


async def test_invalid_page_size_raises():
    """page_size が 1-100 範囲外なら ValueError。"""
    async with KokkaiClient(rate_limit_sec=0) as client:
        with pytest.raises(ValueError, match="page_size"):
            _ = [
                r
                async for r in client.fetch_speeches(
                    from_date=date(2026, 5, 1),
                    until_date=date(2026, 5, 21),
                    page_size=101,
                )
            ]


async def test_invalid_date_range_raises():
    """from_date > until_date で ValueError。"""
    async with KokkaiClient(rate_limit_sec=0) as client:
        with pytest.raises(ValueError, match="from_date"):
            _ = [
                r
                async for r in client.fetch_speeches(
                    from_date=date(2026, 5, 21),
                    until_date=date(2026, 5, 1),
                )
            ]


async def test_retry_on_5xx_then_succeed():
    """5xx で 1 回失敗 → 2 回目成功するパターン。"""
    fixture = _load_fixture("sample_response.json")
    state = {"call_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["call_count"] += 1
        if state["call_count"] == 1:
            return httpx.Response(503, json={"error": "service unavailable"})
        return httpx.Response(200, json=fixture)

    transport = httpx.MockTransport(handler)
    # rate_limit と retry の sleep を両方 0 にすればテスト高速
    async with KokkaiClient(transport=transport, rate_limit_sec=0) as client:
        # 内部の retry sleep が 1 sec から始まる点に注意 (テスト時間 ~1 sec)
        records = [
            r
            async for r in client.fetch_speeches(
                from_date=date(2026, 5, 1),
                until_date=date(2026, 5, 21),
            )
        ]

    assert state["call_count"] == 2
    assert len(records) == 2
