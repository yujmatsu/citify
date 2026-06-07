"""Concierge Agent の Tool 関数群 (Plan E)。

各 tool は BQ への single-query で完結する純粋関数として実装。
ADK FunctionTool でラップされて Concierge Agent から呼ばれる。

設計方針:
    - module-level function として実装 (class method ではない、テスト容易性優先)
    - BQ client は lazy init (`_get_bq_client()`)、テストでは mock 注入可能
    - 各 tool は Pydantic BaseModel を引数 + 戻り値とする
      (ADK が schema を読んで LLM tool call の引数を組み立てる)
    - エラー時は graceful (空 list / None) で返す、Concierge が無限 retry しないよう
"""

from __future__ import annotations

import logging
from typing import Any

from agents.relevance.schema import Interest

from .schema import (
    CityDashboardSummary,
    ComparisonRow,
    ComparisonTable,
    ConstraintFilter,
    FetchCityDashboardArgs,
    FetchCitySpeechesArgs,
    MunicipalityCandidate,
    ScoredSpeechSummary,
    SearchMunicipalitiesArgs,
    TopicCount,
)

logger = logging.getLogger(__name__)

# BQ 定数 (環境変数で上書き可、main.py と同期)
import os  # noqa: E402

BQ_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "citify-dev")
BQ_DATASET_CURATED = os.getenv("BQ_DATASET_CURATED", "citify_curated")
BQ_TABLE_STATS = os.getenv("BQ_TABLE_STATS", "municipality_stats")
BQ_TABLE_SCORED_SPEECHES_LATEST = os.getenv(
    "BQ_TABLE_SCORED_SPEECHES_LATEST", "scored_speeches_latest"
)


def _get_bq_client() -> Any:
    """遅延 import (テストで mock 注入可能、起動高速化)。"""
    from google.cloud import bigquery

    return bigquery.Client(project=BQ_PROJECT)


# ----------------------------------------------------------------------------
# Tool 1: search_municipalities
# ----------------------------------------------------------------------------


def _build_constraint_where(c: ConstraintFilter) -> tuple[str, dict[str, Any]]:
    """ConstraintFilter から BQ WHERE 句と parameters を組み立て。"""
    clauses: list[str] = []
    params: dict[str, Any] = {}

    if c.max_avg_rent_man is not None:
        clauses.append(
            "(used_apartment_median_price_man_yen IS NULL "
            "OR used_apartment_median_price_man_yen <= @max_rent)"
        )
        params["max_rent"] = ("FLOAT64", c.max_avg_rent_man)
    if c.min_childcare_count is not None:
        clauses.append("childcare_facility_count >= @min_childcare")
        params["min_childcare"] = ("INT64", c.min_childcare_count)
    if c.min_medical_count is not None:
        clauses.append("medical_facility_count >= @min_medical")
        params["min_medical"] = ("INT64", c.min_medical_count)
    if c.min_population is not None:
        clauses.append("population_total >= @min_pop")
        params["min_pop"] = ("INT64", c.min_population)
    if c.max_population is not None:
        clauses.append("population_total <= @max_pop")
        params["max_pop"] = ("INT64", c.max_population)
    if c.require_positive_population_growth:
        clauses.append("(population_change_pct IS NOT NULL AND population_change_pct > 0)")
    if c.prefecture_codes:
        clauses.append("SUBSTR(municipality_code, 1, 2) IN UNNEST(@prefs)")
        params["prefs"] = ("STRING", c.prefecture_codes)

    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params


def _interest_match_score(matched: list[str]) -> float:
    """interest hit 数からスコア計算 (max 50 点)。"""
    # 1 hit=25, 2 hit=40, 3+ hit=50 (diminishing returns)
    n = len(matched)
    if n <= 0:
        return 0.0
    if n == 1:
        return 25.0
    if n == 2:
        return 40.0
    return 50.0


# interest 軸 → 関連列のヒット判定 dispatch (テスト容易性 + ruff SIM114 対策)
def _interest_hits(interest: Interest, row: dict[str, Any]) -> bool:
    """1 つの interest が row の統計に hit するか判定。"""
    if interest == "住居":
        return row.get("used_apartment_median_price_man_yen") is not None
    if interest == "子育て":
        return (row.get("childcare_facility_count") or 0) > 0
    if interest == "医療":
        return (row.get("medical_facility_count") or 0) > 0
    if interest == "教育":
        return (row.get("kindergarten_count") or 0) > 0
    if interest == "防災":
        return (row.get("emergency_shelter_count") or 0) > 0
    # 結婚 / 雇用 / 税 / 起業 / 移住 は stats で直接判定不可、人口変動で proxy
    if interest in ("結婚", "雇用", "税", "起業", "移住"):
        growth = row.get("population_change_pct")
        return growth is not None and growth > -10  # -10% 以内なら住みやすいと proxy 判定
    return False


def _calc_match_score(
    interests: list[Interest],
    row: dict[str, Any],
    constraint_pass: bool,
) -> tuple[float, list[Interest]]:
    """1 行に対する match_score 計算。

    Returns:
        (match_score, matched_interests) のタプル
    """
    matched: list[Interest] = [i for i in interests if _interest_hits(i, row)]

    interest_score = _interest_match_score(matched)
    constraint_score = 25.0 if constraint_pass else 0.0

    growth = row.get("population_change_pct")
    growth_bonus = 10.0 if (growth is not None and growth > 0) else 0.0

    base = 15.0
    total = min(100.0, interest_score + constraint_score + growth_bonus + base)
    return total, matched


def _row_to_candidate(
    row: dict[str, Any],
    match_score: float,
    matched_interests: list[Interest],
) -> MunicipalityCandidate:
    """BQ row dict → MunicipalityCandidate."""
    return MunicipalityCandidate(
        municipality_code=row["municipality_code"],
        name=row.get("municipality_name") or row["municipality_code"],
        prefecture=row.get("prefecture") or "",
        match_score=round(match_score, 1),
        population_total=row.get("population_total"),
        youth_share_pct=row.get("youth_share_pct"),
        used_apartment_median_price_man_yen=row.get("used_apartment_median_price_man_yen"),
        childcare_facility_count=row.get("childcare_facility_count"),
        medical_facility_count=row.get("medical_facility_count"),
        population_change_pct=row.get("population_change_pct"),
        financial_capability_index=row.get("financial_capability_index"),
        matched_interests=matched_interests,
        summary_text=_format_summary(row),
    )


def _format_summary(row: dict[str, Any]) -> str:
    """1 自治体の主要統計を 1 行 ASCII でまとめる (LLM 用 reasoning 材料)。"""
    parts = []
    if row.get("population_total"):
        parts.append(f"人口 {row['population_total']:,} 人")
    if row.get("youth_share_pct") is not None:
        parts.append(f"若者 {row['youth_share_pct']:.1f}%")
    if row.get("used_apartment_median_price_man_yen"):
        parts.append(f"中古マンション中央値 {row['used_apartment_median_price_man_yen']:,} 万円")
    if row.get("childcare_facility_count") is not None:
        parts.append(f"保育施設 {row['childcare_facility_count']} 件")
    if row.get("medical_facility_count") is not None:
        parts.append(f"医療機関 {row['medical_facility_count']} 件")
    if row.get("population_change_pct") is not None:
        growth = row["population_change_pct"]
        parts.append(f"人口増減率 {growth:+.1f}%")
    if row.get("financial_capability_index") is not None:
        parts.append(f"財政力指数 {row['financial_capability_index']:.2f}")
    return " / ".join(parts)


def search_municipalities(
    args: SearchMunicipalitiesArgs,
    bq_client: Any | None = None,
) -> list[MunicipalityCandidate]:
    """ペルソナと制約に基づいて自治体 TOP N を返す。

    Args:
        args: 検索条件 (age_group, interests, constraints, limit)
        bq_client: テスト用 mock 注入

    Returns:
        match_score 降順、最大 args.limit 件
    """
    client = bq_client or _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"

    constraint = args.constraints or ConstraintFilter()
    where, params_dict = _build_constraint_where(constraint)

    # 移住先候補は市区町村レベルに限定。
    # municipality_code が 'XX000' (都道府県全体) や '00000' (国会) の集計行は
    # search 結果に含めない (UX 上「自治体」として実態がない)。
    # 政令市親 (XX100/XX130/XX140/XX150) や東京特別区 (13101-13123) は含める。
    where = f"({where}) AND municipality_code NOT LIKE '%000'"

    # まず constraint pass する自治体を全件取得 (1917 全自治体でも 350KB)、
    # in-memory で interests に対する match_score を計算
    sql = f"""
        SELECT
            municipality_code, municipality_name, prefecture,
            population_total, youth_share_pct,
            used_apartment_median_price_man_yen,
            childcare_facility_count, kindergarten_count, nursery_count,
            medical_facility_count, medical_hospital_count, medical_clinic_count,
            emergency_shelter_count,
            population_change_pct, financial_capability_index
        FROM `{table_fqn}`
        WHERE {where}
    """  # noqa: S608

    try:
        from google.cloud import bigquery

        job_params = [
            bigquery.ArrayQueryParameter(k, v[0], v[1])
            if isinstance(v[1], list)
            else bigquery.ScalarQueryParameter(k, v[0], v[1])
            for k, v in params_dict.items()
        ]
        rows = list(
            client.query(
                sql, job_config=bigquery.QueryJobConfig(query_parameters=job_params)
            ).result(timeout=10)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_municipalities.bq_failed err=%s", exc)
        return []

    # 全行を dict 化 (BQ Row → dict for in-memory scoring)
    candidates: list[MunicipalityCandidate] = []
    for row in rows:
        row_dict = dict(row.items()) if hasattr(row, "items") else dict(row)
        # constraint 通過した行 = match_score の constraint 分も加点
        match_score, matched_interests = _calc_match_score(args.interests, row_dict, True)
        candidates.append(_row_to_candidate(row_dict, match_score, matched_interests))

    # match_score 降順、tie-break は population_total 降順
    candidates.sort(
        key=lambda c: (c.match_score, c.population_total or 0),
        reverse=True,
    )
    logger.info(
        "search_municipalities.done n_pool=%d n_returned=%d top_score=%.1f",
        len(rows),
        min(args.limit, len(candidates)),
        candidates[0].match_score if candidates else 0.0,
    )
    return candidates[: args.limit]


# ----------------------------------------------------------------------------
# Tool 2: compare_municipalities (既存 /v1/compare ロジックを Concierge 向けに簡略)
# ----------------------------------------------------------------------------


def compare_municipalities(
    municipality_codes: list[str],
    interest: Interest,
    limit: int = 3,
    bq_client: Any | None = None,
    user_id: str = "demo-25-29",
) -> ComparisonTable:
    """複数自治体の同 interest 議題を横並びで取得。

    NOTE: include_observation=True (中立観察生成) は Phase 3 で endpoint 側に
          移譲、tool 内では生のデータのみ返す (LLM 二重呼び出し回避)。

    Args:
        municipality_codes: 2-3 自治体の 5 桁コード
        interest: 比較する関心軸
        limit: 各自治体の上位件数
        bq_client: テスト用 mock 注入
        user_id: relevance score の persona

    Returns:
        ComparisonTable (neutral_observation は None で返却、endpoint 側で後付け)
    """
    client = bq_client or _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_SCORED_SPEECHES_LATEST}"

    rows: list[ComparisonRow] = []

    for code in municipality_codes:
        sql = f"""
            SELECT speech_id, title, summary, relevance_score, detail_url, meeting_date,
                   municipality_code, ANY_VALUE(name_of_meeting) AS name_of_meeting,
                   ANY_VALUE(matched_interests) AS matched_interests
            FROM `{table_fqn}`
            WHERE municipality_code = @muni
              AND user_id = @uid
              AND @interest IN UNNEST(matched_interests)
            GROUP BY speech_id, title, summary, relevance_score, detail_url, meeting_date, municipality_code
            ORDER BY relevance_score DESC, meeting_date DESC
            LIMIT @lim
        """  # noqa: S608
        try:
            from google.cloud import bigquery

            params = [
                bigquery.ScalarQueryParameter("muni", "STRING", code),
                bigquery.ScalarQueryParameter("uid", "STRING", user_id),
                bigquery.ScalarQueryParameter("interest", "STRING", interest),
                bigquery.ScalarQueryParameter("lim", "INT64", limit),
            ]
            speech_rows = list(
                client.query(
                    sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
                ).result(timeout=10)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "compare_municipalities.bq_failed muni=%s interest=%s err=%s",
                code,
                interest,
                exc,
            )
            speech_rows = []

        top_speeches = [
            {
                "speech_id": r["speech_id"],
                "title": r.get("title"),
                "summary": list(r.get("summary") or []),
                "relevance_score": r["relevance_score"],
                "detail_url": r.get("detail_url"),
            }
            for r in speech_rows
        ]

        # 自治体名/都道府県は別途 stats から取得 (簡略: empty fallback)
        rows.append(
            ComparisonRow(
                municipality_code=code,
                name=_resolve_municipality_name(code, client),
                prefecture="",
                top_speeches=top_speeches,
            )
        )

    return ComparisonTable(interest=interest, rows=rows, neutral_observation=None)


def _resolve_municipality_name(code: str, bq_client: Any) -> str:
    """municipality_stats から自治体名を取得 (BQ 1 query、cache なし)。"""
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"
    sql = f"""
        SELECT municipality_name FROM `{table_fqn}`
        WHERE municipality_code = @code LIMIT 1
    """  # noqa: S608
    try:
        from google.cloud import bigquery

        params = [bigquery.ScalarQueryParameter("code", "STRING", code)]
        rows = list(
            bq_client.query(
                sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
            ).result(timeout=5)
        )
        if rows:
            return rows[0]["municipality_name"] or code
    except Exception:  # noqa: BLE001
        pass
    return code


# ----------------------------------------------------------------------------
# Tool 3: fetch_city_dashboard
# ----------------------------------------------------------------------------


def fetch_city_dashboard(
    args: FetchCityDashboardArgs,
    bq_client: Any | None = None,
) -> CityDashboardSummary:
    """1 自治体の街ダッシュボード (stats + 関心軸別議題数 + top 議題)。

    既存 /v1/cities/{code} と同じ思想だが、Concierge から呼ぶ簡略版。
    """
    client = bq_client or _get_bq_client()
    stats_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"
    speeches_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_SCORED_SPEECHES_LATEST}"

    # 1. 統計取得
    stats: dict[str, Any] = {}
    name = args.municipality_code
    prefecture = ""
    try:
        from google.cloud import bigquery

        sql_stats = f"SELECT * FROM `{stats_fqn}` WHERE municipality_code = @code LIMIT 1"  # noqa: S608
        params = [bigquery.ScalarQueryParameter("code", "STRING", args.municipality_code)]
        rows = list(
            client.query(
                sql_stats, job_config=bigquery.QueryJobConfig(query_parameters=params)
            ).result(timeout=5)
        )
        if rows:
            row_dict = dict(rows[0].items()) if hasattr(rows[0], "items") else dict(rows[0])
            stats = {
                k: v
                for k, v in row_dict.items()
                if k
                in (
                    "population_total",
                    "youth_share_pct",
                    "elderly_share_pct",
                    "used_apartment_median_price_man_yen",
                    "childcare_facility_count",
                    "medical_facility_count",
                    "emergency_shelter_count",
                    "population_change_pct",
                )
                and v is not None
            }
            name = row_dict.get("municipality_name") or args.municipality_code
            prefecture = row_dict.get("prefecture") or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_city_dashboard.stats_failed err=%s", exc)

    # 2. interest 別議題数 + top 議題
    topic_counts: list[TopicCount] = []
    top_speeches: list[dict] = []
    try:
        from google.cloud import bigquery

        sql_speeches = f"""
            SELECT speech_id, title, summary, relevance_score, detail_url, matched_interests
            FROM `{speeches_fqn}`
            WHERE municipality_code = @code AND user_id = @uid
            ORDER BY relevance_score DESC
            LIMIT @lim
        """  # noqa: S608
        params2 = [
            bigquery.ScalarQueryParameter("code", "STRING", args.municipality_code),
            bigquery.ScalarQueryParameter("uid", "STRING", args.user_id),
            bigquery.ScalarQueryParameter("lim", "INT64", args.limit),
        ]
        speech_rows = list(
            client.query(
                sql_speeches, job_config=bigquery.QueryJobConfig(query_parameters=params2)
            ).result(timeout=10)
        )

        # 関心軸別カウント
        counter: dict[str, int] = {}
        for r in speech_rows:
            for interest in r.get("matched_interests") or []:
                counter[interest] = counter.get(interest, 0) + 1
            top_speeches.append(
                {
                    "speech_id": r["speech_id"],
                    "title": r.get("title"),
                    "summary": list(r.get("summary") or []),
                    "relevance_score": r["relevance_score"],
                    "detail_url": r.get("detail_url"),
                }
            )

        topic_counts = sorted(
            [TopicCount(interest=k, count=v) for k, v in counter.items()],  # type: ignore[arg-type]
            key=lambda t: t.count,
            reverse=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_city_dashboard.speeches_failed err=%s", exc)

    return CityDashboardSummary(
        municipality_code=args.municipality_code,
        name=name,
        prefecture=prefecture,
        stats=stats,
        topic_counts=topic_counts,
        top_speeches=top_speeches,
    )


# ----------------------------------------------------------------------------
# Tool 4: fetch_city_speeches
# ----------------------------------------------------------------------------


def fetch_city_speeches(
    args: FetchCitySpeechesArgs,
    bq_client: Any | None = None,
) -> list[ScoredSpeechSummary]:
    """1 自治体の議題を relevance 順で取得 (optional interest フィルタ)。"""
    client = bq_client or _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_SCORED_SPEECHES_LATEST}"

    interest_clause = "AND @interest IN UNNEST(matched_interests)" if args.interest else ""
    sql = f"""
        SELECT speech_id, title, summary, relevance_score, matched_interests,
               detail_url, meeting_date
        FROM `{table_fqn}`
        WHERE municipality_code = @code
          AND user_id = @uid
          {interest_clause}
        ORDER BY relevance_score DESC, meeting_date DESC
        LIMIT @lim
    """  # noqa: S608

    try:
        from google.cloud import bigquery

        params = [
            bigquery.ScalarQueryParameter("code", "STRING", args.municipality_code),
            bigquery.ScalarQueryParameter("uid", "STRING", args.user_id),
            bigquery.ScalarQueryParameter("lim", "INT64", args.limit),
        ]
        if args.interest:
            params.append(bigquery.ScalarQueryParameter("interest", "STRING", args.interest))

        rows = list(
            client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result(
                timeout=10
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_city_speeches.bq_failed err=%s", exc)
        return []

    return [
        ScoredSpeechSummary(
            speech_id=r["speech_id"],
            title=r.get("title"),
            summary=list(r.get("summary") or []),
            relevance_score=r["relevance_score"],
            matched_interests=list(r.get("matched_interests") or []),
            detail_url=r.get("detail_url"),
            meeting_date=(r["meeting_date"].isoformat() if r.get("meeting_date") else None),
        )
        for r in rows
    ]
