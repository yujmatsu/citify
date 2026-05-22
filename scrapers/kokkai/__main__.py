"""国会会議録クライアントの CLI エントリ (subcommand 構造)。

使用例 (プロジェクトルートから):

    # ── fetch: API → stdout (JSON Lines) または BQ 投入
    # 過去 30 日の発言を最大 5 件、JSON Lines で stdout に
    python -m scrapers.kokkai fetch --query "少子化" --max 5

    # 期間指定
    python -m scrapers.kokkai fetch --from 2026-05-01 --until 2026-05-21 --max 10

    # BQ に直接投入
    python -m scrapers.kokkai fetch --query "子育て" --max 100 \\
        --bq-project citify-dev --bq-dataset citify_raw

    # ── publish-from-bq: 既存 BQ kokkai_speeches から Pub/Sub publish
    # 5 件をランダムに publish (4 段パイプラインに流す)
    python -m scrapers.kokkai publish-from-bq \\
        --project-id citify-dev --topic citify-speech-translate --limit 5

    # 「子育て」キーワードで絞ってから publish
    python -m scrapers.kokkai publish-from-bq \\
        --project-id citify-dev --topic citify-speech-translate \\
        --limit 5 --keyword 子育て --order recent

# 後方互換: subcommand 省略時は fetch として実行 (旧 CLI 互換)
    python -m scrapers.kokkai --query "少子化" --max 5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, timedelta

from .client import KokkaiClient


def _build_fetch_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """fetch subcommand の引数定義 (旧 CLI と同一)。"""
    parser.add_argument("--query", "-q", type=str, default=None, help="キーワード絞り込み (any)")
    parser.add_argument("--speaker", type=str, default=None, help="発言者名で絞り込み")
    parser.add_argument("--house", dest="house", type=str, default=None, help="衆議院 / 参議院")
    parser.add_argument(
        "--meeting", dest="meeting", type=str, default=None, help="会議名 (例: 本会議)"
    )
    parser.add_argument(
        "--days", type=int, default=30, help="今日から N 日前まで取得 (--from 未指定時)"
    )
    parser.add_argument(
        "--from", dest="from_date", type=str, default=None, help="開始日 YYYY-MM-DD"
    )
    parser.add_argument(
        "--until", dest="until_date", type=str, default=None, help="終了日 YYYY-MM-DD"
    )
    parser.add_argument(
        "--max", dest="max_total", type=int, default=None, help="最大取得件数 (default: 全件)"
    )
    parser.add_argument("--page-size", type=int, default=30, help="1 ページあたり件数 (1-100)")
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="ページ間待機秒数 (倫理: 最低 1.0 推奨)",
    )
    parser.add_argument(
        "--bq-dataset",
        type=str,
        default=None,
        help="BigQuery dataset_id (例: citify_raw)。指定時のみ BQ モード",
    )
    parser.add_argument(
        "--bq-table",
        type=str,
        default="kokkai_speeches",
        help="BigQuery table_id (default: kokkai_speeches)",
    )
    parser.add_argument(
        "--bq-project",
        type=str,
        default=None,
        help="BigQuery project_id (default: GOOGLE_CLOUD_PROJECT env)",
    )
    parser.add_argument(
        "--bq-batch-size",
        type=int,
        default=100,
        help="streaming insert のバッチサイズ (default: 100)",
    )
    return parser


def _build_publish_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """publish-from-bq subcommand の引数定義。"""
    parser.add_argument("--project-id", required=True, help="GCP project ID")
    parser.add_argument(
        "--topic", default="citify-speech-translate", help="Pub/Sub publish 先 topic"
    )
    parser.add_argument("--limit", type=int, default=50, help="publish 件数上限")
    parser.add_argument("--days", type=int, default=None, help="過去 N 日に絞る (None で全期間)")
    parser.add_argument(
        "--keyword", type=str, default=None, help="speech 本文部分一致 (例: '住居')"
    )
    parser.add_argument(
        "--house", dest="name_of_house", type=str, default=None, help="衆議院 / 参議院"
    )
    parser.add_argument(
        "--meeting", dest="name_of_meeting", type=str, default=None, help="会議名で絞り込み"
    )
    parser.add_argument(
        "--order",
        choices=["rand", "recent", "oldest"],
        default="rand",
        help="ORDER BY (rand / recent / oldest)",
    )
    return parser


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scrapers.kokkai",
        description="国会会議録 API クライアント + Pub/Sub publisher (Citify scrapers/kokkai)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG ログ")

    sub = parser.add_subparsers(dest="cmd")

    p_fetch = sub.add_parser("fetch", help="国会 API → stdout / BQ")
    _build_fetch_parser(p_fetch)

    p_pub = sub.add_parser("publish-from-bq", help="既存 BQ kokkai_speeches → Pub/Sub")
    _build_publish_parser(p_pub)

    # 後方互換: subcommand 省略時用 (= 旧 CLI 引数を root に置く)
    _build_fetch_parser(parser)
    return parser


async def _cmd_fetch(args: argparse.Namespace) -> int:
    from_date = (
        date.fromisoformat(args.from_date)
        if args.from_date
        else date.today() - timedelta(days=args.days)
    )
    until_date = date.fromisoformat(args.until_date) if args.until_date else date.today()

    bq_mode = args.bq_dataset is not None
    loader = None
    if bq_mode:
        from .bq_loader import BigQueryLoader

        project_id = args.bq_project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            print(
                "ERROR: --bq-project または GOOGLE_CLOUD_PROJECT 環境変数を指定してください",
                file=sys.stderr,
            )
            return 2
        loader = BigQueryLoader(
            project_id=project_id,
            dataset_id=args.bq_dataset,
            table_id=args.bq_table,
        )
        print(
            f"# BigQuery mode: project={project_id} "
            f"table={args.bq_dataset}.{args.bq_table} batch_size={args.bq_batch_size}",
            file=sys.stderr,
        )

    count = 0
    records_buffer: list = []
    async with KokkaiClient(rate_limit_sec=args.rate_limit) as client:
        async for record in client.fetch_speeches(
            from_date=from_date,
            until_date=until_date,
            keyword=args.query,
            speaker=args.speaker,
            name_of_house=args.house,
            name_of_meeting=args.meeting,
            page_size=args.page_size,
            max_total=args.max_total,
        ):
            count += 1
            if bq_mode:
                records_buffer.append(record)
            else:
                print(record.model_dump_json(by_alias=True))

    if bq_mode and loader is not None:
        inserted = loader.insert_records(records_buffer, batch_size=args.bq_batch_size)
        print(f"# Inserted {inserted} rows into BigQuery", file=sys.stderr)
    else:
        print(f"# Fetched {count} speeches", file=sys.stderr)
    return 0


def _cmd_publish_from_bq(args: argparse.Namespace) -> int:
    from .publish import fetch_and_publish_kokkai_speeches_from_bq

    msg_ids = fetch_and_publish_kokkai_speeches_from_bq(
        project_id=args.project_id,
        topic=args.topic,
        limit=args.limit,
        days=args.days,
        keyword=args.keyword,
        name_of_house=args.name_of_house,
        name_of_meeting=args.name_of_meeting,
        order=args.order,
    )
    print(f"# Published {len(msg_ids)} kokkai speeches to topic={args.topic}", file=sys.stderr)
    for mid in msg_ids[:5]:
        print(mid)
    if len(msg_ids) > 5:
        print(f"# ... and {len(msg_ids) - 5} more", file=sys.stderr)
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    cmd = getattr(args, "cmd", None)
    if cmd == "publish-from-bq":
        return _cmd_publish_from_bq(args)
    # default / "fetch" / 旧 CLI 互換
    return asyncio.run(_cmd_fetch(args))


if __name__ == "__main__":
    sys.exit(main())
