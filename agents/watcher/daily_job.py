"""TASK-WATCHERV2 P5 — マイ街エージェント 日次先回り Job (A3 / Slice4)。

全ユーザーの user_watchlist を走査し、WatcherAgent を実行して最新の街選び分析を保存する。
Cloud Run Job + Cloud Scheduler で毎朝実行(パイプラインの後)。前回との変化検知(P4)も自動で走る。

設計:
    - **逐次実行**(同時多発の LLM 呼び出しを避け quota 429 を回避。memory の 429 既往に配慮)
    - 1 ユーザーの失敗で全体を止めない (graceful)
    - 街名はホーム表示と同様に BQ(municipality_stats)から解決し town_names を渡す

実行 (Cloud Run Job):
    python -m agents.watcher.daily_job --project-id citify-dev
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


def _load_municipality_names(project_id: str) -> dict[str, str]:
    """municipality_stats から code→name を 1 回ロード (street 名表示用)。失敗は空 dict。"""
    names: dict[str, str] = {}
    try:
        from google.cloud import bigquery

        dataset = os.getenv("BQ_DATASET_CURATED", "citify_curated")
        table = os.getenv("BQ_TABLE_STATS", "municipality_stats")
        client = bigquery.Client(project=project_id)
        sql = f"SELECT municipality_code, municipality_name FROM `{project_id}.{dataset}.{table}`"  # noqa: S608
        for row in client.query(sql).result(timeout=30):
            code = str(row.get("municipality_code") or "")
            name = row.get("municipality_name")
            if code and name:
                names[code] = name
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.daily.names_load_failed err=%s", exc)
    return names


async def _main(args: argparse.Namespace) -> int:
    from agents.watcher.main import WatcherAgent
    from agents.watcher.repo import WatcherRepository

    repo = WatcherRepository()
    agent = WatcherAgent(project_id=args.project_id, repo=repo)
    names = _load_municipality_names(args.project_id)

    watchlists = repo.list_all_watchlists()
    logger.info("watcher.daily.start n_users=%d", len(watchlists))

    ok = 0
    for w in watchlists:
        try:
            town_names = {c: names.get(c, f"自治体{c}") for c in w.all_codes()}
            result = await agent.run(w, town_names=town_names)
            status = result.run_log.status
            ok += 1 if status == "ok" else 0
            logger.info(
                "watcher.daily.user user=%s status=%s towns=%d",
                w.user_id,
                status,
                len(w.all_codes()),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher.daily.user_failed user=%s err=%s", w.user_id, exc)

    logger.info("watcher.daily.done ok=%d total=%d", ok, len(watchlists))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="python -m agents.watcher.daily_job")
    p.add_argument("--project-id", default=os.getenv("GOOGLE_CLOUD_PROJECT", "citify-dev"))
    args = p.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )
    return asyncio.run(_main(args))


if __name__ == "__main__":
    sys.exit(main())
