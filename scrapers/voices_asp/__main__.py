"""voices_asp スクレイパー CLI: inspect / years / list / fetch サブコマンド。

使用例:
    # 1. DOM 構造確認 (年度一覧ページ)
    python -m scrapers.voices_asp inspect --tenant sapporo

    # 2. 年度一覧 (本会議録)
    python -m scrapers.voices_asp years --tenant sapporo --type honkai

    # 3. 特定年度の会議一覧
    python -m scrapers.voices_asp list --tenant sapporo --year 2025 --type honkai --max 10

    # 4. 1 会議の発言取得
    python -m scrapers.voices_asp fetch \\
        --tenant sapporo \\
        --url "https://sapporo.gijiroku.com/voices/g08v_viewh.asp?..."

    # 白ラベル (minato, 独自 subdomain) は --base-url 指定
    python -m scrapers.voices_asp years \\
        --tenant minato \\
        --base-url "https://gikai2.city.minato.tokyo.jp/voices/" \\
        --type honkai
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

from .client import CENTRAL_BASE_URL_TEMPLATE, VoicesAspClient


def _build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--tenant", required=True, help="テナント ID (sapporo, minato 等)")
    common.add_argument(
        "--base-url",
        default=None,
        help=f"白ラベル用上書き URL (None で {CENTRAL_BASE_URL_TEMPLATE})",
    )
    common.add_argument("--timeout-sec", type=float, default=30.0)
    common.add_argument("--rate-limit-sec", type=float, default=1.0)
    common.add_argument("-v", "--verbose", action="store_true")

    parser = argparse.ArgumentParser(
        prog="python -m scrapers.voices_asp",
        description="VOICES/Web スクレイパー (A-4b)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inspect = sub.add_parser("inspect", parents=[common], help="DOM ダンプ")
    p_inspect.add_argument("--path", default="g08v_viewh.asp")

    p_years = sub.add_parser("years", parents=[common], help="年度一覧取得")
    p_years.add_argument(
        "--type", dest="meeting_type", choices=["honkai", "iinkai", "rinji"], default="honkai"
    )

    p_list = sub.add_parser("list", parents=[common], help="指定年度の会議一覧")
    p_list.add_argument("--year", type=int, required=True)
    p_list.add_argument(
        "--type", dest="meeting_type", choices=["honkai", "iinkai", "rinji"], default="honkai"
    )
    p_list.add_argument("--max", type=int, default=20)

    p_fetch = sub.add_parser("fetch", parents=[common], help="1 会議の発言取得")
    p_fetch.add_argument("--url", required=True)
    p_fetch.add_argument("--max-speeches", type=int, default=50)

    return parser


async def _cmd_inspect(args: argparse.Namespace) -> int:
    async with VoicesAspClient(
        tenant_id=args.tenant,
        base_url=args.base_url,
        timeout_sec=args.timeout_sec,
        rate_limit_sec=args.rate_limit_sec,
    ) as c:
        result = await c.inspect_page(path=args.path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


async def _cmd_years(args: argparse.Namespace) -> int:
    async with VoicesAspClient(
        tenant_id=args.tenant,
        base_url=args.base_url,
        timeout_sec=args.timeout_sec,
        rate_limit_sec=args.rate_limit_sec,
    ) as c:
        years = await c.fetch_year_list(meeting_type=args.meeting_type)
    print(f"# Got {len(years)} years for tenant={args.tenant}", file=sys.stderr)
    for y in years:
        print(y.model_dump_json())
    return 0


async def _cmd_list(args: argparse.Namespace) -> int:
    async with VoicesAspClient(
        tenant_id=args.tenant,
        base_url=args.base_url,
        timeout_sec=args.timeout_sec,
        rate_limit_sec=args.rate_limit_sec,
    ) as c:
        meetings = await c.fetch_meetings_for_year(args.year, meeting_type=args.meeting_type)
    print(
        f"# Got {len(meetings)} meetings for tenant={args.tenant} year={args.year}",
        file=sys.stderr,
    )
    for m in meetings[: args.max]:
        print(m.model_dump_json())
    return 0


async def _cmd_fetch(args: argparse.Namespace) -> int:
    async with VoicesAspClient(
        tenant_id=args.tenant,
        base_url=args.base_url,
        timeout_sec=args.timeout_sec,
        rate_limit_sec=args.rate_limit_sec,
    ) as c:
        speeches = await c.fetch_speeches(args.url, max_speeches=args.max_speeches)
    print(f"# Got {len(speeches)} speeches", file=sys.stderr)
    for s in speeches[:3]:
        data = s.model_dump()
        data["content_text"] = data["content_text"][:100] + (
            "…" if len(s.content_text) > 100 else ""
        )
        print(json.dumps(data, ensure_ascii=False))
    if len(speeches) > 3:
        print(f"# ... and {len(speeches) - 3} more", file=sys.stderr)
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
        "years": _cmd_years,
        "list": _cmd_list,
        "fetch": _cmd_fetch,
    }
    return asyncio.run(handlers[args.cmd](args))


if __name__ == "__main__":
    sys.exit(main())
