"""Citify FastAPI バックエンドのエントリポイント。

Cloud Run / ローカル開発 両対応の最小構成:
    - GET /health  : Cloud Run のヘルスチェック用 (常に 200)
    - GET /version : ビルド情報 (Git SHA, 環境名)

ローカル起動:
    uv run uvicorn main:app --reload

Cloud Run デプロイ:
    Dockerfile 経由で gunicorn/uvicorn が PORT 環境変数を読む。
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logger = logging.getLogger(__name__)


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

# CORS: フロントエンド (Firebase Hosting) からのアクセス許可
# 本番では CORS_ORIGINS 環境変数で限定 (例: https://citify.example.com)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class HealthResponse(BaseModel):
    """ヘルスチェックレスポンス"""

    status: str
    version: str


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Cloud Run のヘルスチェック用エンドポイント。常に 200 OK を返す。"""
    return HealthResponse(status="ok", version=app.version)


class VersionResponse(BaseModel):
    """ビルド情報レスポンス"""

    version: str
    git_sha: str | None
    env: str


@app.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    """ビルド情報を返す (Cloud Build から GIT_SHA を注入予定)。"""
    return VersionResponse(
        version=app.version,
        git_sha=os.getenv("GIT_SHA"),
        env=os.getenv("ENV", "dev"),
    )
