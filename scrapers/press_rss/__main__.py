"""press_rss スクレイパー CLI (B-7)。

使用例:
    # 単一 RSS feed を取得 (stdout に JSON 出力、publish なし)
    python -m scrapers.press_rss fetch \\
        --rss-url "https://www.metro.tokyo.lg.jp/.../rss.xml" \\
        --municipality-code 13000 \\
        --max 5

    # 単一 RSS feed を Pub/Sub に publish (translator → relevance → bq_sink で BQ 到達)
    python -m scrapers.press_rss publish-from-rss \\
        --project-id citify-dev \\
        --rss-url "https://www.metro.tokyo.lg.jp/.../rss.xml" \\
        --municipality-code 13000 \\
        --max 3

    # tier1_supplements.csv の press_rss_url 全部を順次 publish
    python -m scrapers.press_rss publish-all \\
        --project-id citify-dev \\
        --csv infra/seed/tier1_supplements.csv \\
        --max-per-feed 3
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys

from .client import PressRssClient
from .publish import fetch_and_publish_rss, publish_all_prefectures

DEFAULT_TOPIC = "citify-speech-translate"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scrapers.press_rss",
        description="Citify 自治体プレス RSS スクレイパー (B-7)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # --- fetch (publish なし) ---
    p_fetch = sub.add_parser("fetch", help="RSS feed を 1 件取得し JSON を stdout に出力")
    p_fetch.add_argument("--rss-url", required=True, help="RSS feed URL")
    p_fetch.add_argument(
        "--municipality-code", required=True, help="自治体コード 5 桁 (13000 = 東京都 等)"
    )
    p_fetch.add_argument("--max", type=int, default=None, help="取得上限件数")
    p_fetch.add_argument("--rate-limit-sec", type=float, default=1.0)
    p_fetch.add_argument("--timeout-sec", type=float, default=30.0)

    # --- publish-from-rss (単一 RSS を Pub/Sub に流す) ---
    p_pub = sub.add_parser("publish-from-rss", help="単一 RSS を Pub/Sub にプロデュース")
    p_pub.add_argument("--project-id", required=True, help="GCP project ID")
    p_pub.add_argument("--topic", default=DEFAULT_TOPIC, help="Pub/Sub topic 名")
    p_pub.add_argument("--rss-url", required=True)
    p_pub.add_argument("--municipality-code", required=True)
    p_pub.add_argument("--max", type=int, default=3, help="取得上限件数 (default 3)")
    p_pub.add_argument("--rate-limit-sec", type=float, default=1.0)
    p_pub.add_argument("--timeout-sec", type=float, default=30.0)

    # --- publish-all (CSV から 47 都道府県分を順次 publish) ---
    p_all = sub.add_parser("publish-all", help="CSV の press_rss_url を全部順次 publish")
    p_all.add_argument("--project-id", required=True)
    p_all.add_argument("--topic", default=DEFAULT_TOPIC)
    p_all.add_argument(
        "--csv",
        default="infra/seed/tier1_supplements.csv",
        help="municipality_code,...,press_rss_url を含む CSV パス",
    )
    p_all.add_argument("--max-per-feed", type=int, default=3, help="各 RSS から取得する最大件数")
    p_all.add_argument(
        "--limit-feeds",
        type=int,
        default=None,
        help="先頭 N feed のみ処理 (デバッグ用)",
    )
    p_all.add_argument("--rate-limit-sec", type=float, default=1.0)
    p_all.add_argument("--timeout-sec", type=float, default=30.0)

    for p in (parser, p_fetch, p_pub, p_all):
        p.add_argument("-v", "--verbose", action="store_true")
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
        if data.get("description") and len(data["description"]) > 150:
            data["description"] = data["description"][:150] + "…"
        print(json.dumps(data, ensure_ascii=False))
    return 0


async def _cmd_publish_from_rss(args: argparse.Namespace) -> int:
    msg_ids = await fetch_and_publish_rss(
        project_id=args.project_id,
        topic=args.topic,
        rss_url=args.rss_url,
        municipality_code=args.municipality_code,
        max_items=args.max,
        rate_limit_sec=args.rate_limit_sec,
        timeout_sec=args.timeout_sec,
    )
    print(
        f"# Published {len(msg_ids)} items to {args.topic} (muni={args.municipality_code})",
        file=sys.stderr,
    )
    for mid in msg_ids:
        print(mid)
    return 0


def _read_press_feeds_from_csv(csv_path: str) -> list[tuple[str, str]]:
    """CSV から (municipality_code, press_rss_url) のリストを抽出。

    press_rss_url が空の行は skip。
    """
    feeds: list[tuple[str, str]] = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            muni = (row.get("municipality_code") or "").strip()
            rss = (row.get("press_rss_url") or "").strip()
            if not muni or not rss:
                continue
            feeds.append((muni, rss))
    return feeds


async def _cmd_publish_all(args: argparse.Namespace) -> int:
    feeds = _read_press_feeds_from_csv(args.csv)
    if args.limit_feeds is not None:
        feeds = feeds[: args.limit_feeds]

    print(
        f"# Loaded {len(feeds)} feeds from {args.csv} (max-per-feed={args.max_per_feed})",
        file=sys.stderr,
    )
    results = await publish_all_prefectures(
        project_id=args.project_id,
        topic=args.topic,
        prefecture_feeds=feeds,
        max_items_per_feed=args.max_per_feed,
        rate_limit_sec=args.rate_limit_sec,
        timeout_sec=args.timeout_sec,
    )

    ok = sum(1 for n in results.values() if n > 0)
    failed = sum(1 for n in results.values() if n == -1)
    empty = len(results) - ok - failed
    total_msgs = sum(n for n in results.values() if n > 0)

    print(
        f"# Summary: feeds={len(results)} ok={ok} failed={failed} empty={empty} "
        f"total_msgs_published={total_msgs}",
        file=sys.stderr,
    )
    for muni, n in sorted(results.items()):
        status = "OK" if n > 0 else ("FAIL" if n == -1 else "EMPTY")
        print(f"{muni}\t{status}\t{n}")
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
    if args.cmd == "publish-from-rss":
        return asyncio.run(_cmd_publish_from_rss(args))
    if args.cmd == "publish-all":
        return asyncio.run(_cmd_publish_all(args))
    return 2


if __name__ == "__main__":
    sys.exit(main())
