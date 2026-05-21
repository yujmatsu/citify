"""DiscussNet スクレイパー CLI: inspect / councils / schedules / speeches。

ツリー構造の各層に対応した subcommand:
- inspect: DOM ダンプ (セレクタ決定用)
- councils: L1 定例会・臨時会一覧
- schedules: L2 council 配下の会議日一覧
- speeches: L3 1 議事録の発言取得

使用例:
    # まず DOM 確認
    python -m scrapers.kaigiroku_net inspect --tenant prefokayama

    # L1: 定例会一覧
    python -m scrapers.kaigiroku_net councils --tenant prefokayama --max 10

    # L2: 特定 council の会議日一覧
    python -m scrapers.kaigiroku_net schedules --tenant prefokayama --council-id 177

    # L3: 個別議事録の発言取得
    python -m scrapers.kaigiroku_net speeches \\
        --tenant prefokayama --council-id 177 --schedule-id 1

    # 白ラベル型 (横浜) は --base-url で指定
    python -m scrapers.kaigiroku_net councils --tenant yokohama \\
        --base-url "http://giji.city.yokohama.lg.jp/tenant/yokohama/" --max 5

    # 目視デバッグ (headless OFF)
    python -m scrapers.kaigiroku_net inspect --tenant prefokayama --no-headless
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
    common.add_argument("--tenant", required=True, help="テナント ID (例: prefokayama)")
    common.add_argument("--base-url", default=None, help="白ラベル型の上書き URL")
    common.add_argument("--no-headless", action="store_true", help="目視デバッグ用")
    common.add_argument("--timeout-ms", type=int, default=30_000)
    common.add_argument("--rate-limit-sec", type=float, default=5.0, help="連続リクエスト間隔 (秒)")
    common.add_argument("-v", "--verbose", action="store_true")

    parser = argparse.ArgumentParser(
        prog="python -m scrapers.kaigiroku_net",
        description="DiscussNet (kaigiroku.net) スクレイパー (A-4)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inspect = sub.add_parser("inspect", parents=[common], help="DOM ダンプ")
    p_inspect.add_argument("--path", default="MinuteBrowse.html")

    p_councils = sub.add_parser("councils", parents=[common], help="L1 council 一覧")
    p_councils.add_argument("--path", default="MinuteBrowse.html")
    p_councils.add_argument("--max", type=int, default=20)

    p_schedules = sub.add_parser("schedules", parents=[common], help="L2 会議日一覧")
    p_schedules.add_argument("--council-id", required=True)
    p_schedules.add_argument("--tenant-id-num", default=None, help="テナント数値 ID (なら自動取得)")
    p_schedules.add_argument("--max", type=int, default=50)

    p_speeches = sub.add_parser("speeches", parents=[common], help="L3 発言取得")
    p_speeches.add_argument("--council-id", required=True)
    p_speeches.add_argument("--schedule-id", required=True)
    p_speeches.add_argument("--max-speeches", type=int, default=200)

    return parser


async def _cmd_inspect(args: argparse.Namespace) -> int:
    async with _client(args) as client:
        result = await client.inspect_page(path=args.path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def _cmd_councils(args: argparse.Namespace) -> int:
    async with _client(args) as client:
        councils = await client.list_councils(path=args.path, max_items=args.max)
    print(
        f"# Got {len(councils)} councils from tenant={args.tenant}",
        file=sys.stderr,
    )
    for c in councils:
        print(c.model_dump_json())
    return 0


async def _cmd_schedules(args: argparse.Namespace) -> int:
    async with _client(args) as client:
        schedules = await client.list_schedules(
            council_id=args.council_id,
            tenant_id_num=args.tenant_id_num,
            max_items=args.max,
        )
    print(
        f"# Got {len(schedules)} schedules from council_id={args.council_id}",
        file=sys.stderr,
    )
    for s in schedules:
        print(s.model_dump_json())
    return 0


async def _cmd_speeches(args: argparse.Namespace) -> int:
    async with _client(args) as client:
        speeches = await client.fetch_speeches(
            council_id=args.council_id,
            schedule_id=args.schedule_id,
            max_speeches=args.max_speeches,
        )
    print(f"# Got {len(speeches)} speeches", file=sys.stderr)
    for s in speeches[:5]:
        data = s.model_dump()
        data["content_text"] = data["content_text"][:120] + (
            "…" if len(s.content_text) > 120 else ""
        )
        print(json.dumps(data, ensure_ascii=False, default=str))
    if len(speeches) > 5:
        print(f"# ... and {len(speeches) - 5} more", file=sys.stderr)
    return 0


def _client(args: argparse.Namespace) -> KaigirokuNetClient:
    return KaigirokuNetClient(
        tenant_id=args.tenant,
        base_url=args.base_url,
        headless=not args.no_headless,
        timeout_ms=args.timeout_ms,
        rate_limit_sec=args.rate_limit_sec,
    )


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    handlers = {
        "inspect": _cmd_inspect,
        "councils": _cmd_councils,
        "schedules": _cmd_schedules,
        "speeches": _cmd_speeches,
    }
    return asyncio.run(handlers[args.cmd](args))


if __name__ == "__main__":
    sys.exit(main())
