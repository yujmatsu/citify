"""Firestore `scraper_failures` collection の CRUD レイヤ (Plan F)。

Plan F MVP では既存 scraper コードを改修せず、sample seed (infra/seed/scraper_failures_sample.json)
を直接 fetch_recent() に渡せる loader を提供。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .pii import mask_pii
from .schema import ScraperFailureLog

logger = logging.getLogger(__name__)

FIRESTORE_COLLECTION_SCRAPER_FAILURES = "scraper_failures"

# HTML タグ抽出用 (BeautifulSoup なしで tag-only skeleton)
_TAG_PATTERN = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)[^>]*>")


def compute_html_signature(html: str | None) -> str:
    """HTML タグ構造のみ抽出 → sha256[:16]。

    同じ DOM 構造の失敗を集約するための重複排除キー。
    """
    if not html:
        return ""
    # タグだけ抽出 (属性は除去)
    tags = [f"<{slash}{name}>" for slash, name in _TAG_PATTERN.findall(html)]
    skeleton = "".join(tags)
    return hashlib.sha256(skeleton.encode("utf-8")).hexdigest()[:16]


class FailureLogRepository:
    """Firestore CRUD + sample seed loader。"""

    def __init__(self, firestore_client: Any | None = None) -> None:
        self._client = firestore_client

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        from google.cloud import firestore

        self._client = firestore.Client()
        return self._client

    def save_failure(self, failure: ScraperFailureLog) -> str:
        """1 失敗を Firestore に保存。html_snippet / stack_trace は PII マスク済を渡す前提。

        Returns:
            failure_id (Firestore doc_id)
        """
        # Defensive: PII マスクを再適用 (二重防御)
        safe_html = mask_pii(failure.html_snippet)
        safe_stack = mask_pii(failure.stack_trace)
        signature = compute_html_signature(safe_html)

        record = failure.model_copy(
            update={
                "html_snippet": safe_html or None,
                "stack_trace": safe_stack,
                "html_signature": signature or failure.html_signature,
            }
        )

        try:
            doc = (
                self._ensure_client()
                .collection(FIRESTORE_COLLECTION_SCRAPER_FAILURES)
                .document(record.failure_id)
            )
            doc.set(record.model_dump(mode="json"))
            logger.info(
                "scraper_failure.saved id=%s scraper=%s signature=%s",
                record.failure_id,
                record.scraper,
                record.html_signature,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("scraper_failure.save_failed err=%s", exc)

        return record.failure_id

    def fetch_recent(
        self,
        days: int = 7,
        limit: int = 50,
    ) -> list[ScraperFailureLog]:
        """過去 N 日の失敗を Firestore から取得 (timestamp 降順、limit 件)。"""
        from datetime import timedelta

        since = datetime.utcnow() - timedelta(days=days)

        try:
            query = (
                self._ensure_client()
                .collection(FIRESTORE_COLLECTION_SCRAPER_FAILURES)
                .where("timestamp", ">=", since)
                .order_by("timestamp", direction="DESCENDING")
                .limit(limit)
            )
            docs = list(query.stream())
        except Exception as exc:  # noqa: BLE001
            logger.warning("scraper_failure.fetch_failed err=%s", exc)
            return []

        results: list[ScraperFailureLog] = []
        for doc in docs:
            data = doc.to_dict() or {}
            try:
                results.append(ScraperFailureLog.model_validate(data))
            except Exception as exc:  # noqa: BLE001
                logger.warning("scraper_failure.parse_failed doc=%s err=%s", doc.id, exc)
        return results

    def load_sample_seed(self, path: Path | None = None) -> list[ScraperFailureLog]:
        """`infra/seed/scraper_failures_sample.json` から sample data を読み込む (demo 用)。"""
        if path is None:
            # repo root を推測
            path = (
                Path(__file__).resolve().parents[2]
                / "infra"
                / "seed"
                / "scraper_failures_sample.json"
            )
        if not path.exists():
            logger.warning("scraper_failure.seed_not_found path=%s", path)
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("scraper_failure.seed_parse_failed err=%s", exc)
            return []

        results: list[ScraperFailureLog] = []
        for item in data if isinstance(data, list) else []:
            try:
                # PII マスクと signature 計算を適用
                if "html_snippet" in item:
                    item["html_snippet"] = mask_pii(item["html_snippet"])
                if "stack_trace" in item:
                    item["stack_trace"] = mask_pii(item["stack_trace"])
                if "html_signature" not in item:
                    item["html_signature"] = compute_html_signature(item.get("html_snippet"))
                results.append(ScraperFailureLog.model_validate(item))
            except Exception as exc:  # noqa: BLE001
                logger.warning("scraper_failure.seed_item_invalid err=%s", exc)
        return results


def dedupe_by_pattern(failures: list[ScraperFailureLog]) -> list[ScraperFailureLog]:
    """重複排除: (scraper + error_type + html_signature) で 1 件残す (最新優先)。"""
    seen: dict[tuple[str, str, str], ScraperFailureLog] = {}
    # timestamp 降順 (新しい順) で見て、未登録キーのものだけ採用
    for f in sorted(failures, key=lambda x: x.timestamp, reverse=True):
        key = (f.scraper, f.error_type, f.html_signature)
        if key not in seen:
            seen[key] = f
    return list(seen.values())
