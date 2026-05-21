"""press_rss スクレイパー CLI。

使用例:
    # 単一 RSS feed を取得
    python -m scrapers.press_rss fetch \\
        --rss-url "https://www.metro.tokyo.lg.jp/tosei/hodohappyo/rss.xml" \\
        --municipality-code 13000 \\
        --max 5

    # 複数自治体を順次 (將来 municipality_master.csv 連携で自動化予定)
    python -m scrapers.press_rss fetch \\
        --rss-url "https://www.city.minato.tokyo.jp/rss.xml" \\
        --municipality-code 13103 \\
        --max 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .client import PressRssClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scrapers.press_rss",
        description="Citify 自治体プレス RSS スクレイパー (B-7)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="RSS feed を 1 件取得")
    p_fetch.add_argument("--rss-url", required=True, help="RSS feed URL")
    p_fetch.add_argument(
        "--municipality-code", required=True, help="自治体コード 5 桁 (13000 = 東京都 等)"
    )
    p_fetch.add_argument("--max", type=int, default=None, help="取得上限件数")
    p_fetch.add_argument("--rate-limit-sec", type=float, default=1.0)
    p_fetch.add_argument("--timeout-sec", type=float, default=30.0)
    p_fetch.add_argument("-v", "--verbose", action="store_true")
    return parser


async def _cmd_fetch(args: argparse.Namespace) -> int:
    async with PressRssClient(
        timeout_sec=args.timeout_sec, rate_limit_sec=args.rate_limit_sec
    ) as c:
        items = await c.fetch_feed(
            rss_url=args.rss_url,
            municipality_code=args.municipality_code,
            max_items=args.max,
        )

    print(f"# Got {len(items)} items from {args.rss_url}", file=sys.stderr)
    for item in items:
        data = item.model_dump(mode="json")
        # description の HTML 含む長文は 150 字で切る
        if data.get("description") and len(data["description"]) > 150:
            data["description"] = data["description"][:150] + "…"
        print(json.dumps(data, ensure_ascii=False))
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    if args.cmd == "fetch":
        return asyncio.run(_cmd_fetch(args))
    return 2


if __name__ == "__main__":
    sys.exit(main())
