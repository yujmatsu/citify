"""TASK-POPTREND — 人口推移を municipality_population_series に投入。

2 ソースを統合して WRITE_TRUNCATE で全置換 (long format):
  - census    : municipality_stats の population_2015 (2015) / population_total (2020)
  - projection: fetch_population_series.py 出力 CSV (XKT013、2025-2070)

使い方:
    cd apps/api
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \\
    .venv/bin/python -m scripts.load_population_series \\
        --projection-csv ../../infra/seed/population_series_projection.csv \\
        --project citify-dev --dataset citify_curated \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

CENSUS_SOURCE_URL = "https://www.e-stat.go.jp/"  # 総務省 国勢調査
PROJECTION_SOURCE_URL = "https://www.reinfolib.mlit.go.jp/"  # 国交省 将来推計人口 (XKT013)

# municipality_stats の列 → census 年次マッピング
_CENSUS_COLUMNS = {
    "population_2015": 2015,
    "population_total": 2020,
}


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def load_projection_rows(csv_path: Path) -> list[dict[str, object]]:
    """fetch_population_series.py の long CSV (code, year, population) → series rows。"""
    rows: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            code = (raw.get("municipality_code") or "").strip().zfill(5)
            year = raw.get("year")
            pop = raw.get("population")
            if not code or not year or not pop:
                continue
            rows.append(
                {
                    "municipality_code": code,
                    "year": int(year),
                    "population": int(pop),
                    "source": "projection",
                    "loaded_at": _now(),
                    "source_url": PROJECTION_SOURCE_URL,
                }
            )
    return rows


def load_history_rows(csv_path: Path) -> list[dict[str, object]]:
    """prep_estat_population_history.py の long CSV (code, year, population) → census rows。

    Stage 2: 過去国勢調査 2000/2005/2010 を source='census' で投入。
    """
    rows: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            code = (raw.get("municipality_code") or "").strip().zfill(5)
            year = raw.get("year")
            pop = raw.get("population")
            if not code or not year or not pop:
                continue
            rows.append(
                {
                    "municipality_code": code,
                    "year": int(year),
                    "population": int(pop),
                    "source": "census",
                    "loaded_at": _now(),
                    "source_url": CENSUS_SOURCE_URL,
                }
            )
    return rows


def fetch_census_rows(project: str, dataset: str) -> list[dict[str, object]]:
    """municipality_stats から census 実績 (2015/2020) を long 形式で取得。"""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    cols = ", ".join(_CENSUS_COLUMNS)
    sql = f"SELECT municipality_code, {cols} FROM `{project}.{dataset}.municipality_stats`"  # noqa: S608
    rows: list[dict[str, object]] = []
    for r in client.query(sql).result():
        code = str(r["municipality_code"]).zfill(5)
        for col, year in _CENSUS_COLUMNS.items():
            pop = r[col]
            if pop is None:
                continue
            rows.append(
                {
                    "municipality_code": code,
                    "year": year,
                    "population": int(pop),
                    "source": "census",
                    "loaded_at": _now(),
                    "source_url": CENSUS_SOURCE_URL,
                }
            )
    return rows


def write_to_bq(rows: list[dict[str, object]], project: str, dataset: str) -> None:
    """municipality_population_series を WRITE_TRUNCATE で全置換。"""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    table_ref = f"{project}.{dataset}.municipality_population_series"

    schema = [
        bigquery.SchemaField("municipality_code", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("year", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("population", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("source", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("source_url", "STRING", mode="NULLABLE"),
    ]
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    buf = io.BytesIO()
    for row in rows:
        buf.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    buf.seek(0)
    job = client.load_table_from_file(buf, table_ref, job_config=job_config)
    job.result()
    logger.info("loaded %d rows into %s (WRITE_TRUNCATE)", len(rows), table_ref)


def main() -> int:
    p = argparse.ArgumentParser(description="人口推移を municipality_population_series に投入")
    p.add_argument("--projection-csv", type=Path, required=True)
    p.add_argument(
        "--census-history-csv",
        type=Path,
        default=None,
        help="Stage 2: prep_estat_population_history.py 出力 (2000/2005/2010 census)",
    )
    p.add_argument("--project", default="citify-dev")
    p.add_argument("--dataset", default="citify_curated")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    if not args.projection_csv.exists():
        logger.error("projection CSV not found: %s", args.projection_csv)
        return 1

    projection = load_projection_rows(args.projection_csv)
    logger.info("projection rows=%d", len(projection))

    # Stage 2: 過去 census (2000/2005/2010) を CSV から (任意)
    history: list[dict[str, object]] = []
    if args.census_history_csv is not None:
        if not args.census_history_csv.exists():
            logger.error("census history CSV not found: %s", args.census_history_csv)
            return 1
        history = load_history_rows(args.census_history_csv)
        logger.info("census history rows=%d", len(history))

    if args.dry_run:
        print(f"# projection rows: {len(projection)}")
        for r in projection[:3]:
            print(json.dumps(r, ensure_ascii=False))
        print(f"# census history rows: {len(history)}")
        for r in history[:3]:
            print(json.dumps(r, ensure_ascii=False))
        print("# census (municipality_stats 2015/2020): BQ 接続が必要なため dry-run では skip")
        return 0

    census = fetch_census_rows(args.project, args.dataset)
    logger.info("census (2015/2020) rows=%d", len(census))

    # (code, year) 防御的 dedup: history(2000-2010) と municipality_stats census(2015/2020) は
    # 年次が排他なので実際は重複しない。重複時は history 優先 (組替で境界整合)。
    by_key: dict[tuple[str, int], dict[str, object]] = {}
    for r in census + projection:
        by_key[(r["municipality_code"], r["year"])] = r
    for r in history:  # history を後勝ち = 優先
        by_key[(r["municipality_code"], r["year"])] = r
    all_rows = list(by_key.values())

    if not all_rows:
        logger.warning("no rows to load — aborting")
        return 1
    write_to_bq(all_rows, args.project, args.dataset)
    return 0


if __name__ == "__main__":
    sys.exit(main())
