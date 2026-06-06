"""WatcherRepository: マイ街エージェントの Firestore 永続化層 (TASK-WATCHER Slice 2)。

3 コレクション:
    - user_watchlist     (doc id = user_id)            : ウォッチ街リスト
    - watcher_agent_runs (doc id = run_id)             : 自律実行ログ (tool_calls 等)
    - watcher_discoveries(doc id = {user_id}__{run_id}__{idx}) : 発見

設計: relevance/cache.py と同じ graceful パターン。全 method は Firestore 障害時も
例外を投げず None / [] / False / 0 を返す (エージェント実行は永続化と無関係に継続)。
lazy client init、テストは firestore_client mock 注入。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .schema import AgentRunLog, Discovery, WatchInput

logger = logging.getLogger(__name__)

FIRESTORE_WATCHLIST = "user_watchlist"
FIRESTORE_RUNS = "watcher_agent_runs"
FIRESTORE_DISCOVERIES = "watcher_discoveries"


def _safe(s: str) -> str:
    """Firestore doc id 用に `/` `:` をエスケープ (relevance/cache.py に倣う)。"""
    return str(s).replace("/", "_").replace(":", "_")


class WatcherRepository:
    """Watcher の Firestore 永続化 (graceful)。"""

    def __init__(self, firestore_client: Any | None = None) -> None:
        self._firestore_client = firestore_client

    def _client(self) -> Any:
        if self._firestore_client is not None:
            return self._firestore_client
        from google.cloud import firestore

        self._firestore_client = firestore.Client()
        return self._firestore_client

    # ------------------------------------------------------------------ watchlist
    def get_watchlist(self, user_id: str) -> WatchInput | None:
        try:
            snap = self._client().collection(FIRESTORE_WATCHLIST).document(_safe(user_id)).get()
            if not getattr(snap, "exists", False):
                return None
            return WatchInput.model_validate(snap.to_dict() or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher_repo.get_watchlist_failed user=%s err=%s", user_id, exc)
            return None

    def save_watchlist(self, watch: WatchInput) -> bool:
        try:
            self._client().collection(FIRESTORE_WATCHLIST).document(_safe(watch.user_id)).set(
                watch.model_dump()
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher_repo.save_watchlist_failed user=%s err=%s", watch.user_id, exc)
            return False

    # ------------------------------------------------------------------ runs
    def save_run(self, run: AgentRunLog) -> bool:
        if not run.run_id:
            logger.warning("watcher_repo.save_run skipped: empty run_id")
            return False
        try:
            payload = run.model_dump()
            payload["created_at"] = datetime.now(UTC)  # latest 判定用 (schema 外の補助列)
            self._client().collection(FIRESTORE_RUNS).document(_safe(run.run_id)).set(payload)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher_repo.save_run_failed run=%s err=%s", run.run_id, exc)
            return False

    def get_run(self, run_id: str) -> AgentRunLog | None:
        """run_id で 1 実行ログを取得 (doc-id lookup、composite index 不要)。"""
        if not run_id:
            return None
        try:
            snap = self._client().collection(FIRESTORE_RUNS).document(_safe(run_id)).get()
            if not getattr(snap, "exists", False):
                return None
            return AgentRunLog.model_validate(snap.to_dict() or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher_repo.get_run_failed run=%s err=%s", run_id, exc)
            return None

    def get_latest_run(self, user_id: str) -> AgentRunLog | None:
        """user の最新実行ログ。最新 discovery の run_id 経由で取得する。

        discoveries は既に user_id+created_at で order_by 済 (list_discoveries の index を
        再利用)。最新 1 件の run_id を引いて get_run するので、runs 用の新規 composite
        index を増やさない。discovery が無ければ None。
        """
        try:
            query = (
                self._client()
                .collection(FIRESTORE_DISCOVERIES)
                .where("user_id", "==", user_id)
                .order_by("created_at", direction="DESCENDING")
                .limit(1)
            )
            run_id = ""
            for doc in query.stream():
                run_id = (doc.to_dict() or {}).get("run_id", "")
                break
            return self.get_run(run_id) if run_id else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher_repo.get_latest_run_failed user=%s err=%s", user_id, exc)
            return None

    # ------------------------------------------------------------------ discoveries
    def save_discoveries(self, user_id: str, run_id: str, discoveries: list[Discovery]) -> int:
        """発見を batch write。成功件数を返す (graceful)。"""
        if not discoveries:
            return 0
        try:
            client = self._client()
            col = client.collection(FIRESTORE_DISCOVERIES)
            batch = client.batch()
            now = datetime.now(UTC)
            for idx, d in enumerate(discoveries):
                doc_id = f"{_safe(user_id)}__{_safe(run_id)}__{idx}"
                payload = d.model_dump()
                payload["user_id"] = user_id
                payload["run_id"] = run_id
                payload["created_at"] = now
                batch.set(col.document(doc_id), payload)
            batch.commit()
            return len(discoveries)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "watcher_repo.save_discoveries_failed user=%s run=%s err=%s", user_id, run_id, exc
            )
            return 0

    def list_discoveries(self, user_id: str, limit: int = 20) -> list[Discovery]:
        """user の発見を新着順 (created_at DESC) で取得。"""
        try:
            query = (
                self._client()
                .collection(FIRESTORE_DISCOVERIES)
                .where("user_id", "==", user_id)
                .order_by("created_at", direction="DESCENDING")
                .limit(limit)
            )
            out: list[Discovery] = []
            for doc in query.stream():
                try:
                    out.append(Discovery.model_validate(doc.to_dict() or {}))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("watcher_repo.discovery_parse_failed err=%s", exc)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher_repo.list_discoveries_failed user=%s err=%s", user_id, exc)
            return []
