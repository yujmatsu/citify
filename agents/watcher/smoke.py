"""WatcherAgent 実データ smoke = 自律性の合否ゲート (TASK-WATCHER Slice 1)。

ADK import + Gemini + BQ が要るので **実環境で人間が実行**する。
ツール選択を指示しないプロンプトのまま、エージェントが *自分で* search_speeches /
fetch_population_trend を呼び、Discovery を why_surfaced 付きで返すことを確認する。

使い方:
    cd ~/projects/citify
    set -a; source .env; set +a
    apps/api/.venv/bin/python -m agents.watcher.smoke \\
        --user demo-40-49 --age 40-49 --interests 子育て 教育 \\
        --home 11227 --watched 13104

判定:
    - run_log.tool_calls が **空でない** = LLM が自分でツールを選んだ (自律性 OK)
    - discoveries に why_surfaced が入っている = 「なぜあなたに」が生成できている
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys


async def _run(args: argparse.Namespace) -> int:
    from agents.watcher.main import WatcherAgent
    from agents.watcher.schema import WatchInput

    watch = WatchInput(
        user_id=args.user,
        age_group=args.age,  # type: ignore[arg-type]
        interests=args.interests,  # type: ignore[arg-type]
        home_municipality_code=args.home,
        watched_codes=args.watched,
    )
    repo = None
    if args.persist:
        from agents.watcher.repo import WatcherRepository

        repo = WatcherRepository()  # 本物の Firestore に保存 (Slice 2 検証)
    agent = WatcherAgent(project_id=args.project, repo=repo)
    result = await agent.run(watch)

    print("=" * 70)
    print(
        f"run_log: status={result.run_log.status} "
        f"n_discoveries={result.run_log.n_discoveries} "
        f"towns={result.run_log.towns_checked}"
    )
    print("--- tool_calls (LLM が自分で選んだ調査計画 = 自律性の証跡) ---")
    for tc in result.run_log.tool_calls:
        print(f"  {tc.tool}({tc.args})")
    print("--- discoveries ---")
    for d in result.discoveries:
        print(json.dumps(d.model_dump(), ensure_ascii=False, indent=2))

    autonomous = len(result.run_log.tool_calls) > 0
    has_why = all(d.why_surfaced for d in result.discoveries)
    print("=" * 70)
    print(
        f"SMOKE_RESULT={'OK' if autonomous else 'NO_TOOL_USE(自律性NG)'} "
        f"tool_calls={len(result.run_log.tool_calls)} why_surfaced_ok={has_why}"
    )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m agents.watcher.smoke")
    p.add_argument("--user", default="demo-40-49")
    p.add_argument("--age", default="40-49")
    p.add_argument("--interests", nargs="*", default=["子育て", "教育"])
    p.add_argument("--home", default="11227", help="住む街コード")
    p.add_argument("--watched", nargs="*", default=["13104"], help="気になる街コード")
    p.add_argument("--project", default=None)
    p.add_argument("--persist", action="store_true", help="Firestore に保存 (Slice 2 検証)")
    args = p.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
