"""WatcherRepository: マイ街エージェントの Firestore 永続化層 (TASK-WATCHER Slice 3.5)。

3 コレクション:
    - user_watchlist     (doc id = user_id)            : ウォッチ街リスト
    - watcher_agent_runs (doc id = run_id)             : 自律実行ログ (tool_calls 等)
    - watcher_analyses   (doc id = {user_id}__{run_id}) : 街選び分析 (verdict + 街評価)

設計: relevance/cache.py と同じ graceful パターン。全 method は Firestore 障害時も
例外を投げず None / [] / False / 0 を返す (エージェント実行は永続化と無関係に継続)。
lazy client init、テストは firestore_client mock 注入。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .schema import AgentRunLog, TownAnalysis, WatchInput

logger = logging.getLogger(__name__)

FIRESTORE_WATCHLIST = "user_watchlist"
FIRESTORE_RUNS = "watcher_agent_runs"
FIRESTORE_ANALYSES = "watcher_analyses"


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
        """user の最新実行ログ。最新 analysis の run_id 経由で取得する。

        analyses は user_id+created_at で order_by 済 (get_latest_analysis と同 index を
        再利用)。最新 1 件の run_id を引いて get_run するので、runs 用の新規 composite
        index を増やさない。analysis が無ければ None。
        """
        try:
            run_id = self._latest_analysis_run_id(user_id)
            return self.get_run(run_id) if run_id else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher_repo.get_latest_run_failed user=%s err=%s", user_id, exc)
            return None

    # ------------------------------------------------------------------ analyses
    def save_analysis(self, user_id: str, run_id: str, analysis: TownAnalysis) -> bool:
        """街選び分析を 1 件保存 (doc id = {user}__{run})。成功可否を返す (graceful)。"""
        try:
            doc_id = f"{_safe(user_id)}__{_safe(run_id)}"
            payload = analysis.model_dump()
            payload["user_id"] = user_id
            payload["run_id"] = run_id
            payload["created_at"] = datetime.now(UTC)
            self._client().collection(FIRESTORE_ANALYSES).document(doc_id).set(payload)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "watcher_repo.save_analysis_failed user=%s run=%s err=%s", user_id, run_id, exc
            )
            return False

    def _latest_analysis_doc(self, user_id: str) -> dict | None:
        """user の最新 analysis ドキュメント (raw dict)。無ければ None。"""
        query = (
            self._client()
            .collection(FIRESTORE_ANALYSES)
            .where("user_id", "==", user_id)
            .order_by("created_at", direction="DESCENDING")
            .limit(1)
        )
        for doc in query.stream():
            return doc.to_dict() or {}
        return None

    def _latest_analysis_run_id(self, user_id: str) -> str:
        doc = self._latest_analysis_doc(user_id)
        return (doc or {}).get("run_id", "") if doc else ""

    def get_latest_analysis(self, user_id: str) -> TownAnalysis | None:
        """user の最新の街選び分析を取得 (created_at DESC)。無ければ None。"""
        try:
            doc = self._latest_analysis_doc(user_id)
            if not doc:
                return None
            return TownAnalysis.model_validate(doc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher_repo.get_latest_analysis_failed user=%s err=%s", user_id, exc)
            return None
