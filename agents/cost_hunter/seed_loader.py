"""Sample seed loader (Plan CC Phase 3、Reviewer Low #6: 相対日付で将来腐敗回避)。

infra/seed/cost_observations_sample.json の `days_ago` フィールドを today - N に変換。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .schema import CostObservation

logger = logging.getLogger(__name__)


def load_sample_seed(
    path: Path | None = None,
    reference_date: date | None = None,
) -> list[CostObservation]:
    """seed JSON を読み込み、days_ago → 実日付 (today - N) に変換。

    Args:
        path: seed file path (None なら infra/seed/cost_observations_sample.json)
        reference_date: 基準日 (None なら today)
    """
    if path is None:
        path = (
            Path(__file__).resolve().parents[2] / "infra" / "seed" / "cost_observations_sample.json"
        )
    if not path.exists():
        logger.warning("cost_hunter.seed_not_found path=%s", path)
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("cost_hunter.seed_parse_failed err=%s", exc)
        return []

    today = reference_date or datetime.now(UTC).date()
    raw_obs = data.get("observations") if isinstance(data, dict) else data
    if not isinstance(raw_obs, list):
        return []

    results: list[CostObservation] = []
    for item in raw_obs:
        try:
            days_ago = int(item["days_ago"])
            obs_date = today - timedelta(days=days_ago)
            results.append(
                CostObservation(
                    date=obs_date,
                    service=item["service"],
                    cost_jpy=float(item["cost_jpy"]),
                    project_id=item.get("project_id", "citify-dev"),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cost_hunter.seed_item_invalid err=%s item=%s", exc, item)
    return results
