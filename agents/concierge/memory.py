"""ConversationMemory: Concierge 会話履歴の永続化 + 類似検索 (Plan L+LL)。

設計:
    - Firestore: collection `concierge_history` に 1 turn = 1 doc 保存
        doc fields: user_id, timestamp, message, reply, short_summary,
                    candidates_codes, matched_interests, embedding[768]
    - Vertex AI text-multilingual-embedding-002 で embedding 計算
    - 類似検索: 直近 50 turn を Firestore で fetch → in-memory cosine similarity
        (Firestore Vector Search は preview なので採用見送り、scale 観点
         50 turn 制限で十分)
    - matched_interests: rule-based 固定辞書で抽出 (LLM call なし、save 高速)

倫理 (PROJECT.md §5):
    - 保存されるのは Concierge 応答そのもので、政治家名/賛否は既に Concierge
      reply post-validation で除去済 (agents/concierge/main.py の find_forbidden_matches)
    - 認可: ConciergeAgent / endpoint 層で user_id チェック (本 module は trust)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agents.concierge.schema import MunicipalityCandidate
from agents.relevance.schema import Interest

logger = logging.getLogger(__name__)

# ============================================================================
# 定数
# ============================================================================

FIRESTORE_COLLECTION_HISTORY = "concierge_history"

# Vertex AI Embedding model
DEFAULT_EMBEDDING_MODEL = "text-multilingual-embedding-002"
EMBEDDING_DIM = 768

# Recall 時の Firestore scan 上限 (scale 防止)
DEFAULT_RECALL_SCAN_LIMIT = 50

# matched_interests 抽出用 rule-based 辞書
# (LLM call せず、message + reply 文字列 contains 判定で interest を推定)
INTEREST_KEYWORDS: dict[Interest, list[str]] = {
    "住居": ["家賃", "マンション", "アパート", "持ち家", "賃貸", "住宅", "中古"],
    "雇用": ["仕事", "転職", "リモートワーク", "テレワーク", "就職", "求人"],
    "結婚": ["結婚", "婚活", "パートナー", "配偶者"],
    "子育て": ["子育て", "保育園", "幼稚園", "待機児童", "学童", "ベビーシッター"],
    "税": ["税金", "ふるさと納税", "減税", "控除", "市民税"],
    "起業": ["起業", "スタートアップ", "個人事業", "フリーランス", "副業"],
    "防災": ["地震", "津波", "避難所", "ハザードマップ", "防災", "災害"],
    "医療": ["医療", "病院", "クリニック", "介護", "診療所", "救急", "通院"],
    "教育": ["学校", "教育", "進学", "塾", "受験", "高校", "大学"],
    "移住": ["移住", "Uターン", "Iターン", "引っ越し", "移転", "実家"],
}


# ============================================================================
# データ型
# ============================================================================


@dataclass
class HistoryRecord:
    """Firestore に保存される 1 turn 分のレコード。"""

    doc_id: str
    user_id: str
    timestamp: datetime
    message: str
    reply: str
    short_summary: str  # reply[:100]、UI 表示用
    candidates_codes: list[str] = field(default_factory=list)
    matched_interests: list[Interest] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)
    similarity_score: float | None = None  # recall_similar の戻り値で設定

    def to_dict(self) -> dict[str, Any]:
        """Firestore 用 dict。"""
        return {
            "user_id": self.user_id,
            "timestamp": self.timestamp,
            "message": self.message,
            "reply": self.reply,
            "short_summary": self.short_summary,
            "candidates_codes": list(self.candidates_codes),
            "matched_interests": list(self.matched_interests),
            "embedding": list(self.embedding),
        }

    @classmethod
    def from_doc(cls, doc_id: str, data: dict[str, Any]) -> HistoryRecord:
        """Firestore doc → HistoryRecord。"""
        return cls(
            doc_id=doc_id,
            user_id=data.get("user_id", ""),
            timestamp=data.get("timestamp") or datetime.now(UTC),
            message=data.get("message", ""),
            reply=data.get("reply", ""),
            short_summary=data.get("short_summary", ""),
            candidates_codes=list(data.get("candidates_codes", [])),
            matched_interests=list(data.get("matched_interests", [])),
            embedding=list(data.get("embedding", [])),
        )


# ============================================================================
# rule-based interest 抽出
# ============================================================================


def extract_interests(text: str) -> list[Interest]:
    """text (user message + agent reply) から rule-based で interest を抽出。

    LLM call なし、固定辞書の部分一致で判定。重複なしで返す。
    """
    found: list[Interest] = []
    for interest, keywords in INTEREST_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found.append(interest)
    return found


# ============================================================================
# Embedding 計算 (Vertex AI text-multilingual-embedding-002)
# ============================================================================


def _embed_text(text: str, model_name: str = DEFAULT_EMBEDDING_MODEL) -> list[float]:
    """Vertex AI Text Embedding API で text を embedding (len=768) に変換。

    遅延 import (test で mock 可能)。
    """
    from vertexai.language_models import TextEmbeddingModel

    model = TextEmbeddingModel.from_pretrained(model_name)
    # text 全体 (最大 2000 tokens) を 1 embedding に
    response = model.get_embeddings([text[:8000]])  # text-multilingual は max ~3000 tokens
    if not response:
        raise RuntimeError("Vertex AI embedding returned empty result")
    return list(response[0].values)


# ============================================================================
# cosine similarity (in-memory)
# ============================================================================


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """2 つの embedding の cosine similarity。長さ違いや zero vector は 0.0。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ============================================================================
# ConversationMemory
# ============================================================================


class ConversationMemory:
    """Concierge 会話履歴の永続化 + 類似検索層。

    Args:
        firestore_client: Firestore client (テスト用 mock 注入)
        embed_fn: text -> embedding 関数 (テスト用 mock 注入)
        recall_scan_limit: recall_similar で fetch する直近 turn 数 上限
    """

    def __init__(
        self,
        firestore_client: Any | None = None,
        embed_fn: Any | None = None,
        recall_scan_limit: int = DEFAULT_RECALL_SCAN_LIMIT,
    ) -> None:
        self._firestore_client = firestore_client
        self._embed_fn = embed_fn or _embed_text
        self.recall_scan_limit = recall_scan_limit

    def _client(self) -> Any:
        """Firestore client を遅延取得。"""
        if self._firestore_client is not None:
            return self._firestore_client
        from google.cloud import firestore

        self._firestore_client = firestore.Client()
        return self._firestore_client

    # ------------------------------------------------------------------------
    # save_turn
    # ------------------------------------------------------------------------

    def save_turn(
        self,
        user_id: str,
        message: str,
        reply: str,
        candidates: list[MunicipalityCandidate] | None = None,
    ) -> str:
        """1 turn を Firestore に保存。doc_id を返す。

        Args:
            user_id: ペルソナ ID
            message: ユーザー入力
            reply: Concierge 応答 (倫理 post-validation 済を想定)
            candidates: search_municipalities の結果 (任意)

        Returns:
            Firestore doc_id (`{user_id}__{timestamp_iso}` 形式)
        """
        ts = datetime.now(UTC)
        doc_id = f"{user_id}__{ts.isoformat()}"

        # rule-based で interests 抽出
        combined_text = f"{message}\n{reply}"
        interests = extract_interests(combined_text)

        # embedding 計算 (失敗時は空 list で graceful)
        try:
            embedding = self._embed_fn(combined_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory.embed_failed user_id=%s err=%s", user_id, exc)
            embedding = []

        record = HistoryRecord(
            doc_id=doc_id,
            user_id=user_id,
            timestamp=ts,
            message=message[:2000],  # safety truncate
            reply=reply[:2000],
            short_summary=reply[:100],
            candidates_codes=[c.municipality_code for c in (candidates or [])],
            matched_interests=interests,
            embedding=embedding,
        )

        try:
            self._client().collection(FIRESTORE_COLLECTION_HISTORY).document(doc_id).set(
                record.to_dict()
            )
            logger.info(
                "memory.saved user_id=%s doc_id=%s interests=%s n_candidates=%d",
                user_id,
                doc_id,
                interests,
                len(record.candidates_codes),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("memory.save_failed user_id=%s err=%s", user_id, exc)
            # 例外を呼び出し元に投げず、graceful (recall がない state に劣化するだけ)

        return doc_id

    # ------------------------------------------------------------------------
    # recall_similar (L: 類似検索)
    # ------------------------------------------------------------------------

    def recall_similar(
        self,
        user_id: str,
        query: str,
        limit: int = 3,
    ) -> list[HistoryRecord]:
        """user_id の過去対話から query と類似する top-N を返す。

        Process:
            1. Firestore で user_id 一致の直近 recall_scan_limit 件 fetch
            2. query を embedding 化
            3. 各 record の embedding と cosine similarity 計算
            4. 降順 sort して top-N 返す (similarity_score 付与)
        """
        # Step 1: 直近 turn を fetch
        records = self.recall_recent(user_id, limit=self.recall_scan_limit)
        if not records:
            return []

        # Step 2: query を embedding 化
        try:
            query_embedding = self._embed_fn(query)
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory.recall_embed_failed user_id=%s err=%s", user_id, exc)
            return records[:limit]  # fallback: 直近順

        # Step 3: 各 record と cosine similarity
        scored: list[HistoryRecord] = []
        for r in records:
            if not r.embedding:
                continue
            r.similarity_score = cosine_similarity(query_embedding, r.embedding)
            scored.append(r)

        # Step 4: 降順 sort
        scored.sort(key=lambda x: x.similarity_score or 0.0, reverse=True)
        return scored[:limit]

    # ------------------------------------------------------------------------
    # recall_recent (時系列)
    # ------------------------------------------------------------------------

    def recall_recent(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[HistoryRecord]:
        """user_id の直近 N turn を timestamp 降順で返す。"""
        try:
            # firestore.Query.DESCENDING はモジュール import 不要、文字列リテラルで OK
            query = (
                self._client()
                .collection(FIRESTORE_COLLECTION_HISTORY)
                .where("user_id", "==", user_id)
                .order_by("timestamp", direction="DESCENDING")
                .limit(limit)
            )
            docs = list(query.stream())
        except Exception as exc:  # noqa: BLE001
            logger.warning("memory.recall_recent_failed user_id=%s err=%s", user_id, exc)
            return []

        return [HistoryRecord.from_doc(doc.id, doc.to_dict() or {}) for doc in docs]

    # ------------------------------------------------------------------------
    # cross_reference (LL: 過去関心 × 新着議題)
    # ------------------------------------------------------------------------

    def get_past_interests(self, user_id: str, limit: int = 20) -> list[Interest]:
        """user_id の過去対話から登場した interest 軸をユニーク降順で返す。

        頻度の高い順 (recall_recent の結果から集計)。
        """
        records = self.recall_recent(user_id, limit=limit)
        from collections import Counter

        counter: Counter[str] = Counter()
        for r in records:
            counter.update(r.matched_interests)

        # 頻度降順、type Interest を保持
        ranked: list[Interest] = []
        for interest, _ in counter.most_common():
            ranked.append(interest)  # type: ignore[arg-type]
        return ranked
