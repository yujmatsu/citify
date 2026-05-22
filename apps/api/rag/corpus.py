"""Vertex AI RAG Engine の corpus 管理 + クエリ。

vertexai.rag SDK の薄いラッパー。
    - create_corpus()           : 新規 corpus 作成
    - import_files_from_gcs()   : GCS 経由で file を import (非同期、polling)
    - retrieval_query()         : セマンティック検索
    - list_corpora()            : 既存 corpus 列挙
    - get_corpus_by_display_name(): 名前で取得 (idempotent setup 用)
    - delete_corpus()           : テスト用 / cleanup 用

Embedding model:
    text-multilingual-embedding-002 (日本語対応、Vertex AI native)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

KOKKAI_CORPUS_DISPLAY_NAME = "citify-kokkai-speeches"
DEFAULT_LOCATION = "us-central1"  # RAG Engine の最も安定したリージョン
DEFAULT_EMBEDDING_MODEL = "publishers/google/models/text-multilingual-embedding-002"
DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 100
DEFAULT_TOP_K = 5
DEFAULT_IMPORT_TIMEOUT_SEC = 1800  # 30 min (1500 files の import に十分)
IMPORT_POLL_INTERVAL_SEC = 15


@dataclass(frozen=True)
class RetrievedContext:
    """RAG クエリ結果の 1 件 (semantic search で hit した text chunk)。"""

    text: str
    source_uri: str  # gs://.../speech_id.txt
    distance: float | None = None  # 0 = 完全一致、1 = 無関連 (cosine)


def _init_vertexai(project_id: str, location: str) -> None:
    """vertexai.init() を遅延 import で呼ぶ (テスト時は呼ばれない)。"""
    import vertexai

    vertexai.init(project=project_id, location=location)


def _rag_module() -> Any:
    """vertexai.rag モジュールを返す (遅延 import + テストで mock しやすく)。"""
    from vertexai import rag

    return rag


def create_corpus(
    project_id: str,
    location: str = DEFAULT_LOCATION,
    display_name: str = KOKKAI_CORPUS_DISPLAY_NAME,
    description: str = "国会会議録 検索 API から取得した speech の RAG corpus",
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    use_serverless: bool = True,
    rag_module: Any | None = None,
) -> Any:
    """新規 RAG corpus を作成。

    Args:
        use_serverless: True (default) で Serverless mode、False で Spanner mode (legacy)。
            2026 以降の新規 project では Spanner mode が allowlist 必要のため、
            Serverless mode 推奨。
    """
    if rag_module is None:
        _init_vertexai(project_id, location)
        rag_module = _rag_module()

    if use_serverless:
        # Serverless mode: backend_config を省略 (us-central1 で Serverless がデフォルト)
        # https://cloud.google.com/vertex-ai/generative-ai/docs/rag-engine/switching-modes
        corpus = rag_module.create_corpus(
            display_name=display_name,
            description=description,
        )
        logger.info(
            "rag.corpus.created (serverless) name=%s display_name=%s",
            corpus.name,
            corpus.display_name,
        )
        return corpus

    # Spanner mode (legacy)
    embedding_model_config = rag_module.RagEmbeddingModelConfig(
        vertex_prediction_endpoint=rag_module.VertexPredictionEndpoint(
            publisher_model=embedding_model,
        ),
    )
    backend_config = rag_module.RagVectorDbConfig(
        rag_embedding_model_config=embedding_model_config,
    )
    corpus = rag_module.create_corpus(
        display_name=display_name,
        description=description,
        backend_config=backend_config,
    )
    logger.info(
        "rag.corpus.created (spanner) name=%s display_name=%s embedding=%s",
        corpus.name,
        corpus.display_name,
        embedding_model,
    )
    return corpus


def list_corpora(
    project_id: str,
    location: str = DEFAULT_LOCATION,
    rag_module: Any | None = None,
) -> list[Any]:
    """既存 RAG corpus 一覧を返す。"""
    if rag_module is None:
        _init_vertexai(project_id, location)
        rag_module = _rag_module()
    return list(rag_module.list_corpora())


def get_corpus_by_display_name(
    project_id: str,
    display_name: str = KOKKAI_CORPUS_DISPLAY_NAME,
    location: str = DEFAULT_LOCATION,
    rag_module: Any | None = None,
) -> Any | None:
    """display_name から corpus を取得。なければ None。"""
    for corpus in list_corpora(project_id, location, rag_module=rag_module):
        if corpus.display_name == display_name:
            return corpus
    return None


def import_files_from_gcs(
    corpus_name: str,
    gcs_paths: list[str],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    project_id: str | None = None,
    location: str = DEFAULT_LOCATION,
    wait: bool = True,
    timeout_sec: int = DEFAULT_IMPORT_TIMEOUT_SEC,
    rag_module: Any | None = None,
) -> Any:
    """GCS path から corpus に file を import (非同期 → 完了 polling)。

    Args:
        corpus_name: corpus の resource name (例: projects/.../ragCorpora/123)
        gcs_paths: import 元 GCS path (folder 指定で配下全 file)
        chunk_size: text chunking のサイズ (token 単位、推奨 256-1024)
        chunk_overlap: chunk 間の overlap (chunk_size の 10-20%)
        wait: True で完了まで polling、False で job を即 return
        timeout_sec: wait=True 時の最大待機秒数

    Returns:
        import operation object
    """
    if rag_module is None:
        if project_id is not None:
            _init_vertexai(project_id, location)
        rag_module = _rag_module()

    transformation_config = rag_module.TransformationConfig(
        chunking_config=rag_module.ChunkingConfig(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        ),
    )

    logger.info(
        "rag.import.start corpus=%s paths=%s chunk_size=%d overlap=%d",
        corpus_name,
        gcs_paths,
        chunk_size,
        chunk_overlap,
    )
    response = rag_module.import_files(
        corpus_name=corpus_name,
        paths=gcs_paths,
        transformation_config=transformation_config,
    )

    if not wait:
        return response

    return _wait_for_import(response, timeout_sec=timeout_sec)


def _wait_for_import(operation: Any, timeout_sec: int) -> Any:
    """import operation 完了を polling。result() で同期待機できるものはそれを使う。"""
    # vertexai.rag の import_files は同期 (ImportRagFilesResponse) を返す版と
    # operation を返す版があり、SDK バージョン依存。両対応:
    if hasattr(operation, "result"):
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if hasattr(operation, "done") and not operation.done():
                time.sleep(IMPORT_POLL_INTERVAL_SEC)
                continue
            result = operation.result(timeout=10)
            logger.info("rag.import.done result=%s", result)
            return result
        raise TimeoutError(f"RAG import exceeded {timeout_sec}s timeout")

    # 同期戻り値の場合 (新 SDK で見られる)
    imported = getattr(operation, "imported_rag_files_count", None)
    failed = getattr(operation, "failed_rag_files_count", None)
    logger.info("rag.import.done imported=%s failed=%s", imported, failed)
    return operation


def retrieval_query(
    corpus_name: str,
    text: str,
    top_k: int = DEFAULT_TOP_K,
    project_id: str | None = None,
    location: str = DEFAULT_LOCATION,
    rag_module: Any | None = None,
) -> list[RetrievedContext]:
    """セマンティック検索: text に近い chunk を top_k 件返す。"""
    if rag_module is None:
        if project_id is not None:
            _init_vertexai(project_id, location)
        rag_module = _rag_module()

    response = rag_module.retrieval_query(
        rag_resources=[rag_module.RagResource(rag_corpus=corpus_name)],
        text=text,
        rag_retrieval_config=rag_module.RagRetrievalConfig(
            top_k=top_k,
        ),
    )

    results: list[RetrievedContext] = []
    contexts = getattr(response, "contexts", None) or getattr(
        getattr(response, "contexts", None), "contexts", []
    )
    if contexts is None:
        contexts = []
    if hasattr(contexts, "contexts"):
        contexts = contexts.contexts

    for ctx in contexts:
        results.append(
            RetrievedContext(
                text=getattr(ctx, "text", "") or "",
                source_uri=getattr(ctx, "source_uri", "") or "",
                distance=getattr(ctx, "distance", None),
            )
        )

    logger.info(
        "rag.query corpus=%s text=%r top_k=%d returned=%d",
        corpus_name,
        text[:50],
        top_k,
        len(results),
    )
    return results


def delete_corpus(
    corpus_name: str,
    project_id: str | None = None,
    location: str = DEFAULT_LOCATION,
    rag_module: Any | None = None,
) -> None:
    """corpus を削除 (cleanup / test 用)。"""
    if rag_module is None:
        if project_id is not None:
            _init_vertexai(project_id, location)
        rag_module = _rag_module()
    rag_module.delete_corpus(name=corpus_name)
    logger.info("rag.corpus.deleted name=%s", corpus_name)
