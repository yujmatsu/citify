"""Watcher エージェントが自律的に呼ぶ BQ ツール群 (TASK-WATCHER Slice 1)。

ADK FunctionTool は関数シグネチャ + docstring からツールスキーマを生成するため、
各ツールは「型ヒント + 日本語 docstring 付きの素の関数」として定義する。
LLM がこの説明を読んで *自分で呼ぶか判断* する。

BQ クライアントは lazy init (concierge/tools.py と同パターン)。テストでは
`set_bq_client_factory` で mock を注入できる。
"""

from __future__ import annotations

import bisect
import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# 街カルテ(/v1/cities/compare-stats)と同一定義の指標 (列, 日本語ラベル, 良い方向)。
# compare_towns はこの全国順位を付与し、エージェントとカルテの判断レンズを揃える。
_RANKED_METRICS: tuple[tuple[str, str, str], ...] = (
    ("financial_capability_index", "財政力", "higher"),
    ("taxable_income_per_capita_yen", "所得", "higher"),
    ("homeownership_rate_pct", "持ち家", "higher"),
    ("real_debt_service_ratio_pct", "財政健全度", "lower"),
    ("crime_rate_per_1000", "治安", "lower"),
    ("doctors_per_100k", "医療", "higher"),
    ("unemployment_rate_pct", "雇用", "lower"),
    ("dwelling_area_sqm", "住まい", "higher"),
)

BQ_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "citify-dev")
BQ_DATASET_CURATED = os.getenv("BQ_DATASET_CURATED", "citify_curated")
BQ_TABLE_SCORED = os.getenv("BQ_TABLE_SCORED_SPEECHES_LATEST", "scored_speeches_latest")
BQ_TABLE_POP_SERIES = "municipality_population_series"
BQ_TABLE_STATS = os.getenv("BQ_TABLE_STATS", "municipality_stats")
MAX_COMPARE_TOWNS = 5

# テスト用に差し替え可能な client factory (None なら本物の BQ client)
_bq_client_factory: Callable[[], Any] | None = None


def set_bq_client_factory(factory: Callable[[], Any] | None) -> None:
    """テスト用: BQ client を返す factory を注入 (None で解除)。"""
    global _bq_client_factory
    _bq_client_factory = factory


def _get_bq_client() -> Any:
    if _bq_client_factory is not None:
        return _bq_client_factory()
    from google.cloud import bigquery

    return bigquery.Client(project=BQ_PROJECT)


def search_speeches(municipality_code: str, user_id: str, interest: str = "") -> list[dict]:
    """指定した街の議題(議事録・プレス)を関連度順に取得する。

    街で今どんな議題が議論・決定されているかを調べたい時に使う。

    Args:
        municipality_code: 5 桁の市区町村コード (例: "11227")
        user_id: 採点コンテキストのユーザー ID (例: "demo-40-49")
        interest: 関心軸で絞る場合に指定 (例: "子育て"。空なら全件)

    Returns:
        議題の list。各要素は speech_id / title / summary / relevance_score /
        matched_interests / detail_url / meeting_date を含む。失敗時は空 list。
    """
    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_SCORED}"
    interest_clause = "AND @interest IN UNNEST(matched_interests)" if interest else ""
    sql = f"""
        SELECT speech_id, title, summary, relevance_score, matched_interests,
               detail_url, meeting_date
        FROM `{table_fqn}`
        WHERE municipality_code = @code AND user_id = @uid
          {interest_clause}
        ORDER BY relevance_score DESC, meeting_date DESC
        LIMIT 15
    """  # noqa: S608
    try:
        from google.cloud import bigquery

        params = [
            bigquery.ScalarQueryParameter("code", "STRING", municipality_code),
            bigquery.ScalarQueryParameter("uid", "STRING", user_id),
        ]
        if interest:
            params.append(bigquery.ScalarQueryParameter("interest", "STRING", interest))
        rows = client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
        ).result(timeout=10)
        return [
            {
                "speech_id": r["speech_id"],
                "title": r["title"],
                "summary": list(r["summary"]) if r["summary"] else [],
                "relevance_score": r["relevance_score"],
                "matched_interests": list(r["matched_interests"] or []),
                "detail_url": r["detail_url"],
                "meeting_date": str(r["meeting_date"]) if r["meeting_date"] else None,
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.search_speeches.bq_failed code=%s err=%s", municipality_code, exc)
        return []


def fetch_population_trend(municipality_code: str) -> dict:
    """指定した街の人口推移(2000-2070、実績+将来推計)を取得する。

    街の将来(人口が増えるか減るか)を踏まえて議題の重要度を判断したい時に使う。

    Args:
        municipality_code: 5 桁の市区町村コード (例: "11227")

    Returns:
        {"series": [{"year","population","source"}], "latest_actual_year",
         "projection_2070_change_pct"} 形式。失敗・データ無しは series 空。
    """
    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_POP_SERIES}"
    sql = f"""
        SELECT year, population, source FROM `{table_fqn}`
        WHERE municipality_code = @code ORDER BY year
    """  # noqa: S608
    try:
        from google.cloud import bigquery

        params = [bigquery.ScalarQueryParameter("code", "STRING", municipality_code)]
        rows = list(
            client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result(
                timeout=10
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.population_trend.bq_failed code=%s err=%s", municipality_code, exc)
        return {"series": [], "latest_actual_year": None, "projection_2070_change_pct": None}

    series = [
        {"year": int(r["year"]), "population": r["population"], "source": r["source"]}
        for r in rows
        if r["population"] is not None
    ]
    census = [p for p in series if p["source"] == "census"]
    proj = [p for p in series if p["source"] == "projection"]
    change = None
    if census and proj:
        base = census[-1]["population"]
        last = proj[-1]["population"]
        if base:
            change = round((last - base) / base * 100.0, 1)
    return {
        "series": series,
        "latest_actual_year": max((p["year"] for p in census), default=None),
        "projection_2070_change_pct": change,
    }


def fetch_topic_trend(municipality_code: str, interest: str = "") -> dict:
    """指定した街で、ある関心テーマの議題が時系列で増えているか減っているかを調べる。

    「この街は最近この話題を活発に議論し始めたか?」という"動きの方向"を知りたい時に使う。
    直近6か月と、その前6か月の議題件数を比べて傾向を判定する。

    Args:
        municipality_code: 5 桁の市区町村コード (例: "11227")
        interest: 関心軸 (例: "子育て"。空なら全テーマ合算)

    Returns:
        {"series": [{"year_month","count"}], "recent_6m": int, "prev_6m": int,
         "trend": "increasing"|"flat"|"decreasing"|"unknown"} 形式。データ無しは series 空・trend unknown。
    """
    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_SCORED}"
    interest_clause = "AND @interest IN UNNEST(matched_interests)" if interest else ""
    sql = f"""
        SELECT FORMAT_DATE('%Y-%m', meeting_date) AS year_month,
               COUNT(DISTINCT speech_id) AS cnt
        FROM `{table_fqn}`
        WHERE municipality_code = @code AND meeting_date IS NOT NULL
          {interest_clause}
        GROUP BY year_month
        ORDER BY year_month
    """  # noqa: S608
    try:
        from google.cloud import bigquery

        params = [bigquery.ScalarQueryParameter("code", "STRING", municipality_code)]
        if interest:
            params.append(bigquery.ScalarQueryParameter("interest", "STRING", interest))
        rows = list(
            client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result(
                timeout=10
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.topic_trend.bq_failed code=%s err=%s", municipality_code, exc)
        return {"series": [], "recent_6m": 0, "prev_6m": 0, "trend": "unknown"}

    series = [{"year_month": r["year_month"], "count": int(r["cnt"])} for r in rows]
    # 直近6か月 vs その前6か月 (年月文字列の昇順末尾を使う)
    counts = [s["count"] for s in series]
    recent_6m = sum(counts[-6:])
    prev_6m = sum(counts[-12:-6])
    if not series:
        trend = "unknown"
    elif recent_6m > prev_6m * 1.2:
        trend = "increasing"
    elif recent_6m < prev_6m * 0.8:
        trend = "decreasing"
    else:
        trend = "flat"
    return {"series": series, "recent_6m": recent_6m, "prev_6m": prev_6m, "trend": trend}


def compare_towns(municipality_codes: list[str]) -> list[dict]:
    """複数の街の主要統計を並べて比較する。街選びの中核ツール。

    ウォッチ中の街(住む街・気になる街)同士を、人口規模・年齢構成・将来人口・
    出生率・住居コスト・子育て/医療施設で横断比較したい時に使う。

    Args:
        municipality_codes: 比較する 5 桁市区町村コードの list (最大 5 件)

    Returns:
        街ごとの dict の list。各 dict は以下を含む(値が無い項目は null):
        municipality_code / population_total / youth_share_pct(15-29歳割合) /
        elderly_share_pct(65歳以上割合) / birth_rate_per_1000(人口千人あたり出生) /
        population_change_pct(直近変化) /
        used_apartment_median_price_man_yen(中古マンション中央値・万円) /
        childcare_facility_count(子育て施設数) /
        financial_capability_index(財政力指数、1.0超で財政的余裕) /
        real_debt_service_ratio_pct(実質公債費比率%、借金の重さ) /
        taxable_income_per_capita_yen(1人当たり課税対象所得・円) /
        homeownership_rate_pct(持ち家比率%) / crime_rate_per_1000(刑法犯認知件数・人口千対) /
        doctors_per_100k(医師数・人口10万対) / unemployment_rate_pct(完全失業率%) /
        dwelling_area_sqm(1住宅延べ面積・㎡)。
        さらに各街に national_rank: {指標ラベル: "上位X%"} を付与する(街カルテと同じ全国順位)。
        **生値の高低だけで良し悪しを断定せず、この national_rank で「全国で高い/低い」を評価すること。**
        失敗時は空 list。値が無い項目は null (財政指標は特別区等で欠損あり)。
    """
    codes = [c for c in municipality_codes if c][:MAX_COMPARE_TOWNS]
    if not codes:
        return []
    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"
    sql = f"""
        SELECT municipality_code, population_total,
               youth_share_pct, elderly_share_pct, birth_rate_per_1000,
               population_change_pct,
               used_apartment_median_price_man_yen, childcare_facility_count,
               financial_capability_index, real_debt_service_ratio_pct,
               taxable_income_per_capita_yen, homeownership_rate_pct,
               crime_rate_per_1000,
               doctors_per_100k, unemployment_rate_pct, dwelling_area_sqm
        FROM `{table_fqn}`
        WHERE municipality_code IN UNNEST(@codes)
    """  # noqa: S608
    cols = (
        "municipality_code",
        "population_total",
        "youth_share_pct",
        "elderly_share_pct",
        "birth_rate_per_1000",
        "population_change_pct",
        "used_apartment_median_price_man_yen",
        "childcare_facility_count",
        "financial_capability_index",
        "real_debt_service_ratio_pct",
        "taxable_income_per_capita_yen",
        "homeownership_rate_pct",
        "crime_rate_per_1000",
        "doctors_per_100k",
        "unemployment_rate_pct",
        "dwelling_area_sqm",
    )
    try:
        from google.cloud import bigquery

        params = [bigquery.ArrayQueryParameter("codes", "STRING", codes)]
        rows = client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
        ).result(timeout=10)
        towns = [{c: r.get(c) for c in cols} for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.compare_towns.bq_failed codes=%s err=%s", codes, exc)
        return []

    # 各街に全国順位 national_rank を付与 (街カルテと同じレンズ。失敗時は graceful に省略)
    national = _load_national_distributions(client)
    for town in towns:
        ranks: dict[str, str] = {}
        for col, label, direction in _RANKED_METRICS:
            top_pct = _national_top_pct(town.get(col), national.get(col, ()), direction)
            if top_pct is not None:
                ranks[label] = f"上位{top_pct}%"
        town["national_rank"] = ranks
    return towns


def _load_national_distributions(client: Any) -> dict[str, list[float]]:
    """全市区町村の _RANKED_METRICS 各列をソート済み配列で返す (全国順位算出用)。

    街カルテ(_load_national_fiscal)と同じ母集合 (00000 と都道府県/政令市集計を除外)。
    null は除外。失敗時は空配列 (national_rank は付かないだけで raw 値は返る)。
    """
    cols = [m[0] for m in _RANKED_METRICS]
    arrays: dict[str, list[float]] = {c: [] for c in cols}
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"
    sql = (  # noqa: S608 — 列名は固定リテラル
        f"SELECT {', '.join(cols)} FROM `{table_fqn}` "
        "WHERE municipality_code != '00000' "
        "AND SUBSTR(municipality_code, 3) NOT IN ('000', '001', '002')"
    )
    try:
        for r in client.query(sql).result(timeout=15):
            for c in cols:
                v = r.get(c)
                if v is not None:
                    arrays[c].append(float(v))
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.compare_towns.national_load_failed err=%s", exc)
        return {c: [] for c in cols}
    for c in cols:
        arrays[c].sort()
    return arrays


def _national_top_pct(value: Any, sorted_vals: list[float], direction: str) -> int | None:
    """value の全国「上位X%」(1=最上位)。街カルテ compare-stats と同じ算出方法。"""
    if value is None or not sorted_vals:
        return None
    n = len(sorted_vals)
    v = float(value)
    if direction == "higher":
        rank = n - bisect.bisect_right(sorted_vals, v) + 1
    else:
        rank = bisect.bisect_left(sorted_vals, v) + 1
    rank = max(1, min(rank, n))
    return max(1, round(rank / n * 100))
