"""DiscussNet スクレイパー CLI: inspect / list-meetings / fetch-speeches。

使用例:
    # 1. まず DOM 構造を確認 (どのセレクタが動くか)
    python -m scrapers.kaigiroku_net inspect --tenant arakawa

    # 2. 会議一覧取得
    python -m scrapers.kaigiroku_net list --tenant arakawa --max 10

    # 3. 1 会議の発言取得
    python -m scrapers.kaigiroku_net fetch \\
        --tenant arakawa \\
        --url "https://ssp.kaigiroku.net/tenant/arakawa/SpMinuteView.html?..."

    # 白ラベル型 (横浜) は --base-url で指定
    python -m scrapers.kaigiroku_net list \\
        --tenant yokohama \\
        --base-url "http://giji.city.yokohama.lg.jp/tenant/yokohama/" --max 5

    # 目視デバッグ (headless OFF)
    python -m scrapers.kaigiroku_net inspect --tenant arakawa --no-headless
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .client import KaigirokuNetClient


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--tenant", required=True, help="テナント ID (例: arakawa)")
    common.add_argument("--base-url", default=None, help="白ラベル型の上書き URL (None で中央型)")
    common.add_argument("--no-headless", action="store_true", help="目視デバッグ用")
    common.add_argument("--timeout-ms", type=int, default=30_000, help="ページ遷移 + セレクタ待機")
    common.add_argument("-v", "--verbose", action="store_true")

    parser = argparse.ArgumentParser(
        prog="python -m scrapers.kaigiroku_net",
        description="DiscussNet (kaigiroku.net) スクレイパー (A-4)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inspect = sub.add_parser("inspect", parents=[common], help="DOM ダンプ (セレクタ決定用)")
    p_inspect.add_argument("--path", default="MinuteBrowse.html", help="ベース URL からの相対 path")

    p_list = sub.add_parser("list", parents=[common], help="会議一覧取得")
    p_list.add_argument("--path", default="MinuteBrowse.html")
    p_list.add_argument("--max", type=int, default=20)

    p_fetch = sub.add_parser("fetch", parents=[common], help="1 議事録の発言取得")
    p_fetch.add_argument("--url", required=True, help="議事録詳細 URL")
    p_fetch.add_argument("--max-speeches", type=int, default=100)

    return parser


async def _cmd_inspect(args: argparse.Namespace) -> int:
    async with KaigirokuNetClient(
        tenant_id=args.tenant,
        base_url=args.base_url,
        headless=not args.no_headless,
        timeout_ms=args.timeout_ms,
    ) as client:
        result = await client.inspect_page(path=args.path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def _cmd_list(args: argparse.Namespace) -> int:
    async with KaigirokuNetClient(
        tenant_id=args.tenant,
        base_url=args.base_url,
        headless=not args.no_headless,
        timeout_ms=args.timeout_ms,
    ) as client:
        meetings = await client.list_meetings(path=args.path, max_items=args.max)
    print(f"# Got {len(meetings)} meetings from tenant={args.tenant}", file=sys.stderr)
    for m in meetings:
        print(m.model_dump_json())
    return 0


async def _cmd_fetch(args: argparse.Namespace) -> int:
    async with KaigirokuNetClient(
        tenant_id=args.tenant,
        base_url=args.base_url,
        headless=not args.no_headless,
        timeout_ms=args.timeout_ms,
    ) as client:
        speeches = await client.fetch_speeches(args.url, max_speeches=args.max_speeches)
    print(f"# Got {len(speeches)} speeches", file=sys.stderr)
    for s in speeches[:3]:  # サンプル 3 件のみ stdout
        data = s.model_dump()
        # speech 本文は最初 100 字に切る (見やすさ重視)
        data["content_text"] = data["content_text"][:100] + (
            "…" if len(s.content_text) > 100 else ""
        )
        print(json.dumps(data, ensure_ascii=False))
    if len(speeches) > 3:
        print(f"# ... and {len(speeches) - 3} more (use --verbose for all)", file=sys.stderr)
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    handlers = {
        "inspect": _cmd_inspect,
        "list": _cmd_list,
        "fetch": _cmd_fetch,
    }
    return asyncio.run(handlers[args.cmd](args))


if __name__ == "__main__":
    sys.exit(main())
