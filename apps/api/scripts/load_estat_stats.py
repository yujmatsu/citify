"""Plan A Phase D — e-Stat 統計データを municipality_stats テーブルに投入。

正規化済み CSV (infra/seed/municipality_stats_normalized.csv) を読み込み、
派生指標 (youth_share_pct / elderly_share_pct / population_change_pct /
birth_rate_per_1000) を計算した上で BigQuery に WRITE_TRUNCATE で投入する。

正規化 CSV の事前準備は infra/seed/README_estat.md を参照。

使用方法:
    cd apps/api
    .venv/bin/python -m scripts.load_estat_stats \\
        --input ../../infra/seed/municipality_stats_normalized.csv \\
        --project citify-dev \\
        --dataset citify_curated \\
        --table municipality_stats \\
        [--dry-run]

正規化 CSV の期待列 (順不同 OK、欠損は NULL になる):
    municipality_code   5 桁 zero-pad
    municipality_name   自治体名
    prefecture          都道府県名
    population_total    総人口 (2020)
    population_15_29    15-29 歳人口
    population_65_plus  65+ 人口
    population_2015     2015 人口 (増減率算出用)
    households_total    総世帯数
    births_annual       年間出生数 (2023)
    data_year           主データ年 (通常 2020)
    source_url          引用元 URL
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


_EXPECTED_COLUMNS = (
    "municipality_code",
    "municipality_name",
    "prefecture",
    "population_total",
    "population_15_29",
    "population_65_plus",
    "population_2015",
    "households_total",
    "births_annual",
    "data_year",
    "source_url",
)


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    s = value.strip().replace(",", "")
    if not s or s.lower() in ("nan", "na", "-", "x"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _safe_pct(numerator: int | None, denominator: int | None) -> float | None:
    """欠損なら None、それ以外は (num/den)*100 を 2 桁丸めで返す。"""
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 100.0, 2)


def _safe_change_pct(latest: int | None, prior: int | None) -> float | None:
    """(latest - prior) / prior * 100 を 2 桁丸めで返す。"""
    if latest is None or prior in (None, 0):
        return None
    return round((latest - prior) / prior * 100.0, 2)


def _safe_per_1000(numerator: int | None, denominator: int | None) -> float | None:
    """出生率: (出生数/人口)*1000 を 2 桁丸めで返す。"""
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 1000.0, 2)


def _build_row(raw: dict[str, str], loaded_at: dt.datetime) -> dict[str, object] | None:
    """正規化 CSV の 1 行から BQ 投入用 dict を構築。必須欠損なら None。"""
    code = (raw.get("municipality_code") or "").strip().zfill(5)
    name = (raw.get("municipality_name") or "").strip()
    pref = (raw.get("prefecture") or "").strip()
    if not code or not name or not pref:
        return None

    population_total = _parse_int(raw.get("population_total"))
    population_15_29 = _parse_int(raw.get("population_15_29"))
    population_65_plus = _parse_int(raw.get("population_65_plus"))
    population_2015 = _parse_int(raw.get("population_2015"))
    households_total = _parse_int(raw.get("households_total"))
    births_annual = _parse_int(raw.get("births_annual"))
    data_year = _parse_int(raw.get("data_year")) or 2020

    return {
        "municipality_code": code,
        "municipality_name": name,
        "prefecture": pref,
        "population_total": population_total,
        "population_15_29": population_15_29,
        "population_65_plus": population_65_plus,
        "population_2015": population_2015,
        "households_total": households_total,
        "births_annual": births_annual,
        "youth_share_pct": _safe_pct(population_15_29, population_total),
        "elderly_share_pct": _safe_pct(population_65_plus, population_total),
        "population_change_pct": _safe_change_pct(population_total, population_2015),
        "birth_rate_per_1000": _safe_per_1000(births_annual, population_total),
        "data_year": data_year,
        "source_url": (raw.get("source_url") or "").strip() or None,
        "loaded_at": loaded_at.isoformat(),
    }


def load_normalized_csv(csv_path: Path) -> list[dict[str, object]]:
    """正規化 CSV を読み、派生指標を計算した row list を返す。"""
    loaded_at = dt.datetime.now(dt.UTC)
    rows: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in _EXPECTED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            logger.warning("missing expected columns (will be NULL): %s", missing)
        for raw in reader:
            row = _build_row(raw, loaded_at)
            if row is not None:
                rows.append(row)
    return rows


def write_to_bq(
    rows: list[dict[str, object]],
    project: str,
    dataset: str,
    table: str,
) -> None:
    """WRITE_TRUNCATE で全件入れ替え。"""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    table_ref = f"{project}.{dataset}.{table}"

    schema = [
        bigquery.SchemaField("municipality_code", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("municipality_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("prefecture", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("population_total", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("population_15_29", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("population_65_plus", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("population_2015", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("households_total", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("births_annual", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("youth_share_pct", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("elderly_share_pct", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("population_change_pct", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("birth_rate_per_1000", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("data_year", "INTEGER", mode="REQUIRED"),
        bigquery.SchemaField("source_url", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
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

    job = client.load_table_from_file(buf, table_ref, job_config=job_config)
    job.result()  # 完了待ち
    logger.info("loaded %d rows into %s", len(rows), table_ref)


def main() -> int:
    parser = argparse.ArgumentParser(description="e-Stat 統計を municipality_stats に投入")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("infra/seed/municipality_stats_normalized.csv"),
        help="正規化済み CSV のパス",
    )
    parser.add_argument("--project", required=False, default="citify-dev")
    parser.add_argument("--dataset", required=False, default="citify_curated")
    parser.add_argument("--table", required=False, default="municipality_stats")
    parser.add_argument("--dry-run", action="store_true", help="BQ に投入せず先頭 3 件表示")
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
        print(f"# (dry-run) total {len(rows)} rows ready to load")
        return 0

    if not rows:
        logger.warning("no rows to load — aborting")
        return 1

    write_to_bq(rows, args.project, args.dataset, args.table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
