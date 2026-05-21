"""Citify FastAPI バックエンドのエントリポイント。

Cloud Run / ローカル開発 両対応:
    - GET /health             : Cloud Run のヘルスチェック用 (常に 200)
    - GET /version            : ビルド情報 (Git SHA, 環境名)
    - GET /v1/feed/{user_id}  : ユーザー別フィード (BQ scored_speeches_latest 経由)
    - GET /v1/speeches/{speech_id} : 1 件詳細 (BQ scored_speeches_latest 経由)

ローカル起動:
    uv run uvicorn main:app --reload --port 8080

Cloud Run デプロイ:
    Dockerfile 経由で uvicorn が PORT 環境変数を読む。
    Cloud Build trigger 'citify-api-main' で main push 自動デプロイ。
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# BQ 設定 (env で上書き可)
BQ_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "citify-dev")
BQ_DATASET_CURATED = os.getenv("BQ_DATASET_CURATED", "citify_curated")
BQ_VIEW_SCORED_LATEST = os.getenv("BQ_VIEW_SCORED_LATEST", "scored_speeches_latest")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """起動・終了処理 (将来的に DB プール初期化や Agent 初期化をここに)"""
    logger.info("citify.startup", extra={"version": app.version})
    yield
    logger.info("citify.shutdown")


app = FastAPI(
    title="Citify API",
    description="自治体議事録・プレスリリースを若者向けに翻訳して配信するマルチエージェント AI バックエンド",
    version=os.getenv("APP_VERSION", "0.1.0-dev"),
    lifespan=lifespan,
)

# CORS: フロントエンド (Firebase Hosting / localhost:3000) からのアクセス許可
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ============================================================================
# Health / Version
# ============================================================================


class HealthResponse(BaseModel):
    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Cloud Run のヘルスチェック用エンドポイント。常に 200 OK を返す。"""
    return HealthResponse(status="ok", version=app.version)


class VersionResponse(BaseModel):
    version: str
    git_sha: str | None
    env: str


@app.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    return VersionResponse(
        version=app.version,
        git_sha=os.getenv("GIT_SHA"),
        env=os.getenv("ENV", "dev"),
    )


# ============================================================================
# v1 Feed API (A-8 For You フィード用)
# ============================================================================


class FeedItem(BaseModel):
    """フィード 1 件 (frontend カード 1 枚分)。"""

    speech_id: str
    title: str | None
    summary: list[str] = Field(default_factory=list)
    detail_url: str | None = None
    meeting_date: date | None = None
    municipality_code: str | None = None
    name_of_meeting: str | None = None
    speaker_position: str | None = None
    tone: str | None = None

    # スコア breakdown
    relevance_score: int
    score_topic: int = 0
    score_age: int = 0
    score_geographic: int = 0
    score_urgency: int = 0
    matched_interests: list[str] = Field(default_factory=list)
    reasoning: str | None = None


class FeedResponse(BaseModel):
    user_id: str
    items: list[FeedItem]
    total: int


def _get_bq_client():
    """遅延 import (テストで mock 注入可能、起動高速化)。"""
    from google.cloud import bigquery

    return bigquery.Client(project=BQ_PROJECT)


def _row_to_feed_item(row: Any) -> FeedItem:
    """BQ row (Mapping) → FeedItem。"""
    return FeedItem(
        speech_id=row["speech_id"],
        title=row.get("title"),
        summary=list(row.get("summary") or []),
        detail_url=row.get("detail_url"),
        meeting_date=row.get("meeting_date"),
        municipality_code=row.get("municipality_code"),
        name_of_meeting=row.get("name_of_meeting"),
        speaker_position=row.get("speaker_position"),
        tone=row.get("tone"),
        relevance_score=int(row.get("relevance_score") or 0),
        score_topic=int(row.get("score_topic") or 0),
        score_age=int(row.get("score_age") or 0),
        score_geographic=int(row.get("score_geographic") or 0),
        score_urgency=int(row.get("score_urgency") or 0),
        matched_interests=list(row.get("matched_interests") or []),
        reasoning=row.get("reasoning"),
    )


@app.get("/v1/feed/{user_id}", response_model=FeedResponse)
async def get_feed(
    user_id: str,
    min_relevance: int = Query(default=0, ge=0, le=100, description="フィルタ閾値 (default 0)"),
    limit: int = Query(default=20, ge=1, le=100),
) -> FeedResponse:
    """ユーザー別フィード取得 (BQ scored_speeches_latest 経由、relevance_score DESC)。

    Args:
        user_id: ペルソナ ID (デフォルト Cloud Run worker は 'demo-25-29')
        min_relevance: 0-100 スコア閾値、default 0 (全件)
        limit: 取得上限件数
    """
    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_VIEW_SCORED_LATEST}"
    sql = f"""
        SELECT
            speech_id, title, summary, detail_url, meeting_date,
            municipality_code, name_of_meeting, speaker_position, tone,
            relevance_score, score_topic, score_age, score_geographic, score_urgency,
            matched_interests, reasoning
        FROM `{table_fqn}`
        WHERE user_id = @user_id
          AND relevance_score >= @min_relevance
        ORDER BY relevance_score DESC, ingested_at DESC
        LIMIT @limit
    """  # noqa: S608 (table_fqn is server-controlled via env)

    from google.cloud import bigquery

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
            bigquery.ScalarQueryParameter("min_relevance", "INT64", min_relevance),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
    )
    try:
        rows = list(client.query(sql, job_config=job_config).result(timeout=10))
    except Exception as exc:  # noqa: BLE001
        logger.exception("feed.bq_query_failed user_id=%s err=%s", user_id, exc)
        raise HTTPException(status_code=500, detail=f"BQ query failed: {exc!s}") from exc

    items = [_row_to_feed_item(r) for r in rows]
    logger.info("feed.served user_id=%s n=%d", user_id, len(items))
    return FeedResponse(user_id=user_id, items=items, total=len(items))


@app.get("/v1/speeches/{speech_id}", response_model=FeedItem)
async def get_speech(
    speech_id: str,
    user_id: str = Query(..., description="ペルソナ ID (採点コンテキスト)"),
) -> FeedItem:
    """1 件の speech 詳細を取得 (relevance_score 含む)。"""
    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_VIEW_SCORED_LATEST}"
    sql = f"""
        SELECT
            speech_id, title, summary, detail_url, meeting_date,
            municipality_code, name_of_meeting, speaker_position, tone,
            relevance_score, score_topic, score_age, score_geographic, score_urgency,
            matched_interests, reasoning
        FROM `{table_fqn}`
        WHERE speech_id = @speech_id AND user_id = @user_id
        LIMIT 1
    """  # noqa: S608

    from google.cloud import bigquery

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("speech_id", "STRING", speech_id),
            bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
        ]
    )
    try:
        rows = list(client.query(sql, job_config=job_config).result(timeout=10))
    except Exception as exc:  # noqa: BLE001
        logger.exception("speech.bq_query_failed speech_id=%s err=%s", speech_id, exc)
        raise HTTPException(status_code=500, detail=f"BQ query failed: {exc!s}") from exc

    if not rows:
        raise HTTPException(
            status_code=404, detail=f"speech_id={speech_id} not found for user_id={user_id}"
        )

    return _row_to_feed_item(rows[0])
