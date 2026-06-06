"""Watcher エージェントが自律的に呼ぶ BQ ツール群 (TASK-WATCHER Slice 1)。

ADK FunctionTool は関数シグネチャ + docstring からツールスキーマを生成するため、
各ツールは「型ヒント + 日本語 docstring 付きの素の関数」として定義する。
LLM がこの説明を読んで *自分で呼ぶか判断* する。

BQ クライアントは lazy init (concierge/tools.py と同パターン)。テストでは
`set_bq_client_factory` で mock を注入できる。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

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


def compare_towns(municipality_codes: list[str]) -> list[dict]:
    """複数の街の主要統計を並べて比較する。

    ウォッチ中の街(住む街・気になる街)同士を、人口・家賃・子育て・医療・人口増減で
    横断比較したい時に使う。

    Args:
        municipality_codes: 比較する 5 桁市区町村コードの list (最大 5 件)

    Returns:
        街ごとの dict の list。各 dict は municipality_code / population_total /
        used_apartment_median_price_man_yen / childcare_facility_count /
        medical_facility_count / population_change_pct を含む。失敗時は空 list。
    """
    codes = [c for c in municipality_codes if c][:MAX_COMPARE_TOWNS]
    if not codes:
        return []
    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"
    sql = f"""
        SELECT municipality_code, population_total,
               used_apartment_median_price_man_yen, childcare_facility_count,
               medical_facility_count, population_change_pct
        FROM `{table_fqn}`
        WHERE municipality_code IN UNNEST(@codes)
    """  # noqa: S608
    try:
        from google.cloud import bigquery

        params = [bigquery.ArrayQueryParameter("codes", "STRING", codes)]
        rows = client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
        ).result(timeout=10)
        return [
            {
                "municipality_code": r["municipality_code"],
                "population_total": r["population_total"],
                "used_apartment_median_price_man_yen": r["used_apartment_median_price_man_yen"],
                "childcare_facility_count": r["childcare_facility_count"],
                "medical_facility_count": r["medical_facility_count"],
                "population_change_pct": r["population_change_pct"],
            }
            for r in rows
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.compare_towns.bq_failed codes=%s err=%s", codes, exc)
        return []
