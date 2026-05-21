"""Citify RAG (Retrieval-Augmented Generation) パッケージ。

Vertex AI RAG Engine を使った議事録セマンティック検索。

主要モジュール:
    - export   : BigQuery → GCS への speech export
    - corpus   : Vertex AI RAG corpus の create / import / query
    - __main__ : CLI (setup-corpus / query)

設計:
    - 1 speech = 1 .txt file (metadata header + speech 本文)
    - 1428 speeches (Phase C) → GCS staging → RAG corpus に import
    - クエリは `retrieval_query(text, top_k=5)` で context list を返す
"""

from .corpus import (
    DEFAULT_LOCATION,
    DEFAULT_TOP_K,
    KOKKAI_CORPUS_DISPLAY_NAME,
    create_corpus,
    delete_corpus,
    get_corpus_by_display_name,
    import_files_from_gcs,
    list_corpora,
    retrieval_query,
)
from .export import (
    DEFAULT_BQ_SOURCE,
    DEFAULT_STAGING_PREFIX,
    SpeechExportRow,
    export_speeches_to_gcs,
    format_speech_for_rag,
)

__all__ = [
    "DEFAULT_BQ_SOURCE",
    "DEFAULT_LOCATION",
    "DEFAULT_STAGING_PREFIX",
    "DEFAULT_TOP_K",
    "KOKKAI_CORPUS_DISPLAY_NAME",
    "SpeechExportRow",
    "create_corpus",
    "delete_corpus",
    "export_speeches_to_gcs",
    "format_speech_for_rag",
    "get_corpus_by_display_name",
    "import_files_from_gcs",
    "list_corpora",
    "retrieval_query",
]
