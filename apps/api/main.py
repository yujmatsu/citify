"""Citify FastAPI バックエンドのエントリポイント。

Cloud Run / ローカル開発 両対応:
    - GET /health             : Cloud Run のヘルスチェック用 (常に 200)
    - GET /version            : ビルド情報 (Git SHA, 環境名)
    - GET /v1/feed/{user_id}  : ユーザー別フィード (BQ scored_speeches_latest 経由)
    - GET /v1/speeches/{speech_id} : 1 件詳細 (BQ scored_speeches_latest 経由)
    - GET /v1/speeches/{speech_id}/related : RAG 関連議題 (Vertex AI corpus)
    - GET|PUT|DELETE /v1/speeches/{speech_id}/reaction : リアクション永続化 (Firestore)
    - GET /v1/speeches/{speech_id}/reactions/summary : リアクション集計 (Phase X+1)
    - GET /v1/compare : 複数自治体の同テーマ比較 (B-2 比較ビュー)
    - GET /v1/cities/{code} : 街ダッシュボード (Plan A-3、関心軸別集計 + 上位議題)

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
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Response
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


class _RateLimiter:
    """process 内スライディングウィンドウのレートリミッタ (W3 対策)。

    高コストな LLM/エージェント endpoint (concierge, watcher/run) の
    コスト暴走 (無認証で偽 user_id を回すだけの金銭的 DoS) の blast radius を
    抑える。厳密なグローバル制御ではない (min..max-instances=1..10 で instance 毎に
    独立、実効上限は最大 ×instance 数) が、無制限からは桁違いに改善する。
    恒久対策は Firestore カウンタ等での分散集約 (提出後)。
    """

    def __init__(self, limit: int, window_sec: float) -> None:
        self.limit = limit
        self.window_sec = window_sec
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_sec
        hits = [t for t in self._hits.get(key, []) if t > cutoff]
        if len(hits) >= self.limit:
            self._hits[key] = hits
            return False
        hits.append(now)
        self._hits[key] = hits
        # 肥大防止: キーが増えすぎたら空リストのキーを一括除去
        if len(self._hits) > 4096:
            self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > cutoff}
        return True


# 高コスト endpoint のレート制限 (ゆるめ = 通常利用は絶対に弾かない値)。
_WATCHER_RUN_LIMITER = _RateLimiter(limit=20, window_sec=600.0)  # 20 回 / 10 分 / user_id
_CONCIERGE_LIMITER = _RateLimiter(limit=40, window_sec=600.0)  # 40 回 / 10 分 / user_id


def _enforce_rate_limit(limiter: _RateLimiter, key: str, retry_after_sec: int) -> None:
    """上限超過なら HTTP 429 を投げる。"""
    if not limiter.allow(key):
        raise HTTPException(
            status_code=429,
            detail="リクエストが集中しています。しばらく待って再度お試しください。",
            headers={"Retry-After": str(retry_after_sec)},
        )


# BQ 設定 (env で上書き可)
BQ_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "citify-dev")
BQ_DATASET_CURATED = os.getenv("BQ_DATASET_CURATED", "citify_curated")
BQ_VIEW_SCORED_LATEST = os.getenv("BQ_VIEW_SCORED_LATEST", "scored_speeches_latest")
BQ_TABLE_STATS = os.getenv("BQ_TABLE_STATS", "municipality_stats")

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


# ============================================================================
# 自治体名 lookup (Compare ビューの Gemini プロンプトで使用)
# 主要自治体のみハードコード、未登録は "自治体{code}" にフォールバック
# ============================================================================
_MUNI_NAME_MAP: dict[str, str] = {
    "00000": "国会",
    # 47 都道府県
    "01000": "北海道",
    "02000": "青森県",
    "03000": "岩手県",
    "04000": "宮城県",
    "05000": "秋田県",
    "06000": "山形県",
    "07000": "福島県",
    "08000": "茨城県",
    "09000": "栃木県",
    "10000": "群馬県",
    "11000": "埼玉県",
    "12000": "千葉県",
    "13000": "東京都",
    "14000": "神奈川県",
    "15000": "新潟県",
    "16000": "富山県",
    "17000": "石川県",
    "18000": "福井県",
    "19000": "山梨県",
    "20000": "長野県",
    "21000": "岐阜県",
    "22000": "静岡県",
    "23000": "愛知県",
    "24000": "三重県",
    "25000": "滋賀県",
    "26000": "京都府",
    "27000": "大阪府",
    "28000": "兵庫県",
    "29000": "奈良県",
    "30000": "和歌山県",
    "31000": "鳥取県",
    "32000": "島根県",
    "33000": "岡山県",
    "34000": "広島県",
    "35000": "山口県",
    "36000": "徳島県",
    "37000": "香川県",
    "38000": "愛媛県",
    "39000": "高知県",
    "40000": "福岡県",
    "41000": "佐賀県",
    "42000": "長崎県",
    "43000": "熊本県",
    "44000": "大分県",
    "45000": "宮崎県",
    "46000": "鹿児島県",
    "47000": "沖縄県",
    # 政令市
    "01100": "札幌市",
    "04100": "仙台市",
    "11100": "さいたま市",
    "12100": "千葉市",
    "14100": "横浜市",
    "14130": "川崎市",
    "14150": "相模原市",
    "15100": "新潟市",
    "22100": "静岡市",
    "22130": "浜松市",
    "23100": "名古屋市",
    "26100": "京都市",
    "27100": "大阪市",
    "27140": "堺市",
    "28100": "神戸市",
    "33100": "岡山市",
    "34100": "広島市",
    "40100": "北九州市",
    "40130": "福岡市",
    "43100": "熊本市",
    # 中核市 (BQ にデータがあるもの中心)
    "01202": "函館市",
    "01204": "旭川市",
    "01213": "苫小牧市",
    "02201": "青森市",
    "02203": "八戸市",
    "03201": "盛岡市",
    "07201": "福島市",
    "07202": "会津若松市",
    "07203": "郡山市",
    "07204": "いわき市",
    "08201": "水戸市",
    "09201": "宇都宮市",
    "10201": "前橋市",
    "10202": "高崎市",
    "11201": "川越市",
    "11203": "川口市",
    "11222": "越谷市",
    "12203": "市川市",
    "12204": "船橋市",
    "12217": "柏市",
    "14201": "横須賀市",
    "16201": "富山市",
    "17201": "金沢市",
    "18201": "福井市",
    "19201": "甲府市",
    "20201": "長野市",
    "20202": "松本市",
    "21201": "岐阜市",
    "22203": "沼津市",
    "23201": "豊橋市",
    "23202": "岡崎市",
    "23203": "一宮市",
    "23211": "豊田市",
    "24202": "四日市市",
    "25201": "大津市",
    "28201": "姫路市",
    "28202": "尼崎市",
    "28204": "明石市",
    "28206": "西宮市",
    "29201": "奈良市",
    "30201": "和歌山市",
    "31201": "鳥取市",
    "32201": "松江市",
    "35201": "下関市",
    "37201": "高松市",
    "38201": "松山市",
    "39201": "高知市",
    "40203": "久留米市",
    "42201": "長崎市",
    "42202": "佐世保市",
    "44201": "大分市",
    "45201": "宮崎市",
    "46201": "鹿児島市",
    "47201": "那覇市",
    # 23 区 (主要)
    "13104": "新宿区",
    "13107": "墨田区",
    "13118": "荒川区",
}


# municipality_stats.municipality_name の全件キャッシュ (名前は不変なのでプロセス内永続)
_MUNI_NAME_CACHE: dict[str, str] | None = None


def _load_all_muni_names() -> dict[str, str]:
    """municipality_stats から全自治体の表示名を 1 回ロードしてキャッシュ。

    ハードコード (_MUNI_NAME_MAP) は主要自治体のみのため、未登録自治体 (例: 朝霞市 11227)
    の名前を BQ から補完する。BQ 失敗時は空 dict で graceful (フォールバック `自治体{code}`)。
    """
    global _MUNI_NAME_CACHE
    if _MUNI_NAME_CACHE is not None:
        return _MUNI_NAME_CACHE
    names: dict[str, str] = {}
    try:
        client = _get_bq_client()
        table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"
        sql = f"SELECT municipality_code, municipality_name FROM `{table_fqn}`"  # noqa: S608
        for row in client.query(sql).result(timeout=15):
            code = str(row.get("municipality_code") or "")
            name = row.get("municipality_name")
            if code and name:
                names[code] = name
    except Exception as exc:  # noqa: BLE001
        logger.warning("muni_names.load_failed err=%s", exc)
    _MUNI_NAME_CACHE = names
    return names


def _muni_label(code: str) -> str:
    """municipality_code から表示用ラベルを返す。

    優先順位: ハードコード (国会/都道府県/主要市区) → municipality_stats の名前 → `自治体{code}`。
    """
    if code in _MUNI_NAME_MAP:
        return _MUNI_NAME_MAP[code]
    name = _load_all_muni_names().get(code)
    return name or f"自治体{code}"


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

# CORS: フロントエンド (Firebase App Hosting / localhost) からのアクセスのみ許可。
# 以前は allow_origins="*" + allow_credentials=True で、Starlette が Origin を反射し
# 任意サイトから資格情報付きで叩ける状態だった (CWE-942)。既定を web ドメインに限定し、
# cookie を使わない設計 (認可は x-user-id ヘッダ) なので allow_credentials=False にして
# 反射リスクを断つ。追加 origin は CORS_ORIGINS 環境変数 (カンマ区切り) で上書き可能。
_DEFAULT_CORS_ORIGINS = (
    "https://citify-web--citify-dev.asia-east1.hosted.app,"
    "http://localhost:3000,http://127.0.0.1:3000"
)
_cors_origins = [
    o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
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
# v1 City Dashboard (Plan A-3 — 「あなたの街」が今どうなっているかの可視化)
# ============================================================================


class MunicipalityStats(BaseModel):
    """Plan A Phase D — 街ダッシュボード用の客観統計。

    municipality_stats テーブル 1 行に対応 (国勢調査 2020 + 人口動態 2023)。
    fallback とは独立に、自治体コード直の数値を常に優先表示する
    (Tier 3 で議題がなくても「街の輪郭」が見える背骨データ)。
    """

    population_total: int | None = None
    population_15_29: int | None = None
    population_65_plus: int | None = None
    households_total: int | None = None
    births_annual: int | None = None
    youth_share_pct: float | None = None
    elderly_share_pct: float | None = None
    population_change_pct: float | None = None
    birth_rate_per_1000: float | None = None
    data_year: int | None = None
    source_url: str | None = None
    # Phase F: Reinfolib (不動産情報ライブラリ) 由来
    used_apartment_median_price_man_yen: int | None = Field(
        default=None,
        description="中古マンション中央値 (万円、過去 4Q 集計、XIT001)",
    )
    used_apartment_sample_size: int | None = Field(
        default=None,
        description="中古マンション取引サンプル数 (n<10 は UI 非表示推奨)",
    )
    used_apartment_median_unit_price_yen: int | None = Field(
        default=None,
        description="中古マンション ㎡単価中央値 (円/㎡)",
    )
    used_apartment_avg_building_age: float | None = Field(
        default=None,
        description="中古マンション築年数平均 (年)",
    )
    emergency_shelter_count: int | None = Field(
        default=None,
        description="周辺地域 (z=11 3x3 タイル ~50km四方) の指定緊急避難場所数 (XGT001)",
    )
    emergency_shelter_official_link: str | None = Field(
        default=None,
        description="国土地理院ハザードマップポータル URL (自治体中心座標)",
    )
    # Phase F v3
    population_2025_estimated: int | None = Field(
        default=None, description="2025 年予測人口 (XKT013、周辺地域メッシュ合算)"
    )
    population_2050_estimated: int | None = Field(
        default=None, description="2050 年予測人口 (XKT013)"
    )
    population_change_2025_2050_pct: float | None = Field(
        default=None, description="2050 vs 2025 人口変動率 (%)"
    )
    medical_facility_count: int | None = Field(
        default=None, description="医療機関数 (XKT010、周辺 ~25km、重複除外)"
    )
    medical_hospital_count: int | None = Field(default=None, description="うち病院")
    medical_clinic_count: int | None = Field(default=None, description="うち診療所")
    childcare_facility_count: int | None = Field(
        default=None, description="保育・幼児教育施設数 (XKT007、自治体内厳密集計)"
    )
    kindergarten_count: int | None = Field(default=None, description="うち幼稚園")
    nursery_count: int | None = Field(default=None, description="うち保育園・認定こども園・その他")
    reinfolib_source_url: str | None = Field(
        default=None,
        description="不動産情報ライブラリ URL (引用元)",
    )
    # TASK-FISCAL: 社会・人口統計体系 (統計でみる市区町村のすがた) 由来 5 指標
    financial_capability_index: float | None = Field(
        default=None, description="財政力指数 (1.0超で財政的余裕。特別区等は null)"
    )
    real_debt_service_ratio_pct: float | None = Field(
        default=None, description="実質公債費比率 (%、高いほど借金が重い)"
    )
    taxable_income_per_capita_yen: int | None = Field(
        default=None, description="1人当たり課税対象所得 (円)"
    )
    homeownership_rate_pct: float | None = Field(default=None, description="持ち家比率 (%)")
    crime_rate_per_1000: float | None = Field(
        default=None, description="刑法犯認知件数 (人口千対、低いほど安全)"
    )
    # TASK-CITYDATA: SSDS 追加8指標 (街の状況)
    doctors_per_100k: float | None = Field(default=None, description="医師数 (人口10万対)")
    ssds_hospital_count: int | None = Field(default=None, description="病院数 (SSDS、信頼版)")
    unemployment_rate_pct: float | None = Field(default=None, description="完全失業率 (%)")
    tertiary_industry_pct: float | None = Field(default=None, description="第3次産業就業者比率 (%)")
    dwelling_area_sqm: float | None = Field(default=None, description="1住宅当たり延べ面積 (㎡)")
    day_night_pop_ratio: float | None = Field(
        default=None, description="昼夜間人口比率 (100未満=ベッドタウン)"
    )
    school_count: int | None = Field(default=None, description="小中学校数")
    nursery_children: int | None = Field(default=None, description="保育所等在所児数")


class CityDashboardResponse(BaseModel):
    """街ダッシュボードのレスポンス。

    BQ scored_speeches_latest を user_id × municipality_code でフィルタした
    集計と上位議題を 1 リクエストで返す。
    Tier 3 一般市町村でデータがない場合は所属都道府県のデータで fallback (Plan A-F)。
    Phase D で municipality_stats から客観数値も同梱。
    """

    municipality_code: str
    municipality_name: str = Field(description="表示用日本語名 (例: 東京都, 国会)")
    user_id: str
    total_speeches: int = Field(description="この自治体の議題件数 (user_id 採点済)")
    interest_counts: dict[str, int] = Field(
        default_factory=dict,
        description="matched_interests 別件数 (関心軸 10 軸のカウント)",
    )
    top_speeches: list[FeedItem] = Field(
        default_factory=list,
        description="relevance_score DESC の上位議題 (limit 件)",
    )
    fallback_used: str | None = Field(
        default=None,
        description="Tier 3 で自治体直のデータがなく都道府県データを使った場合、所属都道府県コード",
    )
    fallback_name: str | None = Field(
        default=None,
        description="fallback 元都道府県の表示名 (例: '東京都')",
    )
    stats: MunicipalityStats | None = Field(
        default=None,
        description="Phase D 客観統計 (国勢調査 2020 + 人口動態 2023)。データ未投入なら null",
    )


class PopulationTrendPoint(BaseModel):
    """人口推移の 1 点 (TASK-POPTREND)。"""

    year: int = Field(description="年次 (2000..2070)")
    population: int = Field(description="総人口")
    source: str = Field(description="'census' (国勢調査実績) | 'projection' (XKT013 将来推計)")


class PopulationTrendResponse(BaseModel):
    """人口推移グラフ用レスポンス (census 実績 + XKT013 将来推計)。"""

    municipality_code: str
    series: list[PopulationTrendPoint] = Field(
        default_factory=list, description="year 昇順の人口推移 (census→projection)"
    )
    latest_actual_year: int | None = Field(
        default=None, description="census 実績の最新年 (実線/破線の境目)"
    )
    projection_start_year: int | None = Field(
        default=None, description="projection の開始年 (破線の起点)"
    )
    source_note: str = Field(
        default="出典: 総務省 国勢調査 (実績) / 国土交通省 将来推計人口 250m メッシュ (推計)",
        description="出典明記 (倫理: AI 生成ではない客観統計)",
    )


def _prefecture_code_from_municipality(municipality_code: str) -> str | None:
    """5 桁自治体コードから所属都道府県コード (XX000) を導出。

    municipality_code の先頭 2 桁が都道府県識別。XX001-XX999 はすべて XX000 に属する。
    国会 (00000) や都道府県集約 (XX000) は対象外 (fallback 不要)。
    """
    if not municipality_code or len(municipality_code) != 5 or not municipality_code.isdigit():
        return None
    if municipality_code == "00000":
        return None
    if municipality_code.endswith("000"):
        return None
    return municipality_code[:2] + "000"


# 街ダッシュボードは 5 分 TTL (議題リストは頻繁に変わらない、フィード並み)
_CITY_CACHE = _TTLCache(maxsize=128, ttl_sec=300.0)

# municipality_stats は 1 時間 TTL (国勢調査ベースで日次変動なし)
_STATS_CACHE = _TTLCache(maxsize=2048, ttl_sec=3600.0)


def _fetch_municipality_stats(municipality_code: str) -> MunicipalityStats | None:
    """municipality_stats から 1 自治体の客観統計を取得。

    テーブル未投入や該当行なしは静かに None を返す (Phase D は optional 機能)。
    """
    cached = _STATS_CACHE.get(municipality_code)
    if cached is not None:
        return cached if isinstance(cached, MunicipalityStats) else None

    from google.cloud import bigquery

    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"
    sql = f"""
        SELECT
            population_total, population_15_29, population_65_plus,
            households_total, births_annual,
            youth_share_pct, elderly_share_pct,
            population_change_pct, birth_rate_per_1000,
            data_year, source_url,
            used_apartment_median_price_man_yen,
            used_apartment_sample_size,
            used_apartment_median_unit_price_yen,
            used_apartment_avg_building_age,
            emergency_shelter_count,
            emergency_shelter_official_link,
            population_2025_estimated,
            population_2050_estimated,
            population_change_2025_2050_pct,
            medical_facility_count,
            medical_hospital_count,
            medical_clinic_count,
            childcare_facility_count,
            kindergarten_count,
            nursery_count,
            reinfolib_source_url,
            financial_capability_index,
            real_debt_service_ratio_pct,
            taxable_income_per_capita_yen,
            homeownership_rate_pct,
            crime_rate_per_1000,
            doctors_per_100k,
            ssds_hospital_count,
            unemployment_rate_pct,
            tertiary_industry_pct,
            dwelling_area_sqm,
            day_night_pop_ratio,
            school_count,
            nursery_children
        FROM `{table_fqn}`
        WHERE municipality_code = @muni
        LIMIT 1
    """  # noqa: S608
    params = [bigquery.ScalarQueryParameter("muni", "STRING", municipality_code)]
    try:
        rows = list(
            client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result(
                timeout=5
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("stats.bq_failed muni=%s err=%s", municipality_code, exc)
        _STATS_CACHE.set(municipality_code, None)
        return None
    if not rows:
        _STATS_CACHE.set(municipality_code, None)
        return None
    r = rows[0]
    stats = MunicipalityStats(
        population_total=r.get("population_total"),
        population_15_29=r.get("population_15_29"),
        population_65_plus=r.get("population_65_plus"),
        households_total=r.get("households_total"),
        births_annual=r.get("births_annual"),
        youth_share_pct=r.get("youth_share_pct"),
        elderly_share_pct=r.get("elderly_share_pct"),
        population_change_pct=r.get("population_change_pct"),
        birth_rate_per_1000=r.get("birth_rate_per_1000"),
        data_year=r.get("data_year"),
        source_url=r.get("source_url"),
        used_apartment_median_price_man_yen=r.get("used_apartment_median_price_man_yen"),
        used_apartment_sample_size=r.get("used_apartment_sample_size"),
        used_apartment_median_unit_price_yen=r.get("used_apartment_median_unit_price_yen"),
        used_apartment_avg_building_age=r.get("used_apartment_avg_building_age"),
        emergency_shelter_count=r.get("emergency_shelter_count"),
        emergency_shelter_official_link=r.get("emergency_shelter_official_link"),
        population_2025_estimated=r.get("population_2025_estimated"),
        population_2050_estimated=r.get("population_2050_estimated"),
        population_change_2025_2050_pct=r.get("population_change_2025_2050_pct"),
        medical_facility_count=r.get("medical_facility_count"),
        medical_hospital_count=r.get("medical_hospital_count"),
        medical_clinic_count=r.get("medical_clinic_count"),
        childcare_facility_count=r.get("childcare_facility_count"),
        kindergarten_count=r.get("kindergarten_count"),
        nursery_count=r.get("nursery_count"),
        reinfolib_source_url=r.get("reinfolib_source_url"),
        financial_capability_index=r.get("financial_capability_index"),
        real_debt_service_ratio_pct=r.get("real_debt_service_ratio_pct"),
        taxable_income_per_capita_yen=r.get("taxable_income_per_capita_yen"),
        homeownership_rate_pct=r.get("homeownership_rate_pct"),
        crime_rate_per_1000=r.get("crime_rate_per_1000"),
        doctors_per_100k=r.get("doctors_per_100k"),
        ssds_hospital_count=r.get("ssds_hospital_count"),
        unemployment_rate_pct=r.get("unemployment_rate_pct"),
        tertiary_industry_pct=r.get("tertiary_industry_pct"),
        dwelling_area_sqm=r.get("dwelling_area_sqm"),
        day_night_pop_ratio=r.get("day_night_pop_ratio"),
        school_count=r.get("school_count"),
        nursery_children=r.get("nursery_children"),
    )
    _STATS_CACHE.set(municipality_code, stats)
    return stats


# 人口推移は 1 時間 TTL (国勢調査 + 将来推計、日次変動なし)
_POPTREND_CACHE = _TTLCache(maxsize=2048, ttl_sec=3600.0)


def _fetch_population_trend(municipality_code: str) -> PopulationTrendResponse:
    """municipality_population_series から 1 自治体の人口推移を取得 (TASK-POPTREND)。

    census (実績) → projection (将来推計) を year 昇順で返す。同一年に census と
    projection が両方ある場合は census を優先 (実績値を採用)。データ未投入は空 series。
    """
    cached = _POPTREND_CACHE.get(municipality_code)
    if isinstance(cached, PopulationTrendResponse):
        return cached

    from google.cloud import bigquery

    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.municipality_population_series"
    sql = f"""
        SELECT year, population, source
        FROM `{table_fqn}`
        WHERE municipality_code = @muni
        ORDER BY year ASC
    """  # noqa: S608
    params = [bigquery.ScalarQueryParameter("muni", "STRING", municipality_code)]
    try:
        rows = list(
            client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result(
                timeout=5
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("poptrend.bq_failed muni=%s err=%s", municipality_code, exc)
        empty = PopulationTrendResponse(municipality_code=municipality_code)
        _POPTREND_CACHE.set(municipality_code, empty)
        return empty

    # 同一年は census 優先で重複排除
    by_year: dict[int, dict] = {}
    for r in rows:
        year = int(r["year"])
        src = r["source"]
        if year in by_year and by_year[year]["source"] == "census" and src != "census":
            continue
        by_year[year] = {"population": r["population"], "source": src}

    points = [
        PopulationTrendPoint(year=y, population=v["population"], source=v["source"])
        for y, v in sorted(by_year.items())
        if v["population"] is not None
    ]
    census_years = [p.year for p in points if p.source == "census"]
    proj_years = [p.year for p in points if p.source == "projection"]
    result = PopulationTrendResponse(
        municipality_code=municipality_code,
        series=points,
        latest_actual_year=max(census_years) if census_years else None,
        projection_start_year=min(proj_years) if proj_years else None,
    )
    _POPTREND_CACHE.set(municipality_code, result)
    return result


@app.get(
    "/v1/cities/{municipality_code}/population-trend",
    response_model=PopulationTrendResponse,
)
async def get_population_trend(
    municipality_code: str,
    response: Response,
) -> PopulationTrendResponse:
    """1 自治体の人口推移 (国勢調査実績 + XKT013 将来推計 2025-2070) を返す。"""
    response.headers["Cache-Control"] = "public, max-age=3600"
    return _fetch_population_trend(municipality_code)


# ============================================================================
# GET /v1/cities/compare-stats — 街比較レーダー用の5指標 (TASK-FISCAL)
# 全国分布のパーセンタイルで正規化 (0-100、外側ほど良い向きに統一) + 生値を返す。
# 2-3市の相対 min-max だと僅差が極端に見え誤解を招くため、絶対指標 (全国percentile) を採用。
# ============================================================================
_COMPARE_STATS_CACHE = _TTLCache(maxsize=64, ttl_sec=600.0)
_SSDS_NATIONAL_CACHE = _TTLCache(maxsize=1, ttl_sec=3600.0)
_FUTURE_POP_CACHE = _TTLCache(maxsize=1, ttl_sec=3600.0)

# (列名, レーダー軸ラベル, 良い向き)。lower = 低いほど良い → score 反転
_FISCAL_RADAR_METRICS: tuple[tuple[str, str, str], ...] = (
    ("financial_capability_index", "財政力", "higher"),
    ("taxable_income_per_capita_yen", "所得", "higher"),
    ("homeownership_rate_pct", "持ち家", "higher"),
    ("real_debt_service_ratio_pct", "財政健全度", "lower"),
    ("crime_rate_per_1000", "治安", "lower"),
)
# TASK-CITYDATA: 暮らしの正規化指標 (規模に依らず全国比較可能なものだけ。
# 病院数/学校数/保育在所児数は実数=規模比例のためレーダーに入れずカード表示)。
_LIVING_RADAR_METRICS: tuple[tuple[str, str, str], ...] = (
    ("doctors_per_100k", "医療", "higher"),
    ("unemployment_rate_pct", "雇用", "lower"),
    ("dwelling_area_sqm", "住まい", "higher"),
)
_RADAR_METRICS: tuple[tuple[str, str, str], ...] = _FISCAL_RADAR_METRICS + _LIVING_RADAR_METRICS
# 将来人口は別ソース (municipality_population_series の 2070 予測 / 直近実績比)。
# 結論が引用する人口見通しと同じ数字を軸にして「根拠の見える化」を担保する。
_FUTURE_POP_KEY = "future_population_change_pct"
_FUTURE_POP_LABEL = "将来人口"


def _load_future_pop_change() -> dict[str, float]:
    """全自治体の (2070予測 - 直近国勢調査) / 直近 × 100 (%) を返す (1h cache)。

    結論(verdict)が使う人口見通しと同じ municipality_population_series 由来。
    減少が小さい/増加ほど値が大きい = 良い。
    """
    cached = _FUTURE_POP_CACHE.get("all")
    if cached is not None:
        return cached
    out: dict[str, float] = {}
    try:
        client = _get_bq_client()
        series_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.municipality_population_series"
        sql = f"""
            WITH base AS (
              SELECT municipality_code,
                     ARRAY_AGG(population ORDER BY year DESC LIMIT 1)[OFFSET(0)] AS pop
              FROM `{series_fqn}`
              WHERE source = 'census' AND population IS NOT NULL
              GROUP BY municipality_code
            ),
            fut AS (
              SELECT municipality_code, population AS pop
              FROM `{series_fqn}`
              WHERE year = 2070 AND population IS NOT NULL
            )
            SELECT b.municipality_code AS code, b.pop AS base_pop, f.pop AS fut_pop
            FROM base b JOIN fut f USING (municipality_code)
        """  # noqa: S608 — 固定リテラル
        for r in client.query(sql).result(timeout=15):
            base, fut = r.get("base_pop"), r.get("fut_pop")
            if base:
                out[str(r["code"])] = round((fut - base) / base * 100.0, 1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("compare_stats.future_pop_load_failed err=%s", exc)
    _FUTURE_POP_CACHE.set("all", out)
    return out


def _load_national_fiscal() -> dict[str, list[float]]:
    """全市区町村の5指標を取得し metric ごとのソート済み値配列を返す (percentile 算出用、1h cache)。"""
    cached = _SSDS_NATIONAL_CACHE.get("all")
    if cached is not None:
        return cached
    cols = [m[0] for m in _RADAR_METRICS]
    arrays: dict[str, list[float]] = {c: [] for c in cols}
    try:
        client = _get_bq_client()
        table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"
        sql = (  # noqa: S608 — 列名は固定リテラル
            f"SELECT {', '.join(cols)} FROM `{table_fqn}` "
            "WHERE municipality_code != '00000' "
            "AND SUBSTR(municipality_code, 3) NOT IN ('000', '001', '002')"
        )
        for r in client.query(sql).result(timeout=15):
            for c in cols:
                v = r.get(c)
                if v is not None:
                    arrays[c].append(float(v))
    except Exception as exc:  # noqa: BLE001
        logger.warning("compare_stats.national_load_failed err=%s", exc)
    for c in cols:
        arrays[c].sort()
    _SSDS_NATIONAL_CACHE.set("all", arrays)
    return arrays


def _percentile_score(value: Any, sorted_vals: list[float], direction: str) -> float | None:
    """value の全国パーセンタイル (0-100)。direction=lower は反転 (外側ほど良いに統一)。"""
    import bisect

    if value is None or not sorted_vals:
        return None
    rank = bisect.bisect_right(sorted_vals, float(value))
    pct = rank / len(sorted_vals) * 100.0
    return round(pct if direction == "higher" else 100.0 - pct, 1)


def _rank(value: Any, sorted_vals: list[float], direction: str) -> dict[str, int] | None:
    """value の全国順位 (1始まり、良い方向で1位) と母数 {rank, total} を返す。

    direction=higher は値が大きいほど上位、lower は小さいほど上位。タイは上位側に揃える。
    """
    import bisect

    if value is None or not sorted_vals:
        return None
    v = float(value)
    total = len(sorted_vals)
    if direction == "higher":
        rank = total - bisect.bisect_right(sorted_vals, v) + 1
    else:
        rank = bisect.bisect_left(sorted_vals, v) + 1
    return {"rank": max(1, min(rank, total)), "total": total}


def _median(sorted_vals: list[float]) -> float | None:
    """ソート済み配列の中央値 (全国基準値として併記、レーダーの解釈性確保)。"""
    n = len(sorted_vals)
    if n == 0:
        return None
    mid = n // 2
    med = sorted_vals[mid] if n % 2 else (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0
    return round(med, 2)


@app.get("/v1/cities/compare-stats")
async def get_compare_stats(
    response: Response,
    codes: str = Query(..., description="カンマ区切りの市区町村コード (最大5)"),
) -> dict:
    """街比較レーダー用: 指定自治体の財政5指標を raw + 全国 percentile score で返す。

    score は 0-100、外側ほど良い (財政力/所得/持ち家は高いほど、財政健全度/治安は低い元値ほど高score)。
    財政データ未投入 (列なし) でも graceful: values は null。
    """
    response.headers["Cache-Control"] = "public, max-age=600"
    code_list = [c.strip() for c in codes.split(",") if c.strip()][:5]
    if not code_list:
        return {"metrics": [], "towns": []}
    cache_key = ("cmpstats", tuple(code_list))
    cached = _COMPARE_STATS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    cols = [m[0] for m in _RADAR_METRICS]
    raw_by_code: dict[str, dict[str, Any]] = {}
    try:
        from google.cloud import bigquery

        client = _get_bq_client()
        table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"
        sql = (  # noqa: S608 — 列名は固定リテラル、コードは parameterized
            f"SELECT municipality_code, {', '.join(cols)} FROM `{table_fqn}` "
            "WHERE municipality_code IN UNNEST(@codes)"
        )
        params = [bigquery.ArrayQueryParameter("codes", "STRING", code_list)]
        for r in client.query(
            sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
        ).result(timeout=10):
            raw_by_code[str(r["municipality_code"])] = {c: r.get(c) for c in cols}
    except Exception as exc:  # noqa: BLE001
        logger.warning("compare_stats.bq_failed codes=%s err=%s", code_list, exc)

    national = _load_national_fiscal()
    future_pop = _load_future_pop_change()
    future_sorted = sorted(future_pop.values())
    metrics_meta = [
        {"key": k, "label": lbl, "direction": d, "national_median": _median(national.get(k, []))}
        for k, lbl, d in _RADAR_METRICS
    ]
    # 将来人口を軸に追加 (結論の主要根拠を可視化)。所得の次に配置。
    metrics_meta.insert(
        2,
        {
            "key": _FUTURE_POP_KEY,
            "label": _FUTURE_POP_LABEL,
            "direction": "higher",
            "national_median": _median(future_sorted),
        },
    )
    towns = []
    for code in code_list:
        raw = raw_by_code.get(code, {})
        values: dict[str, dict[str, Any]] = {}
        for k, _lbl, d in _RADAR_METRICS:
            rv = raw.get(k)
            rk = _rank(rv, national.get(k, []), d)
            values[k] = {
                "raw": float(rv) if isinstance(rv, int | float) else None,
                "score": _percentile_score(rv, national.get(k, []), d),
                "rank": rk["rank"] if rk else None,
                "total": rk["total"] if rk else None,
            }
        fv = future_pop.get(code)
        fr = _rank(fv, future_sorted, "higher")
        values[_FUTURE_POP_KEY] = {
            "raw": fv,
            "score": _percentile_score(fv, future_sorted, "higher"),
            "rank": fr["rank"] if fr else None,
            "total": fr["total"] if fr else None,
        }
        towns.append(
            {"municipality_code": code, "municipality_name": _muni_label(code), "values": values}
        )
    result = {"metrics": metrics_meta, "towns": towns}
    _COMPARE_STATS_CACHE.set(cache_key, result)
    logger.info("compare_stats.done codes=%s n_towns=%d", code_list, len(towns))
    return result


@app.get("/v1/cities/{municipality_code}", response_model=CityDashboardResponse)
async def get_city_dashboard(
    municipality_code: str,
    response: Response,
    user_id: str = Query(..., description="ペルソナ ID (採点コンテキスト)"),
    limit: int = Query(default=10, ge=1, le=30, description="上位議題の最大件数"),
) -> CityDashboardResponse:
    """街ダッシュボード: 1 自治体の議題集計 + 上位議題を 1 リクエストで返す。

    Plan A-3「あなたの街が今どうなっているか」の可視化用エンドポイント。
    関心軸別カウント (子育て/雇用/住居/...) + relevance 順上位 N 件。
    """
    response.headers["Cache-Control"] = (
        "public, max-age=300, s-maxage=300, stale-while-revalidate=1800"
    )
    cache_key = ("city", user_id, municipality_code, limit)
    cached = _CITY_CACHE.get(cache_key)
    if cached is not None:
        logger.info("city.cache_hit muni=%s user_id=%s", municipality_code, user_id)
        return cached

    from google.cloud import bigquery

    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_VIEW_SCORED_LATEST}"

    # 1 つのクエリで集計 + 上位 N 件を一度に取る (BQ コスト最小化)
    sql_top = f"""
        SELECT
            speech_id, title, summary, detail_url, meeting_date,
            municipality_code, name_of_meeting, speaker_position, tone,
            relevance_score, score_topic, score_age, score_geographic, score_urgency,
            matched_interests, reasoning
        FROM `{table_fqn}`
        WHERE user_id = @user_id AND municipality_code = @muni
        ORDER BY relevance_score DESC, ingested_at DESC
        LIMIT @limit
    """  # noqa: S608
    sql_counts = f"""
        SELECT interest, COUNT(DISTINCT speech_id) AS n
        FROM `{table_fqn}`, UNNEST(matched_interests) AS interest
        WHERE user_id = @user_id AND municipality_code = @muni
        GROUP BY interest
    """  # noqa: S608
    sql_total = f"""
        SELECT COUNT(DISTINCT speech_id) AS n
        FROM `{table_fqn}`
        WHERE user_id = @user_id AND municipality_code = @muni
    """  # noqa: S608

    params = [
        bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
        bigquery.ScalarQueryParameter("muni", "STRING", municipality_code),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
    ]

    try:
        rows_top = list(
            client.query(
                sql_top, job_config=bigquery.QueryJobConfig(query_parameters=params)
            ).result(timeout=10)
        )
        rows_counts = list(
            client.query(
                sql_counts, job_config=bigquery.QueryJobConfig(query_parameters=params[:2])
            ).result(timeout=10)
        )
        rows_total = list(
            client.query(
                sql_total, job_config=bigquery.QueryJobConfig(query_parameters=params[:2])
            ).result(timeout=10)
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("city.bq_failed muni=%s err=%s", municipality_code, exc)
        raise HTTPException(status_code=500, detail=f"BQ query failed: {exc!s}") from exc

    interest_counts: dict[str, int] = {
        str(r["interest"]): int(r["n"]) for r in rows_counts if r.get("interest")
    }
    total = int(rows_total[0]["n"]) if rows_total else 0

    # Plan A-F: Tier 3 一般市町村でデータがない場合、所属都道府県データで fallback
    fallback_used: str | None = None
    fallback_name: str | None = None
    if total == 0:
        pref_code = _prefecture_code_from_municipality(municipality_code)
        if pref_code and pref_code != municipality_code:
            logger.info("city.fallback_to_pref muni=%s -> pref=%s", municipality_code, pref_code)
            fallback_params = [
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
                bigquery.ScalarQueryParameter("muni", "STRING", pref_code),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
            ]
            try:
                fb_top = list(
                    client.query(
                        sql_top,
                        job_config=bigquery.QueryJobConfig(query_parameters=fallback_params),
                    ).result(timeout=10)
                )
                fb_counts = list(
                    client.query(
                        sql_counts,
                        job_config=bigquery.QueryJobConfig(query_parameters=fallback_params[:2]),
                    ).result(timeout=10)
                )
                fb_total = list(
                    client.query(
                        sql_total,
                        job_config=bigquery.QueryJobConfig(query_parameters=fallback_params[:2]),
                    ).result(timeout=10)
                )
                fb_total_n = int(fb_total[0]["n"]) if fb_total else 0
                if fb_total_n > 0:
                    rows_top = fb_top
                    interest_counts = {
                        str(r["interest"]): int(r["n"]) for r in fb_counts if r.get("interest")
                    }
                    total = fb_total_n
                    fallback_used = pref_code
                    fallback_name = _muni_label(pref_code)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "city.fallback_failed muni=%s pref=%s err=%s",
                    municipality_code,
                    pref_code,
                    exc,
                )

    # Phase D: 客観統計を fetch (fallback とは独立、自治体コード直の数値を表示)
    stats = _fetch_municipality_stats(municipality_code)

    result = CityDashboardResponse(
        municipality_code=municipality_code,
        municipality_name=_muni_label(municipality_code),
        user_id=user_id,
        total_speeches=total,
        interest_counts=interest_counts,
        fallback_used=fallback_used,
        fallback_name=fallback_name,
        top_speeches=[_row_to_feed_item(r) for r in rows_top],
        stats=stats,
    )
    _CITY_CACHE.set(cache_key, result)
    logger.info(
        "city.served muni=%s user_id=%s total=%d top=%d",
        municipality_code,
        user_id,
        total,
        len(result.top_speeches),
    )
    return result


# ============================================================================
# v1 Compare API (B-2 比較ビュー — Citify のキラー体験)
# ============================================================================


class CompareSpeech(BaseModel):
    """比較ビュー 1 自治体内の 1 件 speech (FeedItem の簡易版)。"""

    speech_id: str
    title: str | None
    summary: list[str] = Field(default_factory=list)
    detail_url: str | None = None
    meeting_date: date | None = None
    name_of_meeting: str | None = None
    matched_interests: list[str] = Field(default_factory=list)
    relevance_score: int = 0


class ComparisonColumn(BaseModel):
    """1 自治体のカラム (municipality_code + 上位 N 件 speech)。"""

    municipality_code: str
    speeches: list[CompareSpeech] = Field(default_factory=list)


class CompareResponse(BaseModel):
    """/v1/compare レスポンス。"""

    user_id: str
    interest: str = Field(description="比較対象テーマ (matched_interests のいずれか)")
    municipality_codes: list[str]
    columns: list[ComparisonColumn]
    observation: str | None = Field(
        default=None,
        description="AI による中立的な観察 (3 文以内、評価コメント禁止)",
    )


_COMPARE_CACHE = _TTLCache(maxsize=128, ttl_sec=600.0)  # 10 分 TTL


def _compare_row_to_speech(row: Any) -> CompareSpeech:
    return CompareSpeech(
        speech_id=row["speech_id"],
        title=row.get("title"),
        summary=list(row.get("summary") or []),
        detail_url=row.get("detail_url"),
        meeting_date=row.get("meeting_date"),
        name_of_meeting=row.get("name_of_meeting"),
        matched_interests=list(row.get("matched_interests") or []),
        relevance_score=int(row.get("relevance_score") or 0),
    )


_NEUTRAL_OBSERVATION_PROMPT = """あなたは Citify の中立的観察エージェントです。
複数の自治体の同テーマ議題を客観的に比較し、3 文以内で「共通点」と「相違点」を
事実陳述のみで述べてください。

# 厳守すべき倫理ルール (絶対遵守)
1. 評価コメント禁止: 「優れている」「劣っている」「素晴らしい」等の評価語句使用禁止
2. 政党推奨・批判禁止
3. 「投票推奨」「処方」等の禁止語禁止
4. 政治家・首長の固有名詞使わない
5. 自治体名はそのまま使ってよい (例: 「新宿区では...」「横浜市では...」)
6. 賛否判断をしない、事実陳述のみ
7. 各文末は「...しています」「...が含まれています」「...されています」のような中立的表現

# 出力
3 文以内のプレーンテキスト (JSON 不要)。
"""


def _build_neutral_observation_user_prompt(interest: str, columns: list[ComparisonColumn]) -> str:
    lines = [f"# テーマ\n{interest}\n"]
    for col in columns:
        label = _muni_label(col.municipality_code)
        lines.append(f"\n## {label} (municipality_code={col.municipality_code})")
        for sp in col.speeches[:3]:
            title = sp.title or "(タイトル未生成)"
            summary_text = " / ".join(sp.summary[:3]) if sp.summary else "(要約未生成)"
            lines.append(f"- {title}: {summary_text}")
    lines.append(
        "\n# タスク\n上記をふまえ、共通点 1 文 + 相違点 1-2 文で中立的に観察してください。\n"
        "自治体名は上記の見出しのとおり日本語名 (例: 「奈良市」「東京都」「国会」) で記述し、"
        "「自治体XXXXX」のようなコード番号表記は使わないでください。"
    )
    return "\n".join(lines)


_FORBIDDEN_OBSERVATION_PATTERNS = (
    "投票",
    "推奨",
    "処方",
    "優れて",
    "劣って",
    "素晴らしい",
    "残念",
    "賛成",
    "反対",
)


def _validate_observation(text: str) -> bool:
    """中立観察の倫理チェック (禁止語含むなら False)。"""
    return not any(pat in text for pat in _FORBIDDEN_OBSERVATION_PATTERNS)


def _generate_neutral_observation(interest: str, columns: list[ComparisonColumn]) -> str | None:
    """Gemini で中立的観察を生成。失敗時 None (UI 側で観察を非表示)。"""
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        logger.warning("compare.observation.genai_unavailable")
        return None

    if not any(col.speeches for col in columns):
        return None

    try:
        client = genai.Client(vertexai=True, project=BQ_PROJECT, location=RAG_LOCATION)
        user_prompt = _build_neutral_observation_user_prompt(interest, columns)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_NEUTRAL_OBSERVATION_PROMPT,
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            return None
        if not _validate_observation(text):
            logger.warning("compare.observation.ethics_violation text=%r", text[:80])
            return None
        # 3 文以内に丸める (改行・句点で簡易分割)
        sentences = [s.strip() for s in text.replace("\n", " ").split("。") if s.strip()]
        # 元テキストが「。」で終わっていない = 最後の文は不完全 → 破棄
        if sentences and not text.rstrip().endswith("。"):
            sentences = sentences[:-1]
        if len(sentences) > 3:
            sentences = sentences[:3]
        if not sentences:
            return None
        return "。".join(sentences) + "。"
    except Exception as exc:  # noqa: BLE001
        logger.exception("compare.observation.gen_failed err=%s", exc)
        return None


@app.get("/v1/compare", response_model=CompareResponse)
async def compare_municipalities(
    response: Response,
    user_id: str = Query(..., description="ペルソナ ID"),
    munis: str = Query(..., description="比較対象の municipality_code (カンマ区切り、2-3 件)"),
    interest: str = Query(..., description="比較対象テーマ (matched_interests の 1 つ)"),
    limit: int = Query(default=3, ge=1, le=5, description="各自治体ごとの上限件数"),
    include_observation: bool = Query(default=True, description="Gemini 中立観察の生成有無"),
) -> CompareResponse:
    """複数自治体の同テーマ議題を横並びで比較 (B-2 キラー体験)。

    Flow:
        1. munis を分割 (2-3 件)
        2. 各 municipality_code × user_id × interest で BQ scored_speeches_latest を検索
        3. include_observation=True なら Gemini で中立観察を生成
    """
    # Phase Q: ブラウザ HTTP cache (10 分)
    response.headers["Cache-Control"] = (
        "public, max-age=600, s-maxage=600, stale-while-revalidate=3600"
    )

    muni_codes = [m.strip() for m in munis.split(",") if m.strip()]
    if len(muni_codes) < 2:
        raise HTTPException(
            status_code=400, detail="munis must contain at least 2 municipality_codes"
        )
    if len(muni_codes) > 3:
        raise HTTPException(
            status_code=400, detail="munis must contain at most 3 municipality_codes"
        )

    cache_key = (
        "compare",
        user_id,
        tuple(sorted(muni_codes)),
        interest,
        limit,
        include_observation,
    )
    cached = _COMPARE_CACHE.get(cache_key)
    if cached is not None:
        logger.info(
            "compare.cache_hit user_id=%s interest=%s munis=%s", user_id, interest, muni_codes
        )
        return cached

    from google.cloud import bigquery

    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_VIEW_SCORED_LATEST}"
    columns_data: list[ComparisonColumn] = []

    for muni in muni_codes:
        sql = f"""
            SELECT
                speech_id, title, summary, detail_url, meeting_date,
                municipality_code, name_of_meeting, matched_interests, relevance_score
            FROM `{table_fqn}`
            WHERE user_id = @user_id
              AND municipality_code = @muni
              AND @interest IN UNNEST(matched_interests)
            ORDER BY relevance_score DESC, ingested_at DESC
            LIMIT @limit
        """  # noqa: S608
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
                bigquery.ScalarQueryParameter("muni", "STRING", muni),
                bigquery.ScalarQueryParameter("interest", "STRING", interest),
                bigquery.ScalarQueryParameter("limit", "INT64", limit),
            ]
        )
        try:
            rows = list(client.query(sql, job_config=job_config).result(timeout=15))
        except Exception as exc:  # noqa: BLE001
            logger.exception("compare.bq_failed muni=%s err=%s", muni, exc)
            raise HTTPException(
                status_code=500, detail=f"BQ query failed for muni={muni}: {exc!s}"
            ) from exc

        columns_data.append(
            ComparisonColumn(
                municipality_code=muni,
                speeches=[_compare_row_to_speech(r) for r in rows],
            )
        )

    observation: str | None = None
    if include_observation:
        observation = _generate_neutral_observation(interest, columns_data)

    result = CompareResponse(
        user_id=user_id,
        interest=interest,
        municipality_codes=muni_codes,
        columns=columns_data,
        observation=observation,
    )
    _COMPARE_CACHE.set(cache_key, result)
    logger.info(
        "compare.served user_id=%s interest=%s munis=%s observation=%s",
        user_id,
        interest,
        muni_codes,
        bool(observation),
    )
    return result


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


# ============================================================================
# /v1/concierge — 街診断 Migration Concierge Agent (Plan E)
# ============================================================================
# ユーザーの自然言語相談 + persona から、合う自治体 TOP5 を提案する対話型 Agent。
# 本番実行体は GenaiConciergeRunner: google.genai の function-calling で 4 つの BQ tool を
# 自律的に反復呼び出しする単一エージェント (反復上限 = Runner.MAX_ITERATIONS)。
# 別途 agents/concierge/adk_agent.py に translator/relevance を sub_agents に持つ ADK 親子
# 構成があり demo_adk_chain.py で単体実行できるが、本エンドポイントの実行経路ではない。
# マルチエージェントの必然性は Watcher の specialist crew と Pub/Sub パイプラインで示す。
# ============================================================================

# Concierge は module-level lazy init (初回 POST 受信時に構築)、process 内 reuse
_CONCIERGE_AGENT: Any = None
_CONCIERGE_RUNNER: Any = None
_CONCIERGE_MEMORY: Any = None  # Plan L+LL: ConversationMemory


def _get_concierge_memory() -> Any:
    """ConversationMemory を遅延構築 (Plan L+LL)。"""
    global _CONCIERGE_MEMORY
    if _CONCIERGE_MEMORY is None:
        from agents.concierge.memory import ConversationMemory

        _CONCIERGE_MEMORY = ConversationMemory()
    return _CONCIERGE_MEMORY


def _get_concierge_agent() -> Any:
    """ConciergeAgent + GenaiConciergeRunner + Memory を遅延構築 (lazy)。"""
    global _CONCIERGE_AGENT, _CONCIERGE_RUNNER
    if _CONCIERGE_AGENT is None:
        from agents.concierge.main import ConciergeAgent
        from agents.concierge.runner import GenaiConciergeRunner

        _CONCIERGE_RUNNER = GenaiConciergeRunner(project_id=BQ_PROJECT)
        _CONCIERGE_AGENT = ConciergeAgent(
            project_id=BQ_PROJECT,
            runner=_CONCIERGE_RUNNER,
            memory=_get_concierge_memory(),
        )
        logger.info("concierge.initialized project=%s", BQ_PROJECT)
    return _CONCIERGE_AGENT


@app.post("/v1/concierge")
async def post_concierge(payload: dict) -> dict:
    """街診断 Migration Concierge Agent endpoint (Plan E)。

    Request body:
        {"message": "26歳、リモートワーク...", "persona": {"user_id": "...", "age_group": "25-29", ...}}

    Response body:
        {"reply": "...", "tool_calls": [...], "candidates": [...], "ethical_violations": []}

    NOTE: request/response の Pydantic 検証は `ConciergeRequest` / `ConciergeResponse` で
    実施する。FastAPI 直接の response_model= は使わず、internal で validate して dict 返却
    (agents パッケージ依存を main.py の type hint から外し、import エラー時の起動失敗を回避)。
    """
    # 遅延 import (起動高速化 + Plan E が壊れても /health は生きる)
    from agents.concierge.schema import ConciergeRequest

    try:
        request = ConciergeRequest.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid request body: {exc!s}") from exc

    # レート制限 (W3): 高コストな LLM tool-loop の暴走抑制
    _enforce_rate_limit(_CONCIERGE_LIMITER, f"concierge:{request.persona.user_id}", 60)

    agent = _get_concierge_agent()
    try:
        response = agent.respond(request)
    except Exception as exc:  # noqa: BLE001
        logger.exception("concierge.endpoint_failed err=%s", exc)
        raise HTTPException(status_code=500, detail=f"Concierge failed: {exc!s}") from exc

    logger.info(
        "concierge.endpoint.done user_id=%s n_tools=%d n_candidates=%d violations=%s",
        request.persona.user_id,
        len(response.tool_calls),
        len(response.candidates),
        response.ethical_violations,
    )

    return response.model_dump(mode="json")


# ============================================================================
# GET /v1/concierge/history/{user_id} — 会話履歴取得 (Plan L+LL)
# ============================================================================
# Concierge との過去対話を取得。認可は `x-user-id` header と path user_id の
# 一致チェック (demo 環境簡易認可)。production では IAM 認証に置換予定。
# ============================================================================


@app.get("/v1/concierge/history/{user_id}")
async def get_concierge_history(
    user_id: str,
    response: Response,
    limit: int = Query(default=20, ge=1, le=100),
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> dict:
    """ユーザーの Concierge 会話履歴を最新順で取得 (Plan L+LL)。

    Authorization:
        path の `user_id` と header `x-user-id` が一致しないと 403。
        demo 環境簡易認可、production では IAM bearer token に置換予定。
    """
    if x_user_id is None or x_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="x-user-id header must match path user_id (demo 認可)",
        )

    response.headers["Cache-Control"] = "private, max-age=0, no-cache"

    memory = _get_concierge_memory()
    try:
        records = memory.recall_recent(user_id=user_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("concierge.history_failed user_id=%s err=%s", user_id, exc)
        raise HTTPException(status_code=500, detail=f"history fetch failed: {exc!s}") from exc

    logger.info(
        "concierge.history.done user_id=%s n_records=%d",
        user_id,
        len(records),
    )

    # HistoryRecord (dataclass) を dict に変換 (embedding は除外、サイズ節約)
    items = []
    for r in records:
        items.append(
            {
                "doc_id": r.doc_id,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "message": r.message,
                "short_summary": r.short_summary,
                "candidates_codes": r.candidates_codes,
                "matched_interests": r.matched_interests,
            }
        )

    return {"user_id": user_id, "items": items, "total": len(items)}


# ============================================================================
# GET /v1/heatmap — 全国ヒートマップ Agent (Plan X)
# ============================================================================
# HeatmapAdvisor がペルソナを踏まえて指標を選定、47 都道府県の median + 県別 TOP3 を返す。
# BQ コスト最小化のため scan は municipality_stats のみ、TTL=1h cache を流用。
# ============================================================================


_HEATMAP_CACHE = _TTLCache(maxsize=256, ttl_sec=600.0)  # 10 分 TTL


_HEATMAP_ADVISOR: Any = None


def _get_heatmap_advisor() -> Any:
    """HeatmapAdvisor を遅延初期化 (テストで monkeypatch 可能)。"""
    global _HEATMAP_ADVISOR
    if _HEATMAP_ADVISOR is None:
        from agents.heatmap_advisor import HeatmapAdvisor

        _HEATMAP_ADVISOR = HeatmapAdvisor(project_id=os.getenv("GCP_PROJECT_ID") or None)
    return _HEATMAP_ADVISOR


@app.get("/v1/heatmap")
async def get_heatmap(
    response: Response,
    user_id: str = Query(default="anon", description="ペルソナ ID"),
    age_group: str = Query(default="25-29", description="年代 (18-24/25-29/30-39/40-49/50+)"),
    interests: str = Query(default="", description="カンマ区切り interest 軸"),
    focus_interest: str = Query(..., description="ヒートマップでフォーカスする 1 軸"),
    free_form_context: str = Query(default="", max_length=500),
) -> dict:
    """全国ヒートマップ: HeatmapAdvisor 選定指標 + 47 県集計 + 県別 TOP3 (Plan X)。

    Flow:
        1. HeatmapAdvisor.suggest_metric(persona) で metric_column + direction
        2. BQ で 47 都道府県の中央値集計 (集計行 XX000 / 00000 除外)
        3. BQ で県別 TOP3 自治体
        4. PrefValue × 47 + PrefTop × 47 を返す

    Authorization: なし (集計値は公開、UI 表示用)。
    """
    from agents.heatmap_advisor.schema import PersonaContext

    response.headers["Cache-Control"] = (
        "public, max-age=600, s-maxage=600, stale-while-revalidate=3600"
    )

    cache_key = ("heatmap", user_id, age_group, interests, focus_interest, free_form_context)
    cached = _HEATMAP_CACHE.get(cache_key)
    if cached is not None:
        logger.info("heatmap.cache_hit user_id=%s focus=%s", user_id, focus_interest)
        return cached

    # Step 1: HeatmapAdvisor で指標選定
    try:
        persona = PersonaContext(
            user_id=user_id,
            age_group=age_group,  # type: ignore[arg-type]
            interests=[i.strip() for i in interests.split(",") if i.strip()],  # type: ignore[arg-type]
            focus_interest=focus_interest,  # type: ignore[arg-type]
            free_form_context=free_form_context,
        )
    except Exception as exc:  # noqa: BLE001 — Pydantic validation
        raise HTTPException(status_code=422, detail=f"Invalid persona: {exc!s}") from exc

    advisor = _get_heatmap_advisor()
    advice = advisor.suggest_metric(persona)

    # Step 2-3: BQ query
    try:
        prefecture_values, top_municipalities = _fetch_heatmap_bq(
            metric_column=advice.metric_column,
            direction=advice.direction,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("heatmap.bq_failed err=%s", exc)
        raise HTTPException(status_code=500, detail=f"BQ heatmap query failed: {exc!s}") from exc

    result = {
        "advice": advice.model_dump(),
        "prefecture_values": prefecture_values,
        "top_municipalities": top_municipalities,
    }
    _HEATMAP_CACHE.set(cache_key, result)
    logger.info(
        "heatmap.done user_id=%s focus=%s metric=%s source=%s n_pref=%d",
        user_id,
        focus_interest,
        advice.metric_column,
        advice.source,
        len(prefecture_values),
    )
    return result


def _fetch_heatmap_bq(metric_column: str, direction: str) -> tuple[list[dict], list[dict]]:
    """47 都道府県集計 + 県別 TOP3 を BQ から取得 (Plan X)。

    重要 (Reviewer Critical #1): 集計行 (XX000) と国会 (00000) を除外しないと
    47 県の median が個別自治体と二重計上され破綻する。
    """
    # SQL injection 防止: metric_column を許可リストで検証 (BQ identifier は param 化できないため)
    from agents.heatmap_advisor.main import FALLBACK_METRIC_BY_INTEREST
    from google.cloud import bigquery

    allowed_columns = {spec.column for spec in FALLBACK_METRIC_BY_INTEREST.values()} | {
        # LLM が選びうる全 metric を明示的に許可
        "used_apartment_median_price_man_yen",
        "used_apartment_median_unit_price_yen",
        "childcare_facility_count",
        "medical_facility_count",
        "emergency_shelter_count",
        "population_change_pct",
        "youth_share_pct",
        "elderly_share_pct",
        "birth_rate_per_1000",
    }
    if metric_column not in allowed_columns:
        raise ValueError(f"metric_column not in allowlist: {metric_column!r}")
    if direction not in ("lower_is_better", "higher_is_better"):
        raise ValueError(f"invalid direction: {direction!r}")

    # 集計 sort 方向 (lower_is_better なら ASC で 1 位、higher_is_better なら DESC)
    sort_order = "ASC" if direction == "lower_is_better" else "DESC"

    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_TABLE_STATS}"

    # 47 都道府県中央値 (集計行 XX000 + 国会 00000 を除外)
    sql_pref = f"""
        WITH muni AS (
          SELECT
            SUBSTR(municipality_code, 1, 2) AS prefecture_code,
            {metric_column} AS metric_value
          FROM `{table_fqn}`
          WHERE {metric_column} IS NOT NULL
            AND municipality_code NOT LIKE '%000'
            AND municipality_code != '00000'
        )
        SELECT
          prefecture_code,
          APPROX_QUANTILES(metric_value, 100)[OFFSET(50)] AS metric_median,
          COUNT(*) AS muni_count
        FROM muni
        GROUP BY prefecture_code
        ORDER BY metric_median {sort_order}
    """  # noqa: S608

    # 県別 TOP3 (集計行除外、ROW_NUMBER で県内ランク付け)
    sql_top = f"""
        SELECT prefecture_code, municipality_code, metric_value
        FROM (
          SELECT
            SUBSTR(municipality_code, 1, 2) AS prefecture_code,
            municipality_code,
            {metric_column} AS metric_value,
            ROW_NUMBER() OVER (
              PARTITION BY SUBSTR(municipality_code, 1, 2)
              ORDER BY {metric_column} {sort_order}
            ) AS rk
          FROM `{table_fqn}`
          WHERE {metric_column} IS NOT NULL
            AND municipality_code NOT LIKE '%000'
            AND municipality_code != '00000'
        )
        WHERE rk <= 3
        ORDER BY prefecture_code, rk
    """  # noqa: S608

    rows_pref = list(
        client.query(sql_pref, job_config=bigquery.QueryJobConfig()).result(timeout=20)
    )
    rows_top = list(client.query(sql_top, job_config=bigquery.QueryJobConfig()).result(timeout=20))

    # 県集計に rank を付与 (sort_order ですでに昇順、enumerate)
    prefecture_values: list[dict] = []
    for rk, row in enumerate(rows_pref, start=1):
        pref_code = row.get("prefecture_code", "") or ""
        pref_full_code = f"{pref_code}000"
        prefecture_values.append(
            {
                "prefecture_code": pref_code,
                "prefecture_name": _MUNI_NAME_MAP.get(pref_full_code, f"県{pref_code}"),
                "metric_median": float(row.get("metric_median") or 0.0),
                "muni_count": int(row.get("muni_count") or 0),
                "rank": rk,
            }
        )

    # 県別 TOP3 を prefecture_code でグループ化
    top_by_pref: dict[str, list[dict]] = {}
    for row in rows_top:
        pref_code = row.get("prefecture_code", "") or ""
        muni_code = row.get("municipality_code", "") or ""
        top_by_pref.setdefault(pref_code, []).append(
            {
                "municipality_code": muni_code,
                "municipality_name": _muni_label(muni_code),
                "metric_value": float(row.get("metric_value") or 0.0),
            }
        )

    top_municipalities = [
        {"prefecture_code": pref_code, "municipalities": top_by_pref.get(pref_code, [])}
        for pref_code in sorted(top_by_pref.keys())
    ]

    return prefecture_values, top_municipalities


# ============================================================================
# GET /v1/timeline — 議論タイムライン Agent (Plan N)
# ============================================================================
# TimelineAgent が theme_interest + 自治体 + 期間で候補 speeches を集約し、
# 5-10 個の重要イベントで議論変遷を物語化。
# ============================================================================


_TIMELINE_CACHE = _TTLCache(maxsize=256, ttl_sec=600.0)  # 10 分 TTL

_TIMELINE_AGENT: Any = None


def _get_timeline_agent() -> Any:
    """TimelineAgent 遅延初期化 (テスト monkeypatch 可能)。"""
    global _TIMELINE_AGENT
    if _TIMELINE_AGENT is None:
        from agents.timeline import TimelineAgent

        _TIMELINE_AGENT = TimelineAgent(project_id=os.getenv("GCP_PROJECT_ID") or None)
    return _TIMELINE_AGENT


@app.get("/v1/timeline")
async def get_timeline(
    response: Response,
    theme_interest: str = Query(..., description="フォーカスする interest 軸 (10 軸のいずれか)"),
    user_id: str = Query(default="anon"),
    municipality_code: str | None = Query(
        default=None, description="None=全国、5桁 code で 1 自治体"
    ),
    days: int = Query(default=90, ge=7, le=365),
) -> dict:
    """議論タイムライン (Plan N): theme + 自治体 + 期間で候補 speeches → LLM ナラティブ。

    Flow:
        1. BQ scored_speeches_latest から候補取得 (集計行除外、UNNEST matched_interests、ORDER BY meeting_date)
        2. TimelineAgent.narrate で物語化 (or rule-based fallback)
        3. TimelineNarrative を返す
    """
    from datetime import timedelta

    from agents.timeline.schema import TimelineRequest

    response.headers["Cache-Control"] = (
        "public, max-age=600, s-maxage=600, stale-while-revalidate=3600"
    )

    cache_key = ("timeline", user_id, theme_interest, municipality_code or "all", days)
    cached = _TIMELINE_CACHE.get(cache_key)
    if cached is not None:
        logger.info("timeline.cache_hit user_id=%s interest=%s", user_id, theme_interest)
        return cached

    # Pydantic validation
    try:
        request = TimelineRequest(
            user_id=user_id,
            theme_interest=theme_interest,  # type: ignore[arg-type]
            municipality_code=municipality_code,
            days=days,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid timeline request: {exc!s}") from exc

    # 期間計算 (today - days, today)
    period_end = datetime.now(UTC).date()
    period_start = period_end - timedelta(days=days)

    # Step 1: BQ candidate fetch
    try:
        candidates = _fetch_timeline_candidates(
            user_id=user_id,
            theme_interest=theme_interest,
            municipality_code=municipality_code,
            period_start=period_start,
            period_end=period_end,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("timeline.bq_failed user_id=%s err=%s", user_id, exc)
        raise HTTPException(status_code=500, detail=f"BQ timeline query failed: {exc!s}") from exc

    # Step 2: LLM narrative (or fallback)
    agent = _get_timeline_agent()
    narrative = agent.narrate(
        candidates,
        request,
        period_start=period_start,
        period_end=period_end,
    )

    result = {
        "narrative": narrative.model_dump(mode="json"),
        "candidate_count": len(candidates),
    }
    _TIMELINE_CACHE.set(cache_key, result)
    logger.info(
        "timeline.done user_id=%s interest=%s n_candidates=%d source=%s n_events=%d",
        user_id,
        theme_interest,
        len(candidates),
        narrative.source,
        len(narrative.events),
    )
    return result


def _fetch_timeline_candidates(
    user_id: str,
    theme_interest: str,
    municipality_code: str | None,
    period_start: date,
    period_end: date,
) -> list:
    """BQ から candidate speeches を取得 (集計行除外、UNNEST matched_interests)。

    Reviewer Critical #1: speaker (実名) は SELECT に含めない (二重防御)。
    speaker_position のみ送る。
    """
    from agents.timeline.schema import CandidateSpeech
    from google.cloud import bigquery

    # 10 関心軸 allowlist (SQL injection 防止、ただしここでは param 化するので必須ではない)
    allowed_interests = {
        "住居",
        "雇用",
        "結婚",
        "子育て",
        "税",
        "起業",
        "防災",
        "医療",
        "教育",
        "移住",
    }
    if theme_interest not in allowed_interests:
        raise ValueError(f"theme_interest not in 10-axis allowlist: {theme_interest!r}")

    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_VIEW_SCORED_LATEST}"

    # speaker は意図的に除外 (Reviewer Critical #1)
    sql = f"""
        SELECT
          speech_id, title, summary, meeting_date,
          municipality_code, name_of_meeting, speaker_position,
          matched_interests, relevance_score
        FROM `{table_fqn}`
        WHERE user_id = @user_id
          AND meeting_date BETWEEN @start_date AND @end_date
          AND @interest IN UNNEST(matched_interests)
          AND (@muni IS NULL OR municipality_code = @muni)
          AND municipality_code != '00000'
          AND municipality_code NOT LIKE '%000'
        ORDER BY meeting_date ASC, relevance_score DESC
        LIMIT 30
    """  # noqa: S608

    params = [
        bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
        bigquery.ScalarQueryParameter("start_date", "DATE", period_start.isoformat()),
        bigquery.ScalarQueryParameter("end_date", "DATE", period_end.isoformat()),
        bigquery.ScalarQueryParameter("interest", "STRING", theme_interest),
        bigquery.ScalarQueryParameter("muni", "STRING", municipality_code),
    ]

    rows = list(
        client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result(
            timeout=15
        )
    )

    candidates = []
    for r in rows:
        summary_list = list(r.get("summary") or [])
        first_line = summary_list[0] if summary_list else ""
        muni_code = r.get("municipality_code", "") or ""
        candidates.append(
            CandidateSpeech(
                speech_id=r.get("speech_id", ""),
                title=r.get("title") or "",
                summary_first_line=str(first_line)[:120],
                meeting_date=r.get("meeting_date"),
                municipality_code=muni_code,
                municipality_name=_muni_label(muni_code),
                speaker_position=r.get("speaker_position"),
                matched_interests=list(r.get("matched_interests") or []),
                relevance_score=int(r.get("relevance_score") or 0),
            )
        )

    return candidates


# ============================================================================
# GET /v1/forecast — 議題件数トレンド予測 Agent (Plan Z)
# ============================================================================
# ForecastEngine (純計算) + ForecastNarrator (LLM) で月別件数 → 3 か月予測 + 介入的説明。
# Reviewer High #2: confidence 3 段階 (high/medium/low、slope 標準誤差 + CV ベース)
# Reviewer High #1: 47 都道府県名 + 主要市区町村名 leak チェック (Frontend disclaimer 必須)
# ============================================================================


_FORECAST_CACHE = _TTLCache(maxsize=256, ttl_sec=600.0)

_FORECAST_NARRATOR: Any = None


def _get_forecast_narrator() -> Any:
    """ForecastNarrator 遅延初期化 (テスト monkeypatch 可能)。"""
    global _FORECAST_NARRATOR
    if _FORECAST_NARRATOR is None:
        from agents.forecast import ForecastNarrator

        _FORECAST_NARRATOR = ForecastNarrator(project_id=os.getenv("GCP_PROJECT_ID") or None)
    return _FORECAST_NARRATOR


@app.get("/v1/forecast")
async def get_forecast(
    response: Response,
    theme_interest: str = Query(..., description="フォーカスする interest 軸 (10 軸のいずれか)"),
    user_id: str = Query(default="anon"),
    age_group: str = Query(default="25-29"),
    municipality_code: str | None = Query(default=None, description="None=全国"),
    history_months: int = Query(default=12, ge=3, le=24),
) -> dict:
    """議題件数トレンド予測 (Plan Z): 月別集計 → 線形外挿 3 か月予測 + LLM ナラティブ。"""
    from datetime import timedelta

    from agents.forecast import ForecastEngine
    from agents.forecast.schema import PersonaContext

    response.headers["Cache-Control"] = (
        "public, max-age=600, s-maxage=600, stale-while-revalidate=3600"
    )

    cache_key = (
        "forecast",
        user_id,
        theme_interest,
        municipality_code or "all",
        history_months,
        age_group,
    )
    cached = _FORECAST_CACHE.get(cache_key)
    if cached is not None:
        logger.info("forecast.cache_hit user_id=%s interest=%s", user_id, theme_interest)
        return cached

    # 入力検証
    try:
        persona = PersonaContext(
            user_id=user_id,
            age_group=age_group,  # type: ignore[arg-type]
            interests=[theme_interest],  # type: ignore[arg-type]
            focus_interest=theme_interest,  # type: ignore[arg-type]
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid forecast request: {exc!s}") from exc

    # 期間計算 (history_months ヶ月分)
    today = datetime.now(UTC).date()
    period_end = today
    period_start = today - timedelta(days=history_months * 31)

    # Step 1: BQ から月別件数
    try:
        monthly_counts = _fetch_forecast_monthly_counts(
            user_id=user_id,
            theme_interest=theme_interest,
            municipality_code=municipality_code,
            period_start=period_start,
            period_end=period_end,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("forecast.bq_failed err=%s", exc)
        raise HTTPException(status_code=500, detail=f"BQ forecast query failed: {exc!s}") from exc

    # Step 2: Engine (純計算)
    engine = ForecastEngine()
    series = engine.forecast_series(monthly_counts, horizon=3)

    # Step 3: Narrator (LLM)
    municipality_label = _muni_label(municipality_code) if municipality_code else "全国"
    narrator = _get_forecast_narrator()
    narrative = narrator.narrate(series, persona, municipality_label=municipality_label)

    result = {
        "series": series.model_dump(mode="json"),
        "narrative": narrative.model_dump(mode="json"),
    }
    _FORECAST_CACHE.set(cache_key, result)
    logger.info(
        "forecast.done user_id=%s interest=%s trend=%s confidence=%s source=%s",
        user_id,
        theme_interest,
        series.trend_classification,
        series.confidence,
        narrative.source,
    )
    return result


def _fetch_forecast_monthly_counts(
    user_id: str,
    theme_interest: str,
    municipality_code: str | None,
    period_start: date,
    period_end: date,
) -> list:
    """BQ から月別 speech_count を取得 (集計行除外、NULL date 除外)。"""
    from agents.forecast.schema import MonthCount
    from google.cloud import bigquery

    allowed_interests = {
        "住居",
        "雇用",
        "結婚",
        "子育て",
        "税",
        "起業",
        "防災",
        "医療",
        "教育",
        "移住",
    }
    if theme_interest not in allowed_interests:
        raise ValueError(f"theme_interest not in 10-axis allowlist: {theme_interest!r}")

    client = _get_bq_client()
    table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_VIEW_SCORED_LATEST}"

    sql = f"""
        SELECT
          FORMAT_DATE("%Y-%m", meeting_date) AS year_month,
          COUNT(DISTINCT speech_id) AS speech_count
        FROM `{table_fqn}`
        WHERE user_id = @user_id
          AND meeting_date IS NOT NULL
          AND meeting_date BETWEEN @start_date AND @end_date
          AND @interest IN UNNEST(matched_interests)
          AND (@muni IS NULL OR municipality_code = @muni)
          AND municipality_code != '00000'
          AND municipality_code NOT LIKE '%000'
        GROUP BY year_month
        ORDER BY year_month ASC
    """  # noqa: S608

    params = [
        bigquery.ScalarQueryParameter("user_id", "STRING", user_id),
        bigquery.ScalarQueryParameter("start_date", "DATE", period_start.isoformat()),
        bigquery.ScalarQueryParameter("end_date", "DATE", period_end.isoformat()),
        bigquery.ScalarQueryParameter("interest", "STRING", theme_interest),
        bigquery.ScalarQueryParameter("muni", "STRING", municipality_code),
    ]

    rows = list(
        client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result(
            timeout=15
        )
    )

    return [
        MonthCount(
            year_month=r.get("year_month", ""),
            speech_count=float(r.get("speech_count") or 0),
        )
        for r in rows
    ]


# ============================================================================
# GET /v1/scraper-health — Self-healing Scraper Agent (Plan F)
# ============================================================================
# DiagnosticAgent + RepairProposalAgent で失敗ログを診断 + 修正提案。
# 自動 PR/commit は **実装しない** (人間レビュー前提、PROJECT.md §5 倫理境界)。
# MVP: Firestore 失敗ログがなければ sample seed (infra/seed/scraper_failures_sample.json) を使用。
# ============================================================================


_SCRAPER_HEALTH_CACHE = _TTLCache(maxsize=64, ttl_sec=3600.0)  # 1 時間 TTL

_DIAGNOSTIC_AGENT: Any = None
_REPAIR_AGENT: Any = None
_FAILURE_REPO: Any = None


def _get_diagnostic_agent() -> Any:
    global _DIAGNOSTIC_AGENT
    if _DIAGNOSTIC_AGENT is None:
        from agents.scraper_doctor import DiagnosticAgent

        _DIAGNOSTIC_AGENT = DiagnosticAgent(project_id=os.getenv("GCP_PROJECT_ID") or None)
    return _DIAGNOSTIC_AGENT


def _get_repair_agent() -> Any:
    global _REPAIR_AGENT
    if _REPAIR_AGENT is None:
        from agents.scraper_doctor import RepairProposalAgent

        _REPAIR_AGENT = RepairProposalAgent(project_id=os.getenv("GCP_PROJECT_ID") or None)
    return _REPAIR_AGENT


def _get_failure_repo() -> Any:
    global _FAILURE_REPO
    if _FAILURE_REPO is None:
        from agents.scraper_doctor.firestore_repo import FailureLogRepository

        _FAILURE_REPO = FailureLogRepository()
    return _FAILURE_REPO


@app.get("/v1/scraper-health")
async def get_scraper_health(
    response: Response,
    days: int = Query(default=7, ge=1, le=30),
    limit: int = Query(default=50, ge=1, le=100),
    use_sample: bool = Query(default=False, description="True なら sample seed を使用 (demo 用)"),
) -> dict:
    """Self-healing Scraper Agent endpoint (Plan F)。

    Firestore から失敗ログを取得 → 重複排除 → DiagnosticAgent + RepairProposalAgent で診断+提案。
    自動修正は実行しない (人間レビュー前提)。
    """
    from datetime import timedelta

    from agents.scraper_doctor.firestore_repo import dedupe_by_pattern
    from agents.scraper_doctor.schema import (
        ScraperHealthEntry,
        ScraperHealthResponse,
    )

    response.headers["Cache-Control"] = "private, max-age=0, no-cache"

    cache_key = ("scraper_health", days, limit, use_sample)
    cached = _SCRAPER_HEALTH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Step 1: 失敗ログを取得
    repo = _get_failure_repo()
    try:
        if use_sample:
            failures = repo.load_sample_seed()
        else:
            failures = repo.fetch_recent(days=days, limit=limit)
            # Firestore に何もなければ sample seed に fallback (MVP / demo 用)
            if not failures:
                logger.info("scraper_health.no_firestore_data falling_back_to_sample")
                failures = repo.load_sample_seed()
    except Exception as exc:  # noqa: BLE001
        logger.exception("scraper_health.fetch_failed err=%s", exc)
        raise HTTPException(status_code=500, detail=f"failure fetch failed: {exc!s}") from exc

    # Step 2: 重複排除 (scraper + error_type + html_signature)
    deduped = dedupe_by_pattern(failures)

    # Step 3: 各失敗を Agent 2 段階で処理 (Diagnostic → Repair)
    diagnostic_agent = _get_diagnostic_agent()
    repair_agent = _get_repair_agent()
    entries: list[ScraperHealthEntry] = []
    by_category: dict[str, int] = {}
    by_scraper: dict[str, int] = {}
    drop_candidates: list[str] = []

    for failure in deduped[:limit]:
        try:
            diagnostic = diagnostic_agent.diagnose(failure)
            proposal = repair_agent.propose(diagnostic, failure)
        except Exception as exc:  # noqa: BLE001
            # Agent クラッシュ時もスキップで継続 (1 失敗で全体死しない)
            logger.warning("scraper_health.agent_failed failure=%s err=%s", failure.failure_id, exc)
            continue

        entries.append(
            ScraperHealthEntry(failure=failure, diagnostic=diagnostic, proposal=proposal)
        )
        by_category[diagnostic.error_category] = by_category.get(diagnostic.error_category, 0) + 1
        by_scraper[failure.scraper] = by_scraper.get(failure.scraper, 0) + 1
        if (
            proposal.proposed_action == "drop_tenant"
            and failure.tenant_id
            and failure.tenant_id not in drop_candidates
        ):
            drop_candidates.append(failure.tenant_id)

    period_end = datetime.now(UTC)
    period_start = period_end - timedelta(days=days)

    response_obj = ScraperHealthResponse(
        period_start=period_start,
        period_end=period_end,
        total_failures=len(deduped),
        by_category=by_category,
        by_scraper=by_scraper,
        entries=entries,
        drop_candidates=drop_candidates,
    )

    result = response_obj.model_dump(mode="json")
    _SCRAPER_HEALTH_CACHE.set(cache_key, result)
    logger.info(
        "scraper_health.done days=%d n_failures=%d n_entries=%d n_drop_candidates=%d",
        days,
        len(deduped),
        len(entries),
        len(drop_candidates),
    )
    return result


# ============================================================================
# GET /v1/reasoning/explain — Reasoning Transparency Agent (Plan PP)
# ============================================================================
# 各 Agent (Concierge / Translator / Critic / Heatmap / Timeline / Forecast / Doctor)
# の reasoning を第三者観測者視点で再構成 (Reflexion / CoVe pattern)。
# on-demand: ユーザーがボタンクリック時のみ呼ばれる、cache なし。
# ============================================================================

_META_REASONER: Any = None


def _get_meta_reasoner() -> Any:
    global _META_REASONER
    if _META_REASONER is None:
        from agents.reasoner import MetaReasoningAgent

        _META_REASONER = MetaReasoningAgent(project_id=os.getenv("GCP_PROJECT_ID") or None)
    return _META_REASONER


@app.get("/v1/reasoning/explain")
async def get_reasoning_explain(
    response: Response,
    agent_name: str = Query(
        ...,
        description="対象 Agent 名 (7 種: concierge / translator / critic / heatmap_advisor / timeline / forecast / scraper_doctor)",
    ),
    raw_reasoning: str = Query(..., max_length=500, description="対象 Agent の reasoning"),
    agent_output_summary: str = Query(..., max_length=300, description="対象 Agent 出力要約"),
    persona_context: str | None = Query(default=None, max_length=200),
) -> dict:
    """Reasoning Transparency (Plan PP): 対象 Agent の reasoning を第三者視点で再構成。

    on-demand: ユーザーが UI でボタンクリック時のみ呼ばれる、cache なし。
    """
    from agents.reasoner.schema import ReasoningInspectInput

    response.headers["Cache-Control"] = "private, max-age=0, no-cache"

    try:
        inspect_input = ReasoningInspectInput(
            agent_name=agent_name,  # type: ignore[arg-type]
            raw_reasoning=raw_reasoning,
            agent_output_summary=agent_output_summary,
            persona_context=persona_context,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid reasoning input: {exc!s}") from exc

    reasoner = _get_meta_reasoner()
    try:
        explanation = reasoner.explain(inspect_input)
    except Exception as exc:  # noqa: BLE001
        logger.exception("reasoning.explain_failed agent=%s err=%s", agent_name, exc)
        raise HTTPException(status_code=500, detail=f"reasoning explain failed: {exc!s}") from exc

    logger.info(
        "reasoning.explain.done agent=%s source=%s confidence=%s",
        agent_name,
        explanation.source,
        explanation.confidence,
    )
    return explanation.model_dump(mode="json")


# ============================================================================
# GET /v1/cost-health — Cost Anomaly Hunter Agent (Plan CC)
# ============================================================================
# CostAnomalyDetector (純計算) + CostRootCauseAgent (LLM) で GCP cost data から
# 異常検知 + 根本原因診断 + 削減提案。自動 cost 削減 action は実装しない (人間レビュー前提)。
# MVP: Firestore 連携なし、infra/seed/cost_observations_sample.json から相対日付で fetch。
# ============================================================================


_COST_HEALTH_CACHE = _TTLCache(maxsize=32, ttl_sec=600.0)  # 10 分 TTL

_COST_DETECTOR: Any = None
_COST_ROOT_CAUSE_AGENT: Any = None


def _get_cost_detector() -> Any:
    global _COST_DETECTOR
    if _COST_DETECTOR is None:
        from agents.cost_hunter import CostAnomalyDetector

        _COST_DETECTOR = CostAnomalyDetector()
    return _COST_DETECTOR


def _get_cost_root_cause_agent() -> Any:
    global _COST_ROOT_CAUSE_AGENT
    if _COST_ROOT_CAUSE_AGENT is None:
        from agents.cost_hunter import CostRootCauseAgent

        _COST_ROOT_CAUSE_AGENT = CostRootCauseAgent(project_id=os.getenv("GCP_PROJECT_ID") or None)
    return _COST_ROOT_CAUSE_AGENT


@app.get("/v1/cost-health")
async def get_cost_health(
    response: Response,
    days: int = Query(default=30, ge=7, le=90),
    limit_entries: int = Query(default=20, ge=1, le=50),
) -> dict:
    """Cost Anomaly Hunter (Plan CC): sample seed → Detector → RootCauseAgent → 提案集約。

    自動 cost 削減 action は実行しない (人間レビュー前提、PROJECT.md §5)。
    """
    from agents.cost_hunter import (
        detect_cross_service_pattern,
        load_sample_seed,
    )
    from agents.cost_hunter.schema import (
        CostHealthEntry,
        CostHealthResponse,
    )

    response.headers["Cache-Control"] = "private, max-age=0, no-cache"

    cache_key = ("cost_health", days, limit_entries)
    cached = _COST_HEALTH_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Step 1: sample seed (将来 GCP Billing API 連携時に差し替え)
    observations = load_sample_seed()

    # Step 2: Detector で異常検知
    detector = _get_cost_detector()
    all_anomalies = detector.detect_anomalies(observations)

    # 重要 (spike/drift) のみ抽出、severity 降順 + spike_ratio 降順で sort
    significant = [a for a in all_anomalies if a.anomaly_type != "normal"]
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    significant.sort(
        key=lambda a: (
            severity_rank.get(a.severity, 99),
            -a.spike_ratio,
        )
    )
    significant = significant[:limit_entries]

    # Step 3: RootCauseAgent で各異常に提案
    root_cause_agent = _get_cost_root_cause_agent()
    entries: list[CostHealthEntry] = []
    estimated_total_savings = 0
    by_service: dict[str, int] = {}
    by_severity: dict[str, int] = {}

    for anomaly in significant:
        try:
            proposal = root_cause_agent.propose(anomaly, trend_summary="")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "cost_health.proposal_failed service=%s err=%s",
                anomaly.service,
                exc,
            )
            continue

        entries.append(CostHealthEntry(anomaly=anomaly, proposal=proposal))
        estimated_total_savings += proposal.monthly_savings_estimate_jpy
        by_service[anomaly.service] = by_service.get(anomaly.service, 0) + 1
        by_severity[anomaly.severity] = by_severity.get(anomaly.severity, 0) + 1

    # Step 4: 横断パターン (Reviewer Medium #4、Plan F 差別化)
    cross_pattern = detect_cross_service_pattern(all_anomalies)

    today = datetime.now(UTC).date()
    response_obj = CostHealthResponse(
        period_start=today - timedelta(days=days),
        period_end=today,
        total_anomalies=len(significant),
        by_service=by_service,
        by_severity=by_severity,
        estimated_total_savings_jpy=estimated_total_savings,
        entries=entries,
        cross_service_pattern=cross_pattern,
    )

    result = response_obj.model_dump(mode="json")
    _COST_HEALTH_CACHE.set(cache_key, result)
    logger.info(
        "cost_health.done days=%d n_anomalies=%d n_entries=%d estimated_savings=¥%d cross=%s",
        days,
        len(significant),
        len(entries),
        estimated_total_savings,
        bool(cross_pattern),
    )
    return result


# ============================================================================
# Ops Crew (運用 SRE マルチエージェントクルー) — DevOps × AI Agent
# ============================================================================
# Watcher と同一パターン(計画→並列専門家→統合→批判→人間/ブラスト半径ゲート)を
# 「自分たちの運用」に適用。scraper_doctor + cost_hunter + データ鮮度を1つの
# 自律クルーが統括し「今いちばん人間が対処すべき運用課題」を提案する(自動実行はしない)。
#   - GET /v1/ops/health : クルーを実行し assessment + 自律実行トレースを返す (5分 TTL)
# 認可: OPS_ADMIN_TOKEN 環境変数が設定されていれば x-admin-token 一致を要求 (server-side secret)。
# ============================================================================

_ops_crew_cache: Any = None
_OPS_HEALTH_CACHE = _TTLCache(maxsize=8, ttl_sec=300.0)
_OPS_LIMITER = _RateLimiter(limit=30, window_sec=600.0)


def _get_ops_crew_agent() -> Any:
    """OpsCrewAgent を遅延初期化 (テストで monkeypatch 可)。"""
    global _ops_crew_cache
    if _ops_crew_cache is None:
        from agents.ops_crew import OpsCrewAgent

        _ops_crew_cache = OpsCrewAgent(project_id=BQ_PROJECT)
    return _ops_crew_cache


def _require_ops_admin(x_admin_token: str | None) -> None:
    """OPS_ADMIN_TOKEN が設定されていれば x-admin-token 一致を要求 (未設定なら dev 許可)。

    NEXT_PUBLIC_* と違い server-side env なのでクライアントバンドルに漏れない。
    """
    expected = os.getenv("OPS_ADMIN_TOKEN")
    if expected and x_admin_token != expected:
        raise HTTPException(status_code=403, detail="invalid or missing x-admin-token")


def _ops_freshness_hours() -> float | None:
    """scored_speeches_latest の最終取込からの経過時間 (h)。失敗時 None (graceful)。"""
    try:
        from datetime import UTC, datetime

        client = _get_bq_client()
        table_fqn = f"{BQ_PROJECT}.{BQ_DATASET_CURATED}.{BQ_VIEW_SCORED_LATEST}"
        q = f"SELECT MAX(ingested_at) AS latest FROM `{table_fqn}`"  # noqa: S608 (table名はenv由来)
        rows = list(client.query(q).result())
        if not rows or rows[0].latest is None:
            return None
        return max(0.0, (datetime.now(UTC) - rows[0].latest).total_seconds() / 3600.0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ops.freshness_failed err=%s", exc)
        return None


@app.get("/v1/ops/health")
async def get_ops_health(
    response: Response,
    days: int = Query(7, ge=1, le=30),
    use_sample: bool = Query(True),
    x_admin_token: str | None = Header(default=None, alias="x-admin-token"),
) -> dict:
    """運用 SRE クルーを実行し、assessment + 自律トレースを返す (DevOps × AI Agent の実証)。"""
    _require_ops_admin(x_admin_token)
    _enforce_rate_limit(_OPS_LIMITER, "ops_health", 60)

    cache_key = (days, use_sample)
    cached = _OPS_HEALTH_CACHE.get(cache_key)
    if cached is not None:
        response.headers["Cache-Control"] = "max-age=300"
        return cached

    crew = _get_ops_crew_agent()
    freshness = _ops_freshness_hours()
    try:
        result = await crew.run(days=days, use_sample=use_sample, freshness_hours=freshness)
    except Exception as exc:  # noqa: BLE001 (crew は本来投げないが二重防御)
        logger.exception("ops.health_failed err=%s", exc)
        raise HTTPException(status_code=500, detail=f"ops crew failed: {exc!s}") from exc

    payload = {
        "assessment": result.assessment.model_dump(mode="json") if result.assessment else None,
        "run_log": result.run_log.model_dump(mode="json"),
        "freshness_hours": freshness,
    }
    _OPS_HEALTH_CACHE.set(cache_key, payload)
    response.headers["Cache-Control"] = "max-age=300"
    return payload


# ============================================================================
# Watcher (マイ街エージェント / TASK-WATCHER Slice 3) — 自律型 Civic Watch Agent
# ============================================================================
# 自律エージェント (ADK Runner) = 街選びアナリスト。住む街(基準)と気になる街(候補)を
# 多軸比較し「移るべきか/移るならどこか」の生きた結論を出す。
#   - GET  /v1/watcher/{user_id}/analysis  : 比較+生きた結論 + 最新実行ログ (自律証跡)
#   - GET  /v1/watcher/{user_id}/watchlist   : 保存済ウォッチ街
#   - PUT  /v1/watcher/{user_id}/watchlist   : ウォッチ街を保存
#   - POST /v1/watcher/{user_id}/run         : エージェントをその場で自律実行 (ADK、5-20s)
# 認可は concierge history と同じ x-user-id header 簡易方式 (demo)。
# ============================================================================


_watcher_repo_cache: Any = None
_watcher_agent_cache: Any = None


def _get_watcher_repo() -> Any:
    """WatcherRepository を遅延初期化 (Firestore client 注入、テストで monkeypatch 可)。"""
    global _watcher_repo_cache
    if _watcher_repo_cache is None:
        from agents.watcher.repo import WatcherRepository

        _watcher_repo_cache = WatcherRepository(firestore_client=_get_firestore_client())
    return _watcher_repo_cache


def _get_watcher_agent() -> Any:
    """WatcherAgent を遅延初期化 (ADK は WatcherAgent 内で更に lazy import)。

    run 以外の経路では呼ばれないため、discoveries/watchlist 取得で ADK は読み込まれない。
    テストでは monkeypatch して mock を注入する。
    """
    global _watcher_agent_cache
    if _watcher_agent_cache is None:
        from agents.watcher.main import WatcherAgent

        _watcher_agent_cache = WatcherAgent(project_id=BQ_PROJECT, repo=_get_watcher_repo())
    return _watcher_agent_cache


def _require_watcher_user(user_id: str, x_user_id: str | None) -> None:
    """demo 簡易認可: path user_id と header x-user-id の一致を要求 (concierge と同方式)。"""
    if x_user_id is None or x_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="x-user-id header must match path user_id (demo 認可)",
        )


class WatchlistBody(BaseModel):
    """ウォッチ街の保存 / 実行入力 (user_id は path から取るので body には含めない)。"""

    age_group: str = Field(description="年代 (18-24/25-29/30-39/40-49/50+)")
    interests: list[str] = Field(default_factory=list)
    home_municipality_code: str = Field(description="住む街 (5 桁)")
    watched_codes: list[str] = Field(
        default_factory=list, description="気になる街 (home 含め上限 5)"
    )
    # TASK-ONBOARDING: 前提整理 (全て省略可・後方互換)
    priorities: list[str] = Field(default_factory=list)
    household: str = Field(default="")
    budget_man: int | None = Field(default=None)
    free_form_context: str = Field(default="")


NATIONAL_DIET_CODE = "00000"  # 国会: エージェントの街選びウォッチ対象からは除外


def _to_watch_input(user_id: str, body: WatchlistBody) -> Any:
    """WatchlistBody → WatchInput。国会(00000)を除外し、enum 不一致は 400 に変換 (graceful)。

    国会は「住む街(=移住判断の基準)」ではないため、エージェントのウォッチ対象から外す。
    home が 00000 の場合は watched 先頭を home に昇格。実在する街が無ければ 400。
    """
    from agents.watcher.schema import WatchInput
    from pydantic import ValidationError

    watched = [c for c in body.watched_codes if c and c != NATIONAL_DIET_CODE]
    home = body.home_municipality_code
    if home == NATIONAL_DIET_CODE or not home:
        if not watched:
            raise HTTPException(
                status_code=400,
                detail="国会(00000)以外の実在する街を住む街として登録してください",
            )
        home = watched.pop(0)

    try:
        return WatchInput(
            user_id=user_id,
            age_group=body.age_group,  # type: ignore[arg-type]
            interests=body.interests,  # type: ignore[arg-type]
            home_municipality_code=home,
            watched_codes=watched,
            priorities=body.priorities,  # type: ignore[arg-type]
            household=body.household,
            budget_man=body.budget_man,
            free_form_context=body.free_form_context,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"invalid watchlist: {exc!s}") from exc


@app.get("/v1/watcher/{user_id}/analysis")
async def get_watcher_analysis(
    user_id: str,
    response: Response,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> dict:
    """エージェントの街選び分析 (比較 + 生きた結論) + 最新実行ログ (自律証跡)。

    latest_run.tool_calls が「LLM が自分で選んだ調査計画」= ①自律性の可視化。
    分析が未生成でも 200 (analysis=null)。
    """
    _require_watcher_user(user_id, x_user_id)
    response.headers["Cache-Control"] = "private, max-age=0, no-cache"

    repo = _get_watcher_repo()
    analysis = repo.get_latest_analysis(user_id)
    latest = repo.get_latest_run(user_id)
    logger.info(
        "watcher.analysis.done user_id=%s has_analysis=%s has_run=%s",
        user_id,
        analysis is not None,
        latest is not None,
    )
    return {
        "user_id": user_id,
        "analysis": analysis.model_dump() if analysis else None,
        "latest_run": latest.model_dump() if latest else None,
    }


@app.get("/v1/watcher/{user_id}/watchlist")
async def get_watcher_watchlist(
    user_id: str,
    response: Response,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> dict | None:
    """保存済のウォッチ街を返す (未設定なら null)。"""
    _require_watcher_user(user_id, x_user_id)
    response.headers["Cache-Control"] = "private, max-age=0, no-cache"
    wl = _get_watcher_repo().get_watchlist(user_id)
    return wl.model_dump() if wl else None


@app.put("/v1/watcher/{user_id}/watchlist")
async def put_watcher_watchlist(
    user_id: str,
    body: WatchlistBody,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> dict:
    """ウォッチ街を保存 (home + watched、上限 5 は all_codes で truncate)。"""
    _require_watcher_user(user_id, x_user_id)
    watch = _to_watch_input(user_id, body)
    if not _get_watcher_repo().save_watchlist(watch):
        raise HTTPException(status_code=500, detail="failed to save watchlist")
    logger.info("watcher.watchlist.saved user_id=%s towns=%s", user_id, watch.all_codes())
    return watch.model_dump()


async def _execute_watcher_run_bg(user_id: str, watch: Any, town_names: dict[str, str]) -> None:
    """エージェントをバックグラウンドで自律実行し Firestore に永続化 (非同期 /run の本体)。

    完了結果は repo 経由で保存され、クライアントは GET /analysis のポーリングで新 run_id を検知する。
    Cloud Run の応答後 CPU 割当が必要 (cloudbuild の --no-cpu-throttling)。例外は握り潰さずログのみ。
    """
    try:
        result = await _get_watcher_agent().run(watch, town_names=town_names)
        logger.info(
            "watcher.run.done(bg) user_id=%s status=%s towns_assessed=%d n_tool_calls=%d",
            user_id,
            result.run_log.status,
            result.run_log.n_discoveries,
            len(result.run_log.tool_calls),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("watcher.run_failed(bg) user_id=%s err=%s", user_id, exc)


@app.post("/v1/watcher/{user_id}/run", status_code=202)
async def run_watcher(
    user_id: str,
    response: Response,
    background_tasks: BackgroundTasks,
    body: WatchlistBody | None = None,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> dict:
    """エージェントを **非同期** に自律実行 (202 即時応答、分析は背景で 2-3 分)。

    body があれば watchlist を更新してから実行、無ければ保存済を使用。
    重い分析はバックグラウンド実行し、クライアントは GET /analysis を **新 run_id までポーリング**する
    (アドバイザーが裏で調べてレポートを出す体験 / 同期待ちの解消)。
    ツール選択は LLM に委任 (スクリプト化しない) = ①自律性。倫理ゲート・コスト bound は Agent 側で継承。
    """
    _require_watcher_user(user_id, x_user_id)
    # レート制限 (W3): 背景 ADK 自律実行はコストが大きいので user_id 毎に上限
    _enforce_rate_limit(_WATCHER_RUN_LIMITER, f"watcher_run:{user_id}", 60)
    response.headers["Cache-Control"] = "no-store"

    repo = _get_watcher_repo()
    if body is not None:
        watch = _to_watch_input(user_id, body)
        repo.save_watchlist(watch)
    else:
        watch = repo.get_watchlist(user_id)
        if watch is None:
            raise HTTPException(
                status_code=400,
                detail="no watchlist saved; provide a body or PUT /watchlist first",
            )

    # 出力文章で街名を使わせるため、コード→名前を解決して渡す
    town_names = {c: _muni_label(c) for c in watch.all_codes()}
    background_tasks.add_task(_execute_watcher_run_bg, user_id, watch, town_names)
    logger.info("watcher.run.accepted user_id=%s towns=%s", user_id, watch.all_codes())
    return {"status": "running", "towns": watch.all_codes()}


# TASK-ONBOARDING (F): 自由記述から移住の前提を抽出 (フォーム自動プリフィル用)
class PreferenceExtractBody(BaseModel):
    """POST /v1/preferences/extract の body。"""

    text: str = Field(min_length=1, max_length=2000, description="ユーザーの自由記述")


@app.post("/v1/preferences/extract")
async def extract_preferences_endpoint(body: PreferenceExtractBody) -> dict:
    """自由記述から {interests, priorities, household, budget_man, background_summary} を抽出。

    オンボーディングのフォームを自動プリフィルする (ユーザーが必ず確認・編集)。失敗時は空。
    """
    from agents.preferences.extract import extract_preferences

    try:
        extracted = await extract_preferences(body.text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("preferences.extract_failed err=%s", exc)
        extracted = {
            "interests": [],
            "priorities": [],
            "household": "",
            "budget_man": None,
            "background_summary": "",
        }
    logger.info("preferences.extract.done interests=%d", len(extracted.get("interests", [])))
    return {"extracted": extracted}


# 移住アクションプラン (TASK-ACTIONPLAN): Watcher 分析を行動プランに変換 (run_id でキャッシュ)
_PLAN_CACHE = _TTLCache(maxsize=512, ttl_sec=3600.0)


@app.get("/v1/watcher/{user_id}/plan")
async def get_watcher_action_plan(
    user_id: str,
    response: Response,
    x_user_id: str | None = Header(default=None, alias="x-user-id"),
) -> dict:
    """移住アクションプラン (最新分析の出口)。分析未生成なら plan=null。

    結論は生成せず Watcher の TownAnalysis を再利用。生成は訪問チェックリストのみ。
    run_id でキャッシュ (同じ分析なら再生成しない)。
    """
    _require_watcher_user(user_id, x_user_id)
    response.headers["Cache-Control"] = "private, max-age=0, no-cache"

    from agents.watcher.action_plan import (
        DEFAULT_MODEL,
        assemble_action_plan,
        generate_visit_checklist,
        select_recommended,
    )

    repo = _get_watcher_repo()
    analysis = repo.get_latest_analysis(user_id)
    if analysis is None:
        return {"user_id": user_id, "plan": None}

    latest = repo.get_latest_run(user_id)
    run_id = latest.run_id if latest else ""
    cache_key = ("plan", user_id, run_id)
    if run_id:
        cached = _PLAN_CACHE.get(cache_key)
        if cached is not None:
            return {"user_id": user_id, "plan": cached.model_dump()}

    sel = select_recommended(analysis)
    if sel is None:
        return {"user_id": user_id, "plan": None}
    rec, mode = sel
    name = _muni_label(rec.municipality_code)
    model = getattr(_get_watcher_agent(), "model", None) or DEFAULT_MODEL
    checklist = await generate_visit_checklist(rec, name, mode, model=model)
    generated_at = datetime.now(UTC).isoformat()
    plan = assemble_action_plan(
        analysis, {rec.municipality_code: name}, checklist, run_id, generated_at
    )
    if plan is None:
        return {"user_id": user_id, "plan": None}

    # TASK-SUPPORT P1: 国の移住支援金マッチング (現住所/世帯は watchlist 由来)。
    # ※ analysis(TownAnalysis) は home/household を持たないため watchlist を引く。
    from agents.watcher.schema import RelocationSupport
    from agents.watcher.support import extract_local_support, match_national_support

    watch = repo.get_watchlist(user_id)
    national = match_national_support(
        home_code=watch.home_municipality_code if watch else "",
        recommended_code=plan.recommended_code,
        household=watch.household if watch else "",
    )
    # P2: 自治体独自支援を google_search グラウンディングで抽出 (失敗時は空・graceful)
    local = await extract_local_support(name, plan.recommended_code)
    plan.support = RelocationSupport(national=national, local=local)

    if run_id:
        _PLAN_CACHE.set(cache_key, plan)
    logger.info(
        "watcher.plan.done user_id=%s mode=%s code=%s checklist=%d",
        user_id,
        plan.mode,
        plan.recommended_code,
        len(plan.visit_checklist),
    )
    return {"user_id": user_id, "plan": plan.model_dump()}
