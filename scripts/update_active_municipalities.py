"""municipalities.json の is_active フラグを BQ 実データから再生成する。

`is_active` は「フィードにデータが配信されている自治体」を表すが、
手動メンテのため陳腐化しやすい (2026-07-02 時点で 00000 のみ active だったが
実際は 830 コードにデータが存在した)。このスクリプトで BQ を正として同期する。

実行 (WSL2 では certifi が読めないため CA バンドルを明示):
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    apps/api/.venv/bin/python scripts/update_active_municipalities.py
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from google.cloud import bigquery

logger = logging.getLogger(__name__)

PROJECT_ID = "citify-dev"
MUNICIPALITIES_JSON = Path(__file__).resolve().parent.parent / "apps/web/public/municipalities.json"
QUERY = """
SELECT DISTINCT municipality_code
FROM `citify-dev.citify_curated.scored_speeches_latest`
"""


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    client = bigquery.Client(project=PROJECT_ID)
    active_codes = {row.municipality_code for row in client.query(QUERY).result()}
    logger.info("BQ active codes: %d", len(active_codes))

    data = json.loads(MUNICIPALITIES_JSON.read_text(encoding="utf-8"))
    items = data["items"]
    changed = 0
    for m in items:
        new_active = m["code"] in active_codes
        if m.get("is_active") != new_active:
            m["is_active"] = new_active
            changed += 1

    MUNICIPALITIES_JSON.write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    logger.info(
        "updated %s: %d entries changed (active total: %d)",
        MUNICIPALITIES_JSON,
        changed,
        sum(1 for m in items if m["is_active"]),
    )


if __name__ == "__main__":
    main()
