"""RelevanceCacheRepository: relevance スコアの Firestore キャッシュ層 (TASK-CACHE)。

設計:
    - Firestore collection `relevance_score_cache` に 1 (speech_id, user_id) = 1 doc
        doc id: `{safe_speech_id}__{user_id}` (`:` `/` を `_` にエスケープ)
        doc fields: speech_id, user_id, relevance_output(dict), cached_at,
                    expires_at(TTL), prompt_version
    - 同じ speech × persona の再採点 (再 publish-all / persona 追加 / cron) で
      Vertex AI Gemini 呼び出しを skip し quota + コスト節約 (429 再発防止の保険)
    - batch_get は client.get_all([...]) で 1 往復、N+1 を回避
    - 全 method graceful: Firestore 障害時も例外を呼び出し元に投げず
      None / {} / False を返す (publish 自体は cache 無関係に継続)

倫理 (PROJECT.md §5):
    - cache されるのは relevance score のみ (政治家名/賛否は RelevanceOutput
      の contains_political_judgment / below_threshold で既に除去済)
    - prompt 変更時は prompt_version mismatch で自動 miss → 古い score を配信しない
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .schema import PersonaRelevanceOutput

logger = logging.getLogger(__name__)

# ============================================================================
# 定数
# ============================================================================

FIRESTORE_COLLECTION_CACHE = "relevance_score_cache"
DEFAULT_TTL_DAYS = 7

# prompt を変更したらこの値を上げる → 古い cache は自動 miss 扱いになる
PROMPT_VERSION = "v1.0"


# ============================================================================
# データ型
# ============================================================================


@dataclass
class RelevanceCacheEntry:
    """Firestore に保存される 1 (speech_id, user_id) 分の cache レコード。"""

    speech_id: str
    user_id: str
    output: PersonaRelevanceOutput
    cached_at: datetime
    expires_at: datetime  # Firestore TTL policy の対象 field
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        """Firestore 用 dict。"""
        return {
            "speech_id": self.speech_id,
            "user_id": self.user_id,
            "relevance_output": self.output.model_dump(),
            "cached_at": self.cached_at,
            "expires_at": self.expires_at,
            "prompt_version": self.prompt_version,
        }


# ============================================================================
# RelevanceCacheRepository
# ============================================================================


class RelevanceCacheRepository:
    """relevance スコアの Firestore キャッシュ。

    Args:
        firestore_client: Firestore client (テスト用 mock 注入)
        ttl_days: cache entry の有効日数 (expires_at = now + ttl_days)
        prompt_version: 現行 prompt バージョン (mismatch の doc は miss 扱い)
    """

    def __init__(
        self,
        firestore_client: Any | None = None,
        ttl_days: int = DEFAULT_TTL_DAYS,
        prompt_version: str = PROMPT_VERSION,
    ) -> None:
        self._firestore_client = firestore_client
        self.ttl_days = ttl_days
        self.prompt_version = prompt_version

    def _client(self) -> Any:
        """Firestore client を遅延取得 (concierge/memory.py と同パターン)。"""
        if self._firestore_client is not None:
            return self._firestore_client
        from google.cloud import firestore

        self._firestore_client = firestore.Client()
        return self._firestore_client

    def _collection(self) -> Any:
        return self._client().collection(FIRESTORE_COLLECTION_CACHE)

    @staticmethod
    def _make_doc_id(speech_id: str, user_id: str) -> str:
        """Firestore doc ID を生成。

        Firestore doc ID は `/` 禁止。`:` は許可だが安全側で `_` にエスケープ。
        speech_id 自体に `__` が含まれても user_id は末尾 1 個の `__` 区切りで
        復元可能 (本実装は doc_id を key としてしか使わないため衝突回避が目的)。
        """
        safe_speech = speech_id.replace(":", "_").replace("/", "_")
        return f"{safe_speech}__{user_id}"

    def _doc_to_output(self, data: dict[str, Any]) -> PersonaRelevanceOutput | None:
        """Firestore doc dict → PersonaRelevanceOutput。

        prompt_version 不一致は miss 扱い (None)。parse 失敗も graceful (None)。
        """
        if data.get("prompt_version") != self.prompt_version:
            return None
        raw = data.get("relevance_output")
        if not isinstance(raw, dict):
            return None
        try:
            return PersonaRelevanceOutput.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("relevance_cache.parse_failed err=%s", exc)
            return None

    # ------------------------------------------------------------------------
    # read
    # ------------------------------------------------------------------------

    def get_cached(self, speech_id: str, user_id: str) -> PersonaRelevanceOutput | None:
        """1 件 lookup。miss / prompt mismatch / Firestore 失敗時は None。"""
        doc_id = self._make_doc_id(speech_id, user_id)
        try:
            snap = self._collection().document(doc_id).get()
            if not getattr(snap, "exists", False):
                return None
            return self._doc_to_output(snap.to_dict() or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "relevance_cache.get_failed speech_id=%s user=%s err=%s",
                speech_id,
                user_id,
                exc,
            )
            return None

    def batch_get(self, speech_id: str, user_ids: list[str]) -> dict[str, PersonaRelevanceOutput]:
        """N persona を 1 往復で lookup。hit したものだけ {user_id: output} で返す。

        client.get_all([doc_ref, ...]) で N+1 を回避。Firestore 失敗時は {} (全 miss)。
        """
        if not user_ids:
            return {}
        try:
            collection = self._collection()
            id_by_doc = {self._make_doc_id(speech_id, uid): uid for uid in user_ids}
            doc_refs = [collection.document(doc_id) for doc_id in id_by_doc]
            snaps = self._client().get_all(doc_refs)
            result: dict[str, PersonaRelevanceOutput] = {}
            for snap in snaps:
                if not getattr(snap, "exists", False):
                    continue
                uid = id_by_doc.get(snap.id)
                if uid is None:
                    continue
                output = self._doc_to_output(snap.to_dict() or {})
                if output is not None:
                    result[uid] = output
            return result
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "relevance_cache.batch_get_failed speech_id=%s n=%d err=%s",
                speech_id,
                len(user_ids),
                exc,
            )
            return {}

    # ------------------------------------------------------------------------
    # write
    # ------------------------------------------------------------------------

    def _build_entry(
        self, speech_id: str, user_id: str, output: PersonaRelevanceOutput
    ) -> RelevanceCacheEntry:
        now = datetime.now(UTC)
        return RelevanceCacheEntry(
            speech_id=speech_id,
            user_id=user_id,
            output=output,
            cached_at=now,
            expires_at=now + timedelta(days=self.ttl_days),
            prompt_version=self.prompt_version,
        )

    def save(self, speech_id: str, user_id: str, output: PersonaRelevanceOutput) -> bool:
        """1 件書き込み。failure は graceful (False、例外は raise しない)。"""
        doc_id = self._make_doc_id(speech_id, user_id)
        entry = self._build_entry(speech_id, user_id, output)
        try:
            self._collection().document(doc_id).set(entry.to_dict())
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "relevance_cache.save_failed speech_id=%s user=%s err=%s",
                speech_id,
                user_id,
                exc,
            )
            return False

    def batch_save(
        self,
        speech_id: str,
        persona_outputs: list[tuple[str, PersonaRelevanceOutput]],
    ) -> int:
        """N persona を Firestore batch write で一括保存。成功件数を返す。

        batch commit 失敗時は 0 (graceful)。publish には影響しない。
        """
        if not persona_outputs:
            return 0
        try:
            client = self._client()
            collection = self._collection()
            batch = client.batch()
            for user_id, output in persona_outputs:
                doc_id = self._make_doc_id(speech_id, user_id)
                entry = self._build_entry(speech_id, user_id, output)
                batch.set(collection.document(doc_id), entry.to_dict())
            batch.commit()
            return len(persona_outputs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "relevance_cache.batch_save_failed speech_id=%s n=%d err=%s",
                speech_id,
                len(persona_outputs),
                exc,
            )
            return 0
