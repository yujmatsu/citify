"""Concierge tools.py のユニットテスト (Plan E Phase 1)。

テスト戦略:
    - BQ client を MagicMock で注入 (DI、google.cloud.bigquery 不要)
    - tool は同期関数なので pytest 標準 (asyncio 不要)
    - 4 tool それぞれ: 正常系 + フィルタ動作 + エラー系
    - helper 関数 (_interest_hits, _calc_match_score) の単体 test も含む
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from agents.concierge.schema import (
    CityDashboardSummary,
    ComparisonTable,
    ConstraintFilter,
    FetchCityDashboardArgs,
    FetchCitySpeechesArgs,
    MunicipalityCandidate,
    ScoredSpeechSummary,
    SearchMunicipalitiesArgs,
)
from agents.concierge.tools import (
    _build_constraint_where,
    _calc_match_score,
    _format_summary,
    _interest_hits,
    _interest_match_score,
    compare_municipalities,
    fetch_city_dashboard,
    fetch_city_speeches,
    search_municipalities,
)

# ============================================================================
# Helper functions: _interest_hits / _interest_match_score / _calc_match_score
# ============================================================================


def test_interest_hits_住居_returns_true_when_apartment_price_set() -> None:
    row = {"used_apartment_median_price_man_yen": 4500}
    assert _interest_hits("住居", row) is True


def test_interest_hits_住居_returns_false_when_apartment_price_none() -> None:
    row = {"used_apartment_median_price_man_yen": None}
    assert _interest_hits("住居", row) is False


def test_interest_hits_子育て_returns_true_when_childcare_positive() -> None:
    assert _interest_hits("子育て", {"childcare_facility_count": 30}) is True


def test_interest_hits_子育て_returns_false_when_childcare_zero() -> None:
    assert _interest_hits("子育て", {"childcare_facility_count": 0}) is False


def test_interest_hits_医療_returns_true_when_medical_positive() -> None:
    assert _interest_hits("医療", {"medical_facility_count": 100}) is True


def test_interest_hits_proxy_interests_use_population_growth() -> None:
    """結婚/雇用/税/起業/移住 は population_change で proxy 判定。"""
    # -5% growth (within -10%) → hit
    assert _interest_hits("結婚", {"population_change_2025_2050_pct": -5.0}) is True
    # -20% growth → not hit
    assert _interest_hits("雇用", {"population_change_2025_2050_pct": -20.0}) is False


def test_interest_match_score_distinct_thresholds() -> None:
    """1 hit=25, 2 hit=40, 3+ hit=50 の diminishing returns。"""
    assert _interest_match_score([]) == 0.0
    assert _interest_match_score(["住居"]) == 25.0
    assert _interest_match_score(["住居", "子育て"]) == 40.0
    assert _interest_match_score(["住居", "子育て", "医療"]) == 50.0
    assert _interest_match_score(["住居", "子育て", "医療", "教育"]) == 50.0  # cap


def test_calc_match_score_full_house() -> None:
    """全 hit + constraint pass + 正方向人口推計 = 100 (cap)。"""
    row = {
        "used_apartment_median_price_man_yen": 4000,
        "childcare_facility_count": 50,
        "population_change_2025_2050_pct": 5.0,
    }
    total, matched = _calc_match_score(["住居", "子育て"], row, constraint_pass=True)
    # 40 (2 hits) + 25 (constraint) + 10 (positive growth) + 15 (base) = 90
    assert total == 90.0
    assert set(matched) == {"住居", "子育て"}


def test_calc_match_score_no_hit_no_constraint_returns_base_only() -> None:
    row = {
        "used_apartment_median_price_man_yen": None,
        "childcare_facility_count": 0,
        "population_change_2025_2050_pct": None,
    }
    total, matched = _calc_match_score(["住居"], row, constraint_pass=False)
    # 0 (no hit) + 0 (no constraint) + 0 (no growth bonus) + 15 (base) = 15
    assert total == 15.0
    assert matched == []


# ============================================================================
# _build_constraint_where
# ============================================================================


def test_build_constraint_where_empty_constraint_returns_1_eq_1() -> None:
    where, params = _build_constraint_where(ConstraintFilter())
    assert where == "1=1"
    assert params == {}


def test_build_constraint_where_max_rent_includes_null_safe_check() -> None:
    where, params = _build_constraint_where(ConstraintFilter(max_avg_rent_man=5000.0))
    assert "used_apartment_median_price_man_yen IS NULL" in where
    assert "<= @max_rent" in where
    assert params["max_rent"] == ("FLOAT64", 5000.0)


def test_build_constraint_where_prefecture_uses_substr() -> None:
    where, params = _build_constraint_where(ConstraintFilter(prefecture_codes=["13", "14"]))
    assert "SUBSTR(municipality_code, 1, 2) IN UNNEST(@prefs)" in where
    assert params["prefs"] == ("STRING", ["13", "14"])


def test_build_constraint_where_multiple_clauses_combined() -> None:
    """複数 constraint で SQL に各 clause が含まれる。"""
    where, params = _build_constraint_where(
        ConstraintFilter(
            min_childcare_count=10,
            min_medical_count=5,
            require_positive_population_growth=True,
        )
    )
    # 3 clauses 全てが含まれる (順序問わず)
    assert "childcare_facility_count >= @min_childcare" in where
    assert "medical_facility_count >= @min_medical" in where
    assert "population_change_2025_2050_pct > 0" in where
    # 結果 params に 2 個 (growth は SQL 内 hard-code、param 不要)
    assert "min_childcare" in params
    assert "min_medical" in params


# ============================================================================
# _format_summary
# ============================================================================


def test_format_summary_with_all_fields() -> None:
    row = {
        "population_total": 150000,
        "youth_share_pct": 18.5,
        "used_apartment_median_price_man_yen": 4200,
        "childcare_facility_count": 45,
        "medical_facility_count": 220,
        "population_change_2025_2050_pct": -12.3,
    }
    text = _format_summary(row)
    assert "150,000 人" in text
    assert "若者 18.5%" in text
    assert "4,200 万円" in text
    assert "保育施設 45 件" in text
    assert "医療機関 220 件" in text
    assert "-12.3%" in text


def test_format_summary_with_empty_row() -> None:
    assert _format_summary({}) == ""


# ============================================================================
# search_municipalities (BQ mock)
# ============================================================================


def _make_mock_bq_client(rows: list[dict[str, Any]]) -> Any:
    """BQ client mock を作成。client.query(...).result() が rows を返す。"""
    mock_row_objects = []
    for row_dict in rows:
        mock_row = MagicMock()
        mock_row.items.return_value = row_dict.items()
        # row["key"] / row.get("key") 両方サポート
        mock_row.__getitem__.side_effect = lambda k, d=row_dict: d[k]
        mock_row.get.side_effect = lambda k, default=None, d=row_dict: d.get(k, default)
        mock_row_objects.append(mock_row)

    mock_job = MagicMock()
    mock_job.result.return_value = iter(mock_row_objects)

    mock_client = MagicMock()
    mock_client.query.return_value = mock_job
    return mock_client


def test_search_municipalities_returns_sorted_by_match_score() -> None:
    """match_score 降順、tie-break は population_total 降順。"""
    rows = [
        {
            "municipality_code": "13104",
            "municipality_name": "新宿区",
            "prefecture": "東京都",
            "population_total": 350000,
            "youth_share_pct": 25.0,
            "used_apartment_median_price_man_yen": 6000,
            "childcare_facility_count": 80,
            "medical_facility_count": 500,
            "population_change_2025_2050_pct": -8.5,
            "emergency_shelter_count": 100,
            "kindergarten_count": 30,
        },
        {
            "municipality_code": "13123",
            "municipality_name": "江戸川区",
            "prefecture": "東京都",
            "population_total": 700000,
            "youth_share_pct": 20.0,
            "used_apartment_median_price_man_yen": 3500,
            "childcare_facility_count": 120,
            "medical_facility_count": 600,
            "population_change_2025_2050_pct": 2.0,
            "emergency_shelter_count": 150,
            "kindergarten_count": 40,
        },
    ]
    client = _make_mock_bq_client(rows)
    args = SearchMunicipalitiesArgs(age_group="25-29", interests=["住居", "子育て"], limit=5)
    result = search_municipalities(args, bq_client=client)
    assert len(result) == 2
    assert all(isinstance(c, MunicipalityCandidate) for c in result)
    # 江戸川区が高スコア (人口推計が positive で +10、新宿区は -8.5% で 0)
    assert result[0].municipality_code == "13123"
    assert result[0].match_score > result[1].match_score


def test_search_municipalities_respects_limit() -> None:
    rows = [
        {
            "municipality_code": f"131{i:02d}",
            "municipality_name": f"区{i}",
            "prefecture": "東京都",
            "population_total": 100000 * (10 - i),  # 大きい順に
            "used_apartment_median_price_man_yen": 5000,
            "childcare_facility_count": 50,
        }
        for i in range(10)
    ]
    client = _make_mock_bq_client(rows)
    args = SearchMunicipalitiesArgs(age_group="25-29", interests=["住居"], limit=3)
    result = search_municipalities(args, bq_client=client)
    assert len(result) == 3


def test_search_municipalities_bq_failure_returns_empty() -> None:
    """BQ exception の時は空 list を返す (graceful)。"""
    client = MagicMock()
    client.query.side_effect = Exception("BQ timeout")
    args = SearchMunicipalitiesArgs(age_group="25-29", interests=["住居"])
    result = search_municipalities(args, bq_client=client)
    assert result == []


def test_search_municipalities_empty_rows_returns_empty() -> None:
    client = _make_mock_bq_client([])
    args = SearchMunicipalitiesArgs(age_group="25-29", interests=["住居"])
    result = search_municipalities(args, bq_client=client)
    assert result == []


def test_search_municipalities_sql_excludes_prefecture_totals() -> None:
    """SQL に都道府県全体行 (XX000) を除外する WHERE 句が含まれる。

    Phase 3 smoke test で reply に「神奈川県 (広域)」「北海道 (広域)」が混入する
    UX 課題を解消するため。
    """
    client = _make_mock_bq_client([])
    args = SearchMunicipalitiesArgs(age_group="25-29", interests=["住居"])
    search_municipalities(args, bq_client=client)

    # client.query() に渡された SQL を確認
    sql_arg = client.query.call_args.args[0]
    assert "municipality_code NOT LIKE '%000'" in sql_arg


def test_search_municipalities_combined_filter_with_constraints() -> None:
    """constraint と都道府県除外の両方を併用しても正しい WHERE になる。"""
    client = _make_mock_bq_client([])
    args = SearchMunicipalitiesArgs(
        age_group="25-29",
        interests=["住居"],
        constraints=ConstraintFilter(max_avg_rent_man=5000.0),
    )
    search_municipalities(args, bq_client=client)

    sql_arg = client.query.call_args.args[0]
    # constraint 部分
    assert "used_apartment_median_price_man_yen" in sql_arg
    # 都道府県除外部分
    assert "municipality_code NOT LIKE '%000'" in sql_arg
    # AND で結合
    assert " AND " in sql_arg


# ============================================================================
# compare_municipalities (BQ mock)
# ============================================================================


def test_compare_municipalities_returns_rows_in_input_order() -> None:
    """municipality_codes の順序通りに ComparisonRow が返る。"""
    # 各自治体ごとに 2 query (speeches + name resolution)
    name_lookup_rows = [{"municipality_name": "新宿区"}, {"municipality_name": "渋谷区"}]
    speech_rows_per_muni = [
        [
            {
                "speech_id": "13104:press-a:2026-05-29:0",
                "title": "保育園拡充",
                "summary": ["保育園を増やす", "予算1億", "来年度から"],
                "relevance_score": 90,
                "detail_url": "https://example.com/1",
            }
        ],
        [
            {
                "speech_id": "13113:press-b:2026-05-29:0",
                "title": "子育て補助新設",
                "summary": ["補助金", "月3万", "対象は若者"],
                "relevance_score": 85,
                "detail_url": "https://example.com/2",
            }
        ],
    ]

    # client.query の返り値を順番に切り替える (call_count で分岐)
    call_count = [0]

    def fake_query(sql: str, job_config: Any = None) -> Any:  # noqa: ARG001
        idx = call_count[0]
        call_count[0] += 1
        # 偶数 call は speeches (各 muni の最初)、奇数 call は name lookup
        # でも実際の順序は: muni1_speeches → muni1_name → muni2_speeches → muni2_name
        # と仮定すると idx=0,2 が speeches, idx=1,3 が name
        mock_job = MagicMock()
        if idx == 0:
            mock_rows = _make_mock_bq_client(speech_rows_per_muni[0]).query("").result.return_value
        elif idx == 1:
            mock_rows = _make_mock_bq_client(name_lookup_rows[:1]).query("").result.return_value
        elif idx == 2:
            mock_rows = _make_mock_bq_client(speech_rows_per_muni[1]).query("").result.return_value
        else:
            mock_rows = _make_mock_bq_client(name_lookup_rows[1:2]).query("").result.return_value
        mock_job.result.return_value = mock_rows
        return mock_job

    client = MagicMock()
    client.query.side_effect = fake_query

    result = compare_municipalities(
        municipality_codes=["13104", "13113"], interest="子育て", limit=3, bq_client=client
    )

    assert isinstance(result, ComparisonTable)
    assert result.interest == "子育て"
    assert len(result.rows) == 2
    assert result.rows[0].municipality_code == "13104"
    assert result.rows[1].municipality_code == "13113"
    assert result.neutral_observation is None  # tool では生成しない


def test_compare_municipalities_handles_bq_failure_for_one_muni() -> None:
    """1 自治体の BQ 失敗で全体が止まらず、空 top_speeches で返る。"""
    client = MagicMock()
    client.query.side_effect = Exception("partial BQ failure")

    result = compare_municipalities(
        municipality_codes=["13104", "13113"], interest="子育て", bq_client=client
    )
    assert len(result.rows) == 2
    assert all(row.top_speeches == [] for row in result.rows)


# ============================================================================
# fetch_city_dashboard (BQ mock)
# ============================================================================


def test_fetch_city_dashboard_returns_stats_and_topics() -> None:
    """statistics + topic_counts + top_speeches を返す。"""
    # 1st query: stats lookup
    stats_row = {
        "municipality_code": "13104",
        "municipality_name": "新宿区",
        "prefecture": "東京都",
        "population_total": 350000,
        "youth_share_pct": 25.0,
        "elderly_share_pct": 20.0,
        "used_apartment_median_price_man_yen": 6000,
        "childcare_facility_count": 80,
        "medical_facility_count": 500,
        "emergency_shelter_count": 100,
        "population_change_2025_2050_pct": -8.5,
    }
    # 2nd query: speeches with matched_interests for topic count
    speech_rows = [
        {
            "speech_id": "13104:press-a:2026-05-29:0",
            "title": "保育園拡充",
            "summary": ["a", "b", "c"],
            "relevance_score": 90,
            "detail_url": "https://example.com/1",
            "matched_interests": ["子育て"],
        },
        {
            "speech_id": "13104:press-b:2026-05-29:0",
            "title": "家賃補助",
            "summary": ["a", "b", "c"],
            "relevance_score": 85,
            "detail_url": "https://example.com/2",
            "matched_interests": ["住居", "子育て"],
        },
    ]

    call_count = [0]

    def fake_query(sql: str, job_config: Any = None) -> Any:  # noqa: ARG001
        idx = call_count[0]
        call_count[0] += 1
        mock_job = MagicMock()
        if idx == 0:
            mock_job.result.return_value = (
                _make_mock_bq_client([stats_row]).query("").result.return_value
            )
        else:
            mock_job.result.return_value = (
                _make_mock_bq_client(speech_rows).query("").result.return_value
            )
        return mock_job

    client = MagicMock()
    client.query.side_effect = fake_query

    args = FetchCityDashboardArgs(municipality_code="13104", user_id="demo-25-29")
    result = fetch_city_dashboard(args, bq_client=client)

    assert isinstance(result, CityDashboardSummary)
    assert result.municipality_code == "13104"
    assert result.name == "新宿区"
    assert result.prefecture == "東京都"
    assert result.stats["population_total"] == 350000
    assert result.stats["childcare_facility_count"] == 80
    # 子育て 2 hits, 住居 1 hit
    counts = {tc.interest: tc.count for tc in result.topic_counts}
    assert counts["子育て"] == 2
    assert counts["住居"] == 1
    assert len(result.top_speeches) == 2


def test_fetch_city_dashboard_handles_missing_stats() -> None:
    """municipality_stats に該当行なしでも empty stats で返る。"""

    def fake_query(sql: str, job_config: Any = None) -> Any:  # noqa: ARG001
        mock_job = MagicMock()
        mock_job.result.return_value = iter([])  # 全 query 空
        return mock_job

    client = MagicMock()
    client.query.side_effect = fake_query

    args = FetchCityDashboardArgs(municipality_code="99999", user_id="demo-25-29")
    result = fetch_city_dashboard(args, bq_client=client)
    assert result.municipality_code == "99999"
    assert result.stats == {}
    assert result.topic_counts == []


# ============================================================================
# fetch_city_speeches (BQ mock)
# ============================================================================


def test_fetch_city_speeches_returns_summaries_with_optional_interest() -> None:
    speech_rows = [
        {
            "speech_id": "13104:press-a:2026-05-29:0",
            "title": "保育園拡充",
            "summary": ["a", "b", "c"],
            "relevance_score": 90,
            "matched_interests": ["子育て"],
            "detail_url": "https://example.com/1",
            "meeting_date": date(2026, 5, 29),
        },
    ]
    client = _make_mock_bq_client(speech_rows)
    args = FetchCitySpeechesArgs(municipality_code="13104", interest="子育て", limit=5)
    result = fetch_city_speeches(args, bq_client=client)
    assert len(result) == 1
    assert isinstance(result[0], ScoredSpeechSummary)
    assert result[0].speech_id == "13104:press-a:2026-05-29:0"
    assert result[0].relevance_score == 90
    assert result[0].meeting_date == "2026-05-29"


def test_fetch_city_speeches_works_without_interest_filter() -> None:
    """interest=None でも問題なく動く (BQ クエリの interest_clause が空)。"""
    speech_rows = [
        {
            "speech_id": "13104:press-a:2026-05-29:0",
            "title": "X",
            "summary": ["a"],
            "relevance_score": 80,
            "matched_interests": ["住居"],
            "detail_url": "https://example.com/1",
            "meeting_date": None,
        },
    ]
    client = _make_mock_bq_client(speech_rows)
    args = FetchCitySpeechesArgs(municipality_code="13104", interest=None)
    result = fetch_city_speeches(args, bq_client=client)
    assert len(result) == 1
    assert result[0].meeting_date is None


def test_fetch_city_speeches_bq_failure_returns_empty() -> None:
    client = MagicMock()
    client.query.side_effect = Exception("BQ down")
    args = FetchCitySpeechesArgs(municipality_code="13104")
    result = fetch_city_speeches(args, bq_client=client)
    assert result == []


# ============================================================================
# Pydantic schema validation (boundary cases)
# ============================================================================


def test_search_municipalities_args_validates_interests_length() -> None:
    """interests は 1-5 個 (min_length=1, max_length=5)。"""
    with pytest.raises(ValueError):
        SearchMunicipalitiesArgs(age_group="25-29", interests=[])  # 空は不可
    with pytest.raises(ValueError):
        SearchMunicipalitiesArgs(
            age_group="25-29",
            interests=["住居", "子育て", "医療", "教育", "防災", "雇用"],  # type: ignore[list-item]
        )


def test_fetch_city_dashboard_args_validates_municipality_code_length() -> None:
    """municipality_code は 5 桁固定。"""
    with pytest.raises(ValueError):
        FetchCityDashboardArgs(municipality_code="123", user_id="demo-25-29")
    with pytest.raises(ValueError):
        FetchCityDashboardArgs(municipality_code="1310456", user_id="demo-25-29")
