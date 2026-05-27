"""Plan A Phase D v2 — e-Stat API 由来の 世帯/2015人口/出生数 を BQ MERGE UPDATE。

入力: scripts.fetch_estat_api fetch-all で生成した estat_v2_normalized.csv
処理: municipality_stats テーブルに対して households_total/population_2015/births_annual
      の 3 列 + 派生指標 (birth_rate_per_1000, population_change_pct) を UPDATE。
      既存の Phase D MVP データ (人口/若者/高齢化) と Phase F データ (Reinfolib) は
      破壊しない (MERGE UPDATE-only)。

派生指標は MERGE 内で T.population_total を使って計算:
    birth_rate_per_1000 = (S.births_annual / T.population_total) * 1000
    population_change_pct = ((T.population_total - S.population_2015) / S.population_2015) * 100

使用方法:
    cd apps/api
    .venv/bin/python -m scripts.load_estat_v2 \\
        --input ../../infra/seed/estat_v2_normalized.csv \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_int(value: str | None) -> int | None:
    if not value or not str(value).strip():
        return None
    s = str(value).strip()
    if s.lower() in ("nan", "none", "null", "-"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def load_csv(csv_path: Path) -> list[dict[str, object]]:
    """estat_v2_normalized.csv を読み、BQ 投入用 dict list を返す。"""
    rows: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            code = (raw.get("municipality_code") or "").strip().zfill(5)
            if not code:
                continue
            rows.append(
                {
                    "municipality_code": code,
                    "households_total": _parse_int(raw.get("households_total")),
                    "population_2015": _parse_int(raw.get("population_2015")),
                    "births_annual": _parse_int(raw.get("births_annual")),
                }
            )
    return rows


def write_to_bq(
    rows: list[dict[str, object]],
    project: str,
    dataset: str,
    table: str,
) -> None:
    """一時テーブル経由で MERGE UPDATE (e-Stat MVP / Reinfolib 列は保護)。"""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    table_ref = f"{project}.{dataset}.{table}"
    tmp_ref = f"{project}.{dataset}._tmp_estat_v2_load"

    schema = [
        bigquery.SchemaField("municipality_code", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("households_total", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("population_2015", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("births_annual", "INTEGER", mode="NULLABLE"),
    ]
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )

    import io
    import json

    buf = io.BytesIO()
    for row in rows:
        buf.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    buf.seek(0)

    job = client.load_table_from_file(buf, tmp_ref, job_config=job_config)
    job.result()
    logger.info("loaded %d rows into temp %s", len(rows), tmp_ref)

    # MERGE UPDATE-only (e-Stat MVP / Reinfolib 列を保護)
    # 派生指標 (birth_rate_per_1000, population_change_pct) も同時に計算
    merge_sql = f"""
    MERGE INTO `{table_ref}` T
    USING `{tmp_ref}` S
    ON T.municipality_code = S.municipality_code
    WHEN MATCHED THEN UPDATE SET
      households_total = S.households_total,
      population_2015 = S.population_2015,
      births_annual = S.births_annual,
      birth_rate_per_1000 = CASE
        WHEN S.births_annual IS NOT NULL AND T.population_total > 0
          THEN ROUND(S.births_annual / T.population_total * 1000.0, 2)
        ELSE NULL
      END,
      population_change_pct = CASE
        WHEN S.population_2015 > 0 AND T.population_total IS NOT NULL
          THEN ROUND((T.population_total - S.population_2015) / S.population_2015 * 100.0, 2)
        ELSE NULL
      END
    """
    merge_job = client.query(merge_sql)
    merge_job.result()
    logger.info("MERGE done dml_stats=%s", merge_job.num_dml_affected_rows)

    client.delete_table(tmp_ref, not_found_ok=True)
    logger.info("dropped temp table %s", tmp_ref)


def main() -> int:
    parser = argparse.ArgumentParser(description="e-Stat v2 (世帯/2015/出生) を MERGE UPDATE")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("../../infra/seed/estat_v2_normalized.csv"),
        help="default は apps/api 起点 (../../infra/seed/...)",
    )
    parser.add_argument("--project", default="citify-dev")
    parser.add_argument("--dataset", default="citify_curated")
    parser.add_argument("--table", default="municipality_stats")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    if not args.input.exists():
        logger.error("input CSV not found: %s", args.input)
        return 1

    rows = load_csv(args.input)
    logger.info("parsed %d rows from %s", len(rows), args.input)

    if args.dry_run:
        import json

        for r in rows[:3]:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        print(f"# (dry-run) total {len(rows)} rows ready to MERGE UPDATE")
        return 0

    if not rows:
        logger.warning("no rows to load — aborting")
        return 1

    write_to_bq(rows, args.project, args.dataset, args.table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
