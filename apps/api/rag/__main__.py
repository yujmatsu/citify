"""Citify RAG CLI: setup-corpus / query サブコマンド。

使用例 (プロジェクトルートから、apps/api/.venv activate 済):

    # corpus 作成 + BQ → GCS export + import の一気通貫
    python -m apps.api.rag setup \\
        --project citify-dev --bucket citify-dev-rag-staging

    # 既存 corpus を流用 + 追加 import のみ (export 済み前提)
    python -m apps.api.rag import-only \\
        --project citify-dev --bucket citify-dev-rag-staging

    # クエリ
    python -m apps.api.rag query \\
        --project citify-dev --text "子育て支援について" --top-k 5

    # corpus 一覧
    python -m apps.api.rag list --project citify-dev

    # corpus 削除 (cleanup)
    python -m apps.api.rag delete --project citify-dev \\
        --corpus projects/.../ragCorpora/123
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

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
from .export import DEFAULT_BQ_SOURCE, DEFAULT_STAGING_PREFIX, export_speeches_to_gcs

logger = logging.getLogger(__name__)


def _build_parser() -> argparse.ArgumentParser:
    # 全 subcommand に共通する引数 (--project / --location / -v) を parent parser に
    # 集約。これにより subcommand の前後どちらでも引数指定が許される。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--project", required=True, help="GCP project ID")
    common.add_argument("--location", default=DEFAULT_LOCATION, help="Vertex AI location")
    common.add_argument("-v", "--verbose", action="store_true", help="DEBUG ログ")

    parser = argparse.ArgumentParser(
        prog="python -m apps.api.rag",
        description="Citify RAG (Vertex AI RAG Engine) CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # setup: export + create + import 一気通貫
    p_setup = sub.add_parser(
        "setup",
        parents=[common],
        help="BQ → GCS export → corpus 作成 → import の一気通貫",
    )
    p_setup.add_argument("--bucket", required=True, help="GCS staging bucket 名")
    p_setup.add_argument("--bq-source", default=DEFAULT_BQ_SOURCE)
    p_setup.add_argument("--prefix", default=DEFAULT_STAGING_PREFIX)
    p_setup.add_argument("--display-name", default=KOKKAI_CORPUS_DISPLAY_NAME)
    p_setup.add_argument("--limit", type=int, default=None, help="export 件数上限 (test 用)")
    p_setup.add_argument(
        "--skip-export", action="store_true", help="GCS export スキップ (既に export 済の場合)"
    )

    # import-only: 既存 GCS から既存 corpus に追加 import
    p_imp = sub.add_parser(
        "import-only", parents=[common], help="既存 corpus に GCS から追加 import のみ"
    )
    p_imp.add_argument("--bucket", required=True)
    p_imp.add_argument("--prefix", default=DEFAULT_STAGING_PREFIX)
    p_imp.add_argument("--display-name", default=KOKKAI_CORPUS_DISPLAY_NAME)

    # query: セマンティック検索
    p_q = sub.add_parser("query", parents=[common], help="corpus にセマンティック検索")
    p_q.add_argument("--text", required=True, help="検索クエリ文")
    p_q.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    p_q.add_argument("--display-name", default=KOKKAI_CORPUS_DISPLAY_NAME)

    # list: 既存 corpus 一覧
    sub.add_parser("list", parents=[common], help="既存 RAG corpus を列挙")

    # delete: corpus 削除
    p_del = sub.add_parser("delete", parents=[common], help="corpus 削除")
    p_del.add_argument("--corpus", required=True, help="corpus resource name")

    return parser


def _cmd_setup(args: argparse.Namespace) -> int:
    # 1. corpus 作成 (or 既存取得)
    corpus = get_corpus_by_display_name(args.project, args.display_name, args.location)
    if corpus is None:
        print(f"# Creating corpus: {args.display_name}", file=sys.stderr)
        corpus = create_corpus(
            project_id=args.project,
            location=args.location,
            display_name=args.display_name,
        )
        print(f"# Corpus created: {corpus.name}", file=sys.stderr)
    else:
        print(f"# Reusing existing corpus: {corpus.name}", file=sys.stderr)

    # 2. BQ → GCS export
    if not args.skip_export:
        print(f"# Exporting speeches from BQ to gs://{args.bucket}/{args.prefix}/", file=sys.stderr)
        uploaded = export_speeches_to_gcs(
            bucket_name=args.bucket,
            bq_source=args.bq_source,
            prefix=args.prefix,
            limit=args.limit,
            project_id=args.project,
        )
        print(f"# Uploaded {uploaded} speeches to GCS", file=sys.stderr)
    else:
        print("# Skipping BQ → GCS export (--skip-export)", file=sys.stderr)

    # 3. GCS → corpus import
    gcs_path = f"gs://{args.bucket}/{args.prefix}/"
    print(f"# Importing files from {gcs_path} (this may take 5-30 min)...", file=sys.stderr)
    result = import_files_from_gcs(
        corpus_name=corpus.name,
        gcs_paths=[gcs_path],
        project_id=args.project,
        location=args.location,
        wait=True,
    )
    print(f"# Import done: {result}", file=sys.stderr)
    return 0


def _cmd_import_only(args: argparse.Namespace) -> int:
    corpus = get_corpus_by_display_name(args.project, args.display_name, args.location)
    if corpus is None:
        print(f"ERROR: corpus '{args.display_name}' not found", file=sys.stderr)
        return 2
    gcs_path = f"gs://{args.bucket}/{args.prefix}/"
    print(f"# Importing from {gcs_path}", file=sys.stderr)
    result = import_files_from_gcs(
        corpus_name=corpus.name,
        gcs_paths=[gcs_path],
        project_id=args.project,
        location=args.location,
        wait=True,
    )
    print(f"# Import done: {result}", file=sys.stderr)
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    corpus = get_corpus_by_display_name(args.project, args.display_name, args.location)
    if corpus is None:
        print(f"ERROR: corpus '{args.display_name}' not found", file=sys.stderr)
        return 2

    results = retrieval_query(
        corpus_name=corpus.name,
        text=args.text,
        top_k=args.top_k,
        project_id=args.project,
        location=args.location,
    )
    print(f"# Query: {args.text!r} → {len(results)} hits", file=sys.stderr)
    for i, ctx in enumerate(results, 1):
        preview = ctx.text[:200].replace("\n", " ")
        dist = f"{ctx.distance:.4f}" if ctx.distance is not None else "n/a"
        print(f"\n=== Hit {i} (distance={dist}) ===")
        print(f"Source: {ctx.source_uri}")
        print(f"Preview: {preview}…")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    corpora = list_corpora(args.project, args.location)
    print(f"# {len(corpora)} corpora found in {args.project}/{args.location}", file=sys.stderr)
    for c in corpora:
        print(f"{c.name}\t{c.display_name}")
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    delete_corpus(args.corpus, project_id=args.project, location=args.location)
    print(f"# Deleted: {args.corpus}", file=sys.stderr)
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    handlers: dict[str, Any] = {
        "setup": _cmd_setup,
        "import-only": _cmd_import_only,
        "query": _cmd_query,
        "list": _cmd_list,
        "delete": _cmd_delete,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
