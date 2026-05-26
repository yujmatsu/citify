"""Citify FastAPI バックエンドのエントリポイント。

Cloud Run / ローカル開発 両対応:
    - GET /health             : Cloud Run のヘルスチェック用 (常に 200)
    - GET /version            : ビルド情報 (Git SHA, 環境名)
    - GET /v1/feed/{user_id}  : ユーザー別フィード (BQ scored_speeches_latest 経由)
    - GET /v1/speeches/{speech_id} : 1 件詳細 (BQ scored_speeches_latest 経由)
    - GET /v1/speeches/{speech_id}/related : RAG 関連議題 (Vertex AI corpus)
    - GET|PUT|DELETE /v1/speeches/{speech_id}/reaction : リアクション永続化 (Firestore)
    - GET /v1/speeches/{speech_id}/reactions/summary : リアクション集計 (Phase X+1)

ローカル起動:
    uv run uvicorn main:app --reload --port 8080

Cloud Run デプロイ:
    Dockerfile 経由で uvicorn が PORT 環境変数を読む。
    Cloud Build trigger 'citify-api-main' で main push 自動デプロイ。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# In-memory TTL cache (Phase Q パフォーマンスチューニング)
# 外部依存なし、軽量。Cloud Run 単一インスタンスでの per-process キャッシュ。
# ============================================================================


class _TTLCache:
    """TTL 付きの dict-like キャッシュ (FIFO eviction)。

    process 内のみ有効。Cloud Run の min-instances=1 と組み合わせて
    BQ/RAG 呼び出しの体感速度を改善する目的。
    """

    def __init__(self, maxsize: int = 128, ttl_sec: float = 60.0) -> None:
        self.maxsize = maxsize
        self.ttl_sec = ttl_sec
        self._data: dict[Any, tuple[Any, float]] = {}

    def get(self, key: Any) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        value, expire_at = item
        if time.monotonic() > expire_at:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: Any, value: Any) -> None:
        if len(self._data) >= self.maxsize:
            # FIFO で最古を 1 件削除 (LRU ほど厳密でなくてよい、process scope)
            oldest = next(iter(self._data), None)
            if oldest is not None:
                self._data.pop(oldest, None)
        self._data[key] = (value, time.monotonic() + self.ttl_sec)

    def clear(self) -> None:
        self._data.clear()


# /v1/feed/{user_id} (60 秒 TTL): 同 user_id × min_relevance × limit の組み合わせ
_FEED_CACHE = _TTLCache(maxsize=64, ttl_sec=60.0)
# /v1/speeches/{id}/related (1 時間 TTL): RAG 結果は安定なので長めに
_RELATED_CACHE = _TTLCache(maxsize=256, ttl_sec=3600.0)

# BQ 設定 (env で上書き可)
BQ_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "citify-dev")
BQ_DATASET_CURATED = os.getenv("BQ_DATASET_CURATED", "citify_curated")
BQ_VIEW_SCORED_LATEST = os.getenv("BQ_VIEW_SCORED_LATEST", "scored_speeches_latest")

# RAG 設定 (Phase D で作成した Vertex AI corpus)
# RAG_CORPUS_NAME を直接指定するか、起動時に display_name で lookup
RAG_CORPUS_NAME = os.getenv("RAG_CORPUS_NAME") or None
RAG_CORPUS_DISPLAY_NAME = os.getenv("RAG_CORPUS_DISPLAY_NAME", "citify-kokkai-speeches")
RAG_LOCATION = os.getenv("RAG_LOCATION", "us-central1")

# Firestore 設定 (Phase X リアクション永続化 + Phase X+1 集計)
FIRESTORE_COLLECTION_REACTIONS = os.getenv("FIRESTORE_COLLECTION_REACTIONS", "reactions")
FIRESTORE_COLLECTION_REACTION_COUNTS = os.getenv(
    "FIRESTORE_COLLECTION_REACTION_COUNTS", "reaction_counts"
)
ALLOWED_REACTIONS = ("👍", "🤔", "😢", "🔥")


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
    allow_methods=["GET", "POST", "PUT", "DELETE"],
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
    response: Response,
    min_relevance: int = Query(default=0, ge=0, le=100, description="フィルタ閾値 (default 0)"),
    limit: int = Query(default=20, ge=1, le=100),
) -> FeedResponse:
    """ユーザー別フィード取得 (BQ scored_speeches_latest 経由、relevance_score DESC)。

    Args:
        user_id: ペルソナ ID (デフォルト Cloud Run worker は 'demo-25-29')
        min_relevance: 0-100 スコア閾値、default 0 (全件)
        limit: 取得上限件数
    """
    # Phase Q: ブラウザ HTTP cache 用 header (60 秒、SWR 5 分)
    response.headers["Cache-Control"] = (
        "public, max-age=60, s-maxage=60, stale-while-revalidate=300"
    )

    # Phase Q: in-memory cache (60 秒 TTL) — 同 user_id × params の連続リクエストを高速化
    cache_key = ("feed", user_id, min_relevance, limit)
    cached = _FEED_CACHE.get(cache_key)
    if cached is not None:
        logger.info("feed.cache_hit user_id=%s", user_id)
        return cached

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
    response = FeedResponse(user_id=user_id, items=items, total=len(items))
    _FEED_CACHE.set(cache_key, response)
    logger.info("feed.served user_id=%s n=%d cached=true", user_id, len(items))
    return response


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


# ============================================================================
# v1 RAG (関連議題、A-9 詳細ビュー用)
# ============================================================================


class RelatedContext(BaseModel):
    """RAG 検索で hit した関連発言 1 件 (chunk + 引用)。"""

    text: str = Field(description="検索で hit した chunk のテキスト本文 (一部抜粋)")
    source_uri: str = Field(default="", description="原典 URI (gs:// または https://)")
    distance: float | None = Field(
        default=None, description="cosine distance (0=完全一致, 1=無関連)"
    )


class RelatedResponse(BaseModel):
    """/v1/speeches/{speech_id}/related のレスポンス。"""

    speech_id: str
    query_text: str = Field(description="RAG にかけた query 文字列 (title + summary)")
    items: list[RelatedContext]
    corpus_used: str | None = Field(default=None, description="使用した RAG corpus 名 (debug)")


# Module-level cache: 起動毎に corpus resource name を引くと遅いので 1 度だけ lookup
_rag_corpus_cache: str | None = None


def _resolve_rag_corpus_name() -> str | None:
    """env RAG_CORPUS_NAME を優先、なければ display_name で lookup (1 回キャッシュ)。

    Returns:
        corpus resource name (例: projects/citify-dev/locations/us-central1/ragCorpora/123)
        または None (corpus 未構築時)
    """
    global _rag_corpus_cache
    if _rag_corpus_cache:
        return _rag_corpus_cache

    if RAG_CORPUS_NAME:
        _rag_corpus_cache = RAG_CORPUS_NAME
        return _rag_corpus_cache

    # 起動毎に lookup (遅延 import)
    try:
        from rag.corpus import get_corpus_by_display_name

        corpus = get_corpus_by_display_name(
            project_id=BQ_PROJECT,
            display_name=RAG_CORPUS_DISPLAY_NAME,
            location=RAG_LOCATION,
        )
        if corpus is None:
            logger.warning(
                "rag.corpus_not_found display_name=%s location=%s",
                RAG_CORPUS_DISPLAY_NAME,
                RAG_LOCATION,
            )
            return None
        _rag_corpus_cache = corpus.name
        logger.info("rag.corpus_resolved name=%s", _rag_corpus_cache)
        return _rag_corpus_cache
    except Exception as exc:  # noqa: BLE001
        logger.exception("rag.corpus_lookup_failed err=%s", exc)
        return None


@app.get("/v1/speeches/{speech_id}/related", response_model=RelatedResponse)
async def get_related_speeches(
    speech_id: str,
    response: Response,
    user_id: str = Query(..., description="ペルソナ ID (元 speech 取得コンテキスト)"),
    limit: int = Query(default=3, ge=1, le=10),
) -> RelatedResponse:
    """1 speech から RAG で関連発言を取得 (国会会議録 corpus を semantic search)。

    Flow:
        1. BQ scored_speeches_latest から元 speech の title + summary を取得
        2. それらを連結して RAG query 文字列に
        3. Vertex AI RAG corpus に retrieval_query
        4. top-K chunk を返す
    """
    # Phase Q: ブラウザ HTTP cache 用 header (1 時間、SWR 1 日)
    response.headers["Cache-Control"] = (
        "public, max-age=3600, s-maxage=3600, stale-while-revalidate=86400"
    )

    # Phase Q: in-memory cache (1 時間 TTL) — RAG retrieval は重い (~2-5 秒)、結果は安定
    cache_key = ("related", speech_id, user_id, limit)
    cached = _RELATED_CACHE.get(cache_key)
    if cached is not None:
        logger.info("related.cache_hit speech_id=%s", speech_id)
        return cached

    # 1. 元 speech の title + summary 取得
    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_VIEW_SCORED_LATEST}"
    sql = f"""
        SELECT title, summary
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
        logger.exception("related.bq_query_failed speech_id=%s err=%s", speech_id, exc)
        raise HTTPException(status_code=500, detail=f"BQ query failed: {exc!s}") from exc

    if not rows:
        raise HTTPException(
            status_code=404, detail=f"speech_id={speech_id} not found for user_id={user_id}"
        )

    row = rows[0]
    title = (row.get("title") or "").strip()
    summary_lines = list(row.get("summary") or [])
    query_text = " ".join([title, *summary_lines]).strip()

    if not query_text:
        empty = RelatedResponse(speech_id=speech_id, query_text="", items=[], corpus_used=None)
        _RELATED_CACHE.set(cache_key, empty)
        return empty

    # 2. RAG corpus を解決
    corpus_name = _resolve_rag_corpus_name()
    if not corpus_name:
        # corpus 未構築時は空配列 (frontend は placeholder 表示)
        logger.warning(
            "related.no_corpus speech_id=%s (RAG_CORPUS_NAME env or display_name lookup failed)",
            speech_id,
        )
        no_corpus = RelatedResponse(
            speech_id=speech_id, query_text=query_text, items=[], corpus_used=None
        )
        _RELATED_CACHE.set(cache_key, no_corpus)
        return no_corpus

    # 3. retrieval_query
    try:
        from rag.corpus import retrieval_query

        contexts = retrieval_query(
            corpus_name=corpus_name,
            text=query_text,
            top_k=limit,
            project_id=BQ_PROJECT,
            location=RAG_LOCATION,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("related.rag_query_failed speech_id=%s err=%s", speech_id, exc)
        raise HTTPException(status_code=500, detail=f"RAG query failed: {exc!s}") from exc

    items = [
        RelatedContext(
            text=ctx.text,
            source_uri=ctx.source_uri,
            distance=ctx.distance,
        )
        for ctx in contexts
    ]
    logger.info(
        "related.served speech_id=%s n=%d query_chars=%d cached=true",
        speech_id,
        len(items),
        len(query_text),
    )
    response = RelatedResponse(
        speech_id=speech_id,
        query_text=query_text,
        items=items,
        corpus_used=corpus_name,
    )
    _RELATED_CACHE.set(cache_key, response)
    return response


# ============================================================================
# v1 Reactions (Phase X — Firestore 永続化)
# ============================================================================


class ReactionResponse(BaseModel):
    """ユーザー × speech のリアクション状態。未設定時 reaction=None。"""

    speech_id: str
    user_id: str
    reaction: str | None = Field(default=None, description="👍 | 🤔 | 😢 | 🔥 | None")
    updated_at: str | None = Field(default=None, description="ISO 8601 timestamp")


class ReactionPutRequest(BaseModel):
    """PUT body: 設定したいリアクション。"""

    reaction: str = Field(description="👍 | 🤔 | 😢 | 🔥 のいずれか")


class ReactionSummary(BaseModel):
    """speech 1 件の集計 (Phase X+1)。全 4 種絵文字の件数 + 合計。"""

    speech_id: str
    counts: dict[str, int] = Field(
        default_factory=lambda: {r: 0 for r in ALLOWED_REACTIONS},
        description="絵文字 → 件数 (全 4 種が必ず key として存在)",
    )
    total: int = Field(default=0, description="counts の合計 (sort 用)")


_firestore_client_cache: Any = None


def _get_firestore_client() -> Any:
    """Firestore client (遅延 import + プロセス内 cache)。テストで差替可能。"""
    global _firestore_client_cache
    if _firestore_client_cache is not None:
        return _firestore_client_cache
    from google.cloud import firestore

    _firestore_client_cache = firestore.Client(project=BQ_PROJECT)
    return _firestore_client_cache


def _reaction_doc_id(user_id: str, speech_id: str) -> str:
    """Firestore document ID: {user_id}__{speech_id} (区切り文字に __ を採用)。"""
    return f"{user_id}__{speech_id}"


def _empty_counts() -> dict[str, int]:
    """全 4 種絵文字を key=0 で持つ初期値 (UI は常に 4 種並べる)。"""
    return {r: 0 for r in ALLOWED_REACTIONS}


@app.get("/v1/speeches/{speech_id}/reaction", response_model=ReactionResponse)
async def get_reaction(
    speech_id: str,
    user_id: str = Query(..., description="ペルソナ ID"),
) -> ReactionResponse:
    """ユーザー × speech の現在のリアクションを取得 (未設定なら reaction=None)。"""
    client = _get_firestore_client()
    doc_id = _reaction_doc_id(user_id, speech_id)
    try:
        snap = client.collection(FIRESTORE_COLLECTION_REACTIONS).document(doc_id).get()
    except Exception as exc:  # noqa: BLE001
        logger.exception("reaction.get_failed doc_id=%s err=%s", doc_id, exc)
        raise HTTPException(status_code=500, detail=f"Firestore get failed: {exc!s}") from exc

    if not snap.exists:
        return ReactionResponse(speech_id=speech_id, user_id=user_id, reaction=None)

    data = snap.to_dict() or {}
    updated_at = data.get("updated_at")
    return ReactionResponse(
        speech_id=speech_id,
        user_id=user_id,
        reaction=data.get("reaction"),
        updated_at=updated_at.isoformat() if hasattr(updated_at, "isoformat") else None,
    )


@app.put("/v1/speeches/{speech_id}/reaction", response_model=ReactionResponse)
async def put_reaction(
    speech_id: str,
    body: ReactionPutRequest,
    user_id: str = Query(..., description="ペルソナ ID"),
) -> ReactionResponse:
    """リアクションを設定 or 上書き。同一 user_id × speech_id は 1 つだけ保持。

    Phase X+1: 集計 (`reaction_counts/{speech_id}`) も batch で原子的に更新。
    - 新規: counts.{new} += 1, total += 1
    - 上書き: counts.{prev} -= 1, counts.{new} += 1 (total は変わらず)
    """
    if body.reaction not in ALLOWED_REACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"reaction must be one of {ALLOWED_REACTIONS}, got {body.reaction!r}",
        )

    from google.cloud import firestore as fs

    client = _get_firestore_client()
    doc_id = _reaction_doc_id(user_id, speech_id)
    reaction_ref = client.collection(FIRESTORE_COLLECTION_REACTIONS).document(doc_id)
    counts_ref = client.collection(FIRESTORE_COLLECTION_REACTION_COUNTS).document(speech_id)

    now_sentinel = fs.SERVER_TIMESTAMP

    try:
        # 既存 reaction を取得 (上書き判定 + 集計差分計算用)
        existing_snap = reaction_ref.get()
        existing_reaction: str | None = None
        if existing_snap.exists:
            existing_data = existing_snap.to_dict() or {}
            existing_reaction = existing_data.get("reaction")

        # 同じ絵文字を再 PUT した場合は no-op (counts 変更不要)
        is_same_as_existing = existing_reaction == body.reaction

        payload: dict[str, Any] = {
            "user_id": user_id,
            "speech_id": speech_id,
            "reaction": body.reaction,
            "updated_at": now_sentinel,
        }
        if not existing_snap.exists:
            payload["created_at"] = now_sentinel

        batch = client.batch()
        batch.set(reaction_ref, payload, merge=True)

        if not is_same_as_existing:
            # NOTE: batch.set() は dot-path を literal field name にする (update() のみ解釈)
            # → nested map で渡し、merge=True による deep merge で他 emoji の値を保持する
            counts_field_updates: dict[str, Any] = {body.reaction: fs.Increment(1)}
            if existing_reaction in ALLOWED_REACTIONS:
                # 上書き: 旧 reaction を -1
                counts_field_updates[existing_reaction] = fs.Increment(-1)

            counts_update: dict[str, Any] = {
                "speech_id": speech_id,
                "updated_at": now_sentinel,
                "counts": counts_field_updates,
            }
            if existing_reaction not in ALLOWED_REACTIONS:
                # 新規: total を +1 (上書きは total 不変)
                counts_update["total"] = fs.Increment(1)
            batch.set(counts_ref, counts_update, merge=True)

        batch.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("reaction.put_failed doc_id=%s err=%s", doc_id, exc)
        raise HTTPException(status_code=500, detail=f"Firestore set failed: {exc!s}") from exc

    logger.info(
        "reaction.set user_id=%s speech_id=%s reaction=%s prev=%s",
        user_id,
        speech_id,
        body.reaction,
        existing_reaction,
    )
    return ReactionResponse(
        speech_id=speech_id,
        user_id=user_id,
        reaction=body.reaction,
        updated_at=None,
    )


@app.delete("/v1/speeches/{speech_id}/reaction", response_model=ReactionResponse)
async def delete_reaction(
    speech_id: str,
    user_id: str = Query(..., description="ペルソナ ID"),
) -> ReactionResponse:
    """リアクションを解除 (document 削除)。存在しなくても 200 を返す (idempotent)。

    Phase X+1: 集計 (`reaction_counts/{speech_id}`) も batch で減算。
    既存 reaction がなければ counts は触らない。
    """
    from google.cloud import firestore as fs

    client = _get_firestore_client()
    doc_id = _reaction_doc_id(user_id, speech_id)
    reaction_ref = client.collection(FIRESTORE_COLLECTION_REACTIONS).document(doc_id)
    counts_ref = client.collection(FIRESTORE_COLLECTION_REACTION_COUNTS).document(speech_id)

    try:
        existing_snap = reaction_ref.get()
        existing_reaction: str | None = None
        if existing_snap.exists:
            existing_data = existing_snap.to_dict() or {}
            existing_reaction = existing_data.get("reaction")

        batch = client.batch()
        batch.delete(reaction_ref)
        if existing_reaction in ALLOWED_REACTIONS:
            # nested map で deep merge (dot-path は batch.set() で解釈されない)
            batch.set(
                counts_ref,
                {
                    "speech_id": speech_id,
                    "updated_at": fs.SERVER_TIMESTAMP,
                    "counts": {existing_reaction: fs.Increment(-1)},
                    "total": fs.Increment(-1),
                },
                merge=True,
            )
        batch.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("reaction.delete_failed doc_id=%s err=%s", doc_id, exc)
        raise HTTPException(status_code=500, detail=f"Firestore delete failed: {exc!s}") from exc

    logger.info(
        "reaction.cleared user_id=%s speech_id=%s prev=%s",
        user_id,
        speech_id,
        existing_reaction,
    )
    return ReactionResponse(speech_id=speech_id, user_id=user_id, reaction=None)


@app.get("/v1/speeches/{speech_id}/reactions/summary", response_model=ReactionSummary)
async def get_reaction_summary(speech_id: str) -> ReactionSummary:
    """speech に対する全リアクションの集計を取得 (Phase X+1)。

    未集計 (document なし) なら全絵文字 0 件を返す (UX 一貫性のため常に 4 種返却)。
    """
    client = _get_firestore_client()
    try:
        snap = client.collection(FIRESTORE_COLLECTION_REACTION_COUNTS).document(speech_id).get()
    except Exception as exc:  # noqa: BLE001
        logger.exception("reaction.summary_failed speech_id=%s err=%s", speech_id, exc)
        raise HTTPException(status_code=500, detail=f"Firestore get failed: {exc!s}") from exc

    counts = _empty_counts()
    total = 0
    if snap.exists:
        data = snap.to_dict() or {}
        raw_counts = data.get("counts") or {}
        for emoji in ALLOWED_REACTIONS:
            v = int(raw_counts.get(emoji, 0) or 0)
            counts[emoji] = max(0, v)  # 負値ガード (バックフィル無しなので理論上 0 以上)
        total = int(data.get("total", 0) or 0)
        total = max(0, total)

    return ReactionSummary(speech_id=speech_id, counts=counts, total=total)
