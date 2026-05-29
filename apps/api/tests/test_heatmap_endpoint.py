"""GET /v1/heatmap endpoint のユニットテスト (Plan X)。

テスト戦略:
    - HeatmapAdvisor (`_get_heatmap_advisor`) を MagicMock で差し替え
    - BQ query (`_fetch_heatmap_bq`) を MagicMock で差し替え (BQ 接続を回避)
    - 200 / advisor LLM 失敗 graceful / BQ 失敗 500 / 集計行フィルタ確認
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _stub_firestore_module() -> None:
    if "google.cloud.firestore" not in sys.modules:
        stub = types.ModuleType("google.cloud.firestore")
        stub.SERVER_TIMESTAMP = object()  # type: ignore[attr-defined]
        stub.Client = MagicMock()  # type: ignore[attr-defined]
        stub.Increment = MagicMock()  # type: ignore[attr-defined]
        sys.modules["google.cloud.firestore"] = stub


def _mock_advice(
    metric_column: str = "used_apartment_median_price_man_yen",
    direction: str = "lower_is_better",
    source: str = "llm",
):
    """HeatmapAdvice mock を組み立て (Pydantic instance)。"""
    from agents.heatmap_advisor.schema import HeatmapAdvice

    return HeatmapAdvice(
        metric_column=metric_column,
        metric_label_ja="中古マンション中央値",
        direction=direction,  # type: ignore[arg-type]
        unit="万円",
        reasoning="20 代後半の住居検討では価格水準が直接効きます。",
        persona_summary="25-29 / 住居",
        source=source,  # type: ignore[arg-type]
    )


def _setup_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    advice=None,
    pref_values=None,
    top_munis=None,
    advisor_exc: Exception | None = None,
    bq_exc: Exception | None = None,
) -> TestClient:
    """endpoint 依存を全 mock 化して TestClient を返す。"""
    from apps.api import main as api_main
    from apps.api.main import _HEATMAP_CACHE

    _HEATMAP_CACHE.clear()  # cache 残骸を消す

    # advisor mock
    mock_advisor = MagicMock()
    if advisor_exc is not None:
        mock_advisor.suggest_metric.side_effect = advisor_exc
    else:
        mock_advisor.suggest_metric.return_value = advice or _mock_advice()
    monkeypatch.setattr(api_main, "_get_heatmap_advisor", lambda: mock_advisor)

    # BQ mock
    def _mock_bq(metric_column: str, direction: str):
        if bq_exc is not None:
            raise bq_exc
        return (
            pref_values
            or [
                {
                    "prefecture_code": "13",
                    "prefecture_name": "東京都",
                    "metric_median": 4500.0,
                    "muni_count": 62,
                    "rank": 1,
                },
                {
                    "prefecture_code": "01",
                    "prefecture_name": "北海道",
                    "metric_median": 800.0,
                    "muni_count": 179,
                    "rank": 2,
                },
            ],
            top_munis
            or [
                {
                    "prefecture_code": "13",
                    "municipalities": [
                        {
                            "municipality_code": "13104",
                            "municipality_name": "新宿区",
                            "metric_value": 5500.0,
                        }
                    ],
                }
            ],
        )

    monkeypatch.setattr(api_main, "_fetch_heatmap_bq", _mock_bq)
    return TestClient(api_main.app)


# ============================================================================
# 1) 200 + advice/prefecture_values/top_municipalities 構造
# ============================================================================


def test_heatmap_returns_200_with_full_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """正常 path: advice + prefecture_values + top_municipalities が返る。"""
    client = _setup_endpoint(monkeypatch)

    response = client.get(
        "/v1/heatmap",
        params={
            "user_id": "demo",
            "age_group": "25-29",
            "interests": "住居,子育て",
            "focus_interest": "住居",
        },
    )
    assert response.status_code == 200
    body = response.json()

    assert "advice" in body
    assert body["advice"]["metric_column"] == "used_apartment_median_price_man_yen"
    assert body["advice"]["source"] == "llm"
    assert "prefecture_values" in body
    assert body["prefecture_values"][0]["prefecture_code"] == "13"
    assert "top_municipalities" in body


# ============================================================================
# 2) advisor LLM 失敗時に rule-based fallback (source="rule_based") を透過
# ============================================================================


def test_heatmap_advisor_llm_failure_graceful(monkeypatch: pytest.MonkeyPatch) -> None:
    """HeatmapAdvisor が rule_based fallback を返したら endpoint は 200 で透過。"""
    fallback_advice = _mock_advice(source="rule_based")
    client = _setup_endpoint(monkeypatch, advice=fallback_advice)

    response = client.get(
        "/v1/heatmap",
        params={"focus_interest": "住居", "user_id": "anon"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["advice"]["source"] == "rule_based"


# ============================================================================
# 3) BQ クラッシュ → 500 graceful
# ============================================================================


def test_heatmap_bq_failure_returns_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """BQ query が例外を投げたら 500 graceful。"""
    client = _setup_endpoint(
        monkeypatch,
        bq_exc=RuntimeError("BQ table not found"),
    )

    response = client.get(
        "/v1/heatmap",
        params={"focus_interest": "住居", "user_id": "anon"},
    )
    assert response.status_code == 500
    assert "BQ heatmap query failed" in response.json()["detail"]


# ============================================================================
# 4) 集計行 (XX000) フィルタ: _fetch_heatmap_bq 内 SQL が NOT LIKE '%000' を含む (Reviewer Critical #1)
# ============================================================================


def test_heatmap_bq_query_filters_aggregate_rows() -> None:
    """生 _fetch_heatmap_bq の SQL に NOT LIKE '%000' フィルタが含まれることを確認。

    BQ client を mock し、生成される SQL 文字列を検証する。
    """
    from unittest.mock import patch

    from apps.api import main as api_main

    captured_sqls: list[str] = []

    def _capture_query(sql, job_config=None):  # noqa: ARG001
        captured_sqls.append(sql)
        result = MagicMock()
        result.result.return_value = []
        return result

    mock_bq_client = MagicMock()
    mock_bq_client.query.side_effect = _capture_query

    with patch.object(api_main, "_get_bq_client", return_value=mock_bq_client):
        api_main._fetch_heatmap_bq(
            metric_column="used_apartment_median_price_man_yen",
            direction="lower_is_better",
        )

    assert len(captured_sqls) == 2  # 2 query (pref + top)
    for sql in captured_sqls:
        assert "NOT LIKE '%000'" in sql, f"集計行フィルタ欠落: {sql[:200]}"
        assert "!= '00000'" in sql, f"国会フィルタ欠落: {sql[:200]}"


# ============================================================================
# 5) SQL injection guard: 許可リストに無い metric_column は ValueError
# ============================================================================


def test_heatmap_bq_rejects_unknown_metric_column() -> None:
    """metric_column が allowlist になければ ValueError (SQL injection 防止)。"""
    from apps.api import main as api_main

    with pytest.raises(ValueError, match="metric_column not in allowlist"):
        api_main._fetch_heatmap_bq(
            metric_column="DROP TABLE municipality_stats",
            direction="lower_is_better",
        )


# ============================================================================
# 6) direction enum guard
# ============================================================================


def test_heatmap_bq_rejects_invalid_direction() -> None:
    """direction が enum 外なら ValueError。"""
    from apps.api import main as api_main

    with pytest.raises(ValueError, match="invalid direction"):
        api_main._fetch_heatmap_bq(
            metric_column="used_apartment_median_price_man_yen",
            direction="random_string",
        )


# ============================================================================
# 7) Pydantic validation error: focus_interest 必須
# ============================================================================


def test_heatmap_returns_422_when_focus_interest_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """focus_interest query が欠けていたら 422。"""
    client = _setup_endpoint(monkeypatch)

    response = client.get("/v1/heatmap", params={"user_id": "demo"})
    assert response.status_code == 422
