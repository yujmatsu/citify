"""国会会議録クライアントの CLI エントリ。

使用例 (プロジェクトルートから):
    # 過去 30 日の発言を最大 5 件、JSON Lines で stdout に
    python -m scrapers.kokkai --query "少子化" --max 5

    # 期間指定
    python -m scrapers.kokkai --from 2026-05-01 --until 2026-05-21 --max 10

    # 院・会議絞り込み
    python -m scrapers.kokkai --house 衆議院 --meeting 予算委員会 --max 20

    # ファイル出力
    python -m scrapers.kokkai --query 子育て --max 100 > /tmp/kokkai_sample.jsonl
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date, timedelta

from .client import KokkaiClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scrapers.kokkai",
        description="国会会議録 API クライアント (Citify scrapers/kokkai)",
    )
    parser.add_argument("--query", "-q", type=str, default=None, help="キーワード絞り込み (any)")
    parser.add_argument("--speaker", type=str, default=None, help="発言者名で絞り込み")
    parser.add_argument(
        "--house", dest="house", type=str, default=None, help="衆議院 / 参議院"
    )
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
    parser.add_argument(
        "--page-size", type=int, default=30, help="1 ページあたり件数 (1-100)"
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=1.0,
        help="ページ間待機秒数 (倫理: 最低 1.0 推奨)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="DEBUG ログ")
    return parser


async def _run(args: argparse.Namespace) -> int:
    from_date = (
        date.fromisoformat(args.from_date)
        if args.from_date
        else date.today() - timedelta(days=args.days)
    )
    until_date = (
        date.fromisoformat(args.until_date) if args.until_date else date.today()
    )

    count = 0
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
            # 1 行 1 record の JSON Lines (BigQuery 投入時にそのまま使える形式)
            print(record.model_dump_json(by_alias=True))
            count += 1

    print(f"# Fetched {count} speeches", file=sys.stderr)
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
