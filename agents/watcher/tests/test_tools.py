"""watcher tools の test (BQ は mock 注入、TASK-WATCHER Slice 1)。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.watcher import tools as wt


@pytest.fixture(autouse=True)
def _reset_factory():
    yield
    wt.set_bq_client_factory(None)


def _client_returning(rows: list[dict] | Exception) -> MagicMock:
    client = MagicMock()
    if isinstance(rows, Exception):
        client.query.side_effect = rows
    else:
        client.query.return_value.result.return_value = iter(rows)
    return client


# ============================================================================
# search_speeches
# ============================================================================


def test_search_speeches_maps_rows() -> None:
    rows = [
        {
            "speech_id": "sp-1",
            "title": "新保育補助",
            "summary": ["補助拡充"],
            "relevance_score": 82,
            "matched_interests": ["子育て"],
            "detail_url": "https://x/1",
            "meeting_date": "2026-05-20",
        }
    ]
    wt.set_bq_client_factory(lambda: _client_returning(rows))
    out = wt.search_speeches("11227", "demo-40-49", interest="子育て")
    assert len(out) == 1
    assert out[0]["speech_id"] == "sp-1"
    assert out[0]["matched_interests"] == ["子育て"]


def test_search_speeches_graceful_on_bq_failure() -> None:
    wt.set_bq_client_factory(lambda: _client_returning(RuntimeError("BQ down")))
    assert wt.search_speeches("11227", "demo-40-49") == []


# ============================================================================
# fetch_population_trend
# ============================================================================


def test_population_trend_computes_2070_change() -> None:
    rows = [
        {"year": 2020, "population": 100000, "source": "census"},
        {"year": 2025, "population": 99000, "source": "projection"},
        {"year": 2070, "population": 60000, "source": "projection"},
    ]
    wt.set_bq_client_factory(lambda: _client_returning(rows))
    out = wt.fetch_population_trend("11227")
    assert out["latest_actual_year"] == 2020
    # (60000-100000)/100000*100 = -40.0
    assert out["projection_2070_change_pct"] == -40.0
    assert len(out["series"]) == 3


def test_population_trend_graceful_on_failure() -> None:
    wt.set_bq_client_factory(lambda: _client_returning(RuntimeError("BQ down")))
    out = wt.fetch_population_trend("11227")
    assert out["series"] == []
    assert out["projection_2070_change_pct"] is None


# ============================================================================
# compare_towns (Slice 2)
# ============================================================================


def test_compare_towns_returns_per_town_stats() -> None:
    rows = [
        {
            "municipality_code": "13104",
            "population_total": 349385,
            "youth_share_pct": 18.2,
            "elderly_share_pct": 21.0,
            "birth_rate_per_1000": 7.1,
            "population_change_pct": 3.5,
            "population_2050_estimated": 360000,
            "population_change_2025_2050_pct": 2.0,
            "used_apartment_median_price_man_yen": 4900,
            "childcare_facility_count": 80,
            "medical_facility_count": 500,
            "financial_capability_index": 0.98,
            "real_debt_service_ratio_pct": 4.9,
            "taxable_income_per_capita_yen": 3947780,
            "homeownership_rate_pct": 53.7,
            "crime_rate_per_1000": 13.5,
        },
        {
            "municipality_code": "27100",
            "population_total": 2752000,
            "youth_share_pct": 15.0,
            "elderly_share_pct": 27.0,
            "birth_rate_per_1000": 6.0,
            "population_change_pct": -1.2,
            "population_2050_estimated": 2400000,
            "population_change_2025_2050_pct": -12.0,
            "used_apartment_median_price_man_yen": 2600,
            "childcare_facility_count": 300,
            "medical_facility_count": 1200,
        },
    ]
    wt.set_bq_client_factory(lambda: _client_returning(rows))
    out = wt.compare_towns(["13104", "27100"])
    assert {r["municipality_code"] for r in out} == {"13104", "27100"}
    assert out[0]["population_total"] == 349385
    # 街選びに効く新たな軸が含まれる
    assert out[0]["youth_share_pct"] == 18.2
    assert out[0]["population_change_2025_2050_pct"] == 2.0
    assert out[1]["elderly_share_pct"] == 27.0
    # TASK-FISCAL: 財政・所得・治安の軸 (SSDS)
    assert out[0]["financial_capability_index"] == 0.98
    assert out[0]["taxable_income_per_capita_yen"] == 3947780
    assert out[0]["crime_rate_per_1000"] == 13.5
    # Fix2: 廃止した medical_facility_count は返さない / national_rank を付与
    assert "medical_facility_count" not in out[0]
    assert isinstance(out[0]["national_rank"], dict)


def test_compare_towns_missing_columns_become_null() -> None:
    # 一部列が無い行でも例外にならず None 埋め (graceful)
    rows = [{"municipality_code": "13104", "population_total": 100}]
    wt.set_bq_client_factory(lambda: _client_returning(rows))
    out = wt.compare_towns(["13104"])
    assert out[0]["youth_share_pct"] is None
    assert out[0]["doctors_per_100k"] is None


def test_compare_towns_empty_codes() -> None:
    assert wt.compare_towns([]) == []


def _client_seq(result_sets: list[list[dict]]) -> MagicMock:
    """query() 呼び出しごとに別の結果セットを返す client (town 用 + national 用)。"""
    client = MagicMock()
    queries = []
    for rs in result_sets:
        q = MagicMock()
        q.result.return_value = iter(rs)
        queries.append(q)
    client.query.side_effect = queries
    return client


def test_national_top_pct_matches_karte_logic() -> None:
    # Fix1: 街カルテ compare-stats と同じ「上位X%」算出 (1=最上位)
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert wt._national_top_pct(5.0, vals, "higher") == 20  # 最大=上位20% (rank1/5)
    assert wt._national_top_pct(1.0, vals, "higher") == 100
    assert wt._national_top_pct(1.0, vals, "lower") == 20  # 最小=上位 (低いほど良い)
    assert wt._national_top_pct(5.0, vals, "lower") == 100
    assert wt._national_top_pct(None, vals, "higher") is None
    assert wt._national_top_pct(3.0, [], "higher") is None


def test_compare_towns_attaches_national_rank() -> None:
    # 街の生値 + 全国分布 → national_rank が「上位X%」で付く
    town_rows = [{"municipality_code": "13104", "financial_capability_index": 0.98}]
    national_rows = [{"financial_capability_index": v} for v in (0.2, 0.4, 0.6, 0.8, 0.98)]
    wt.set_bq_client_factory(lambda: _client_seq([town_rows, national_rows]))
    out = wt.compare_towns(["13104"])
    # 0.98 は5件中の最上位 → 上位20%
    assert out[0]["national_rank"]["財政力"] == "上位20%"


# ============================================================================
# fetch_topic_trend (Watcher v2 P1, A6)
# ============================================================================


def _months(counts: list[int]) -> list[dict]:
    # year_month は昇順。直近が末尾。
    return [{"year_month": f"2025-{i + 1:02d}", "cnt": c} for i, c in enumerate(counts)]


def test_topic_trend_increasing() -> None:
    # 前6か月 計6、直近6か月 計18 → increasing
    rows = _months([1, 1, 1, 1, 1, 1, 3, 3, 3, 3, 3, 3])
    wt.set_bq_client_factory(lambda: _client_returning(rows))
    out = wt.fetch_topic_trend("11227", "子育て")
    assert out["recent_6m"] == 18
    assert out["prev_6m"] == 6
    assert out["trend"] == "increasing"


def test_topic_trend_flat() -> None:
    rows = _months([2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2])
    wt.set_bq_client_factory(lambda: _client_returning(rows))
    assert wt.fetch_topic_trend("11227", "子育て")["trend"] == "flat"


def test_topic_trend_empty_is_unknown() -> None:
    wt.set_bq_client_factory(lambda: _client_returning([]))
    out = wt.fetch_topic_trend("11227", "子育て")
    assert out["series"] == [] and out["trend"] == "unknown"


def test_topic_trend_graceful_on_failure() -> None:
    wt.set_bq_client_factory(lambda: _client_returning(RuntimeError("BQ down")))
    assert wt.fetch_topic_trend("11227")["trend"] == "unknown"


def test_compare_towns_graceful_on_failure() -> None:
    wt.set_bq_client_factory(lambda: _client_returning(RuntimeError("BQ down")))
    assert wt.compare_towns(["13104"]) == []
