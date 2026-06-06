"""TASK-FISCAL — SSDS(統計でみる市区町村のすがた)5指標を municipality_stats に MERGE UPDATE。

fetch_ssds_indicators.py fetch の出力 (ssds_indicators_normalized.csv) を読み、
既存 municipality_stats の SSDS 由来列のみ UPDATE する (e-Stat/Reinfolib 列は破壊しない)。

設計 (load_reinfolib_stats.py を踏襲):
    - 一時テーブル経由で MERGE UPDATE-only (新規 INSERT はしない)
    - 既存列を壊さず SSDS 列のみ更新

使用方法:
    cd apps/api
    .venv/bin/python -m scripts.load_ssds_stats \\
        --input ../../infra/seed/ssds_indicators_normalized.csv \\
        --project citify-dev --dataset citify_curated --table municipality_stats \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# CSV→BQ にそのまま流す列 (派生計算は fetch 側で済んでいる)
_FLOAT_COLS = (
    "financial_capability_index",
    "real_debt_service_ratio_pct",
    "homeownership_rate_pct",
    "crime_rate_per_1000",
)
_INT_COLS = ("taxable_income_per_capita_yen", "ssds_data_year")


def _parse_float(value: str | None) -> float | None:
    if not value:
        return None
    s = value.strip()
    if not s or s.lower() in ("nan", "none", "null", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    f = _parse_float(value)
    return int(f) if f is not None else None


def _parse_str(value: str | None) -> str | None:
    if not value:
        return None
    s = value.strip()
    return s if s else None


def load_normalized_csv(csv_path: Path) -> list[dict[str, object]]:
    """ssds_indicators_normalized.csv を読み、BQ 投入用 dict list を返す。"""
    now = dt.datetime.now(dt.UTC).isoformat()
    rows: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            raw_code = (raw.get("municipality_code") or "").strip()
            if not raw_code:
                continue
            code = raw_code.zfill(5)
            rows.append(
                {
                    "municipality_code": code,
                    "financial_capability_index": _parse_float(
                        raw.get("financial_capability_index")
                    ),
                    "real_debt_service_ratio_pct": _parse_float(
                        raw.get("real_debt_service_ratio_pct")
                    ),
                    "taxable_income_per_capita_yen": _parse_int(
                        raw.get("taxable_income_per_capita_yen")
                    ),
                    "homeownership_rate_pct": _parse_float(raw.get("homeownership_rate_pct")),
                    "crime_rate_per_1000": _parse_float(raw.get("crime_rate_per_1000")),
                    "ssds_data_year": _parse_int(raw.get("ssds_data_year")),
                    "ssds_source_url": _parse_str(raw.get("ssds_source_url")),
                    "ssds_loaded_at": now,
                }
            )
    return rows


def write_to_bq(rows: list[dict[str, object]], project: str, dataset: str, table: str) -> None:
    """一時テーブルに upload → MERGE UPDATE で SSDS 列のみ更新。"""
    import io
    import json

    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    table_ref = f"{project}.{dataset}.{table}"
    tmp_ref = f"{project}.{dataset}._tmp_ssds_load"

    schema = [
        bigquery.SchemaField("municipality_code", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("financial_capability_index", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("real_debt_service_ratio_pct", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("taxable_income_per_capita_yen", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("homeownership_rate_pct", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("crime_rate_per_1000", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("ssds_data_year", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("ssds_source_url", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("ssds_loaded_at", "TIMESTAMP", mode="NULLABLE"),
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
    client.load_table_from_file(buf, tmp_ref, job_config=job_config).result()
    logger.info("loaded %d rows into temp %s", len(rows), tmp_ref)

    # MERGE UPDATE-only (既存の e-Stat / Reinfolib 列は壊さない)
    merge_sql = f"""
    MERGE INTO `{table_ref}` T
    USING `{tmp_ref}` S
    ON T.municipality_code = S.municipality_code
    WHEN MATCHED THEN UPDATE SET
      financial_capability_index = S.financial_capability_index,
      real_debt_service_ratio_pct = S.real_debt_service_ratio_pct,
      taxable_income_per_capita_yen = S.taxable_income_per_capita_yen,
      homeownership_rate_pct = S.homeownership_rate_pct,
      crime_rate_per_1000 = S.crime_rate_per_1000,
      ssds_data_year = S.ssds_data_year,
      ssds_source_url = S.ssds_source_url,
      ssds_loaded_at = S.ssds_loaded_at
    """
    merge_job = client.query(merge_sql)
    merge_job.result()
    logger.info("MERGE done dml_affected=%s", merge_job.num_dml_affected_rows)

    client.delete_table(tmp_ref, not_found_ok=True)
    logger.info("dropped temp table %s", tmp_ref)


def main() -> int:
    parser = argparse.ArgumentParser(description="SSDS 5指標を municipality_stats に MERGE UPDATE")
    parser.add_argument(
        "--input", type=Path, default=Path("infra/seed/ssds_indicators_normalized.csv")
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

    rows = load_normalized_csv(args.input)
    logger.info("parsed %d rows from %s", len(rows), args.input)

    if args.dry_run:
        import json

        for r in rows[:3]:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        print(f"# (dry-run) total {len(rows)} rows ready to MERGE UPDATE")
        for col in (*_FLOAT_COLS, *_INT_COLS):
            n = sum(1 for r in rows if r.get(col) is not None)
            print(f"#   {col}: {n}/{len(rows)} 非None")
        return 0

    if not rows:
        logger.warning("no rows to load — aborting")
        return 1

    write_to_bq(rows, args.project, args.dataset, args.table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
