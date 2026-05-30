"""Plan A Phase F — Reinfolib 統計を municipality_stats テーブルに MERGE UPDATE。

reinfolib_normalized.csv (scrapers/reinfolib/__main__.py fetch-all の出力) を
読み込み、既存 municipality_stats テーブルの reinfolib 由来 6 列のみ UPDATE する
(e-Stat 由来列は破壊しない)。

設計:
    - WHEN NOT MATCHED THEN INSERT は使わない (Phase D で全 1794 自治体 INSERT 済前提)
    - 一時テーブル経由で MERGE 文を実行
    - WRITE_TRUNCATE ではなく UPDATE-only (Phase D データを保護)

使用方法:
    cd apps/api
    .venv/bin/python -m scripts.load_reinfolib_stats \\
        --input ../../infra/seed/reinfolib_normalized.csv \\
        --project citify-dev \\
        --dataset citify_curated \\
        --table municipality_stats \\
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


_REINFOLIB_COLUMNS = (
    "municipality_code",
    "used_apartment_median_price_man_yen",
    "used_apartment_sample_size",
    "used_apartment_median_unit_price_yen",
    "used_apartment_avg_building_age",
    "emergency_shelter_count",
    "emergency_shelter_official_link",
    "reinfolib_loaded_at",
    "reinfolib_source_url",
)


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    s = value.strip()
    if not s or s.lower() in ("nan", "none", "null", "-"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


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


def _parse_str(value: str | None) -> str | None:
    if not value:
        return None
    s = value.strip()
    return s if s else None


def load_normalized_csvs(csv_paths: list[Path]) -> list[dict[str, object]]:
    """複数 normalized CSV を読み結合。同一 municipality_code は後勝ち (warning 付き)。

    Phase F v4: region 別 9 ファイル (reinfolib_normalized_*.csv) を 1 回の MERGE で
    処理するために追加。事前調査では 9 region 間に重複コードはないが、念のため
    後勝ち dedup + warning で保護する。
    """
    merged: dict[str, dict[str, object]] = {}
    for path in csv_paths:
        file_rows = load_normalized_csv(path)
        for row in file_rows:
            code = str(row["municipality_code"])
            if code in merged:
                logger.warning(
                    "duplicate municipality_code=%s (後勝ちで上書き) file=%s", code, path
                )
            merged[code] = row
        logger.info("parsed %d rows from %s", len(file_rows), path)
    return list(merged.values())


def load_normalized_csv(csv_path: Path) -> list[dict[str, object]]:
    """reinfolib_normalized.csv を読み、BQ 投入用 dict list を返す。"""
    rows: list[dict[str, object]] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            # zfill は空チェックの後に。空文字を先に zfill すると "00000" (国会コード) に
            # 化けて空行が混入するため、raw が空なら skip してから 5 桁ゼロ埋めする。
            raw_code = (raw.get("municipality_code") or "").strip()
            if not raw_code:
                continue
            code = raw_code.zfill(5)
            rows.append(
                {
                    "municipality_code": code,
                    "used_apartment_median_price_man_yen": _parse_int(
                        raw.get("used_apartment_median_price_man_yen")
                    ),
                    "used_apartment_sample_size": _parse_int(raw.get("used_apartment_sample_size")),
                    "used_apartment_median_unit_price_yen": _parse_int(
                        raw.get("used_apartment_median_unit_price_yen")
                    ),
                    "used_apartment_avg_building_age": _parse_float(
                        raw.get("used_apartment_avg_building_age")
                    ),
                    "emergency_shelter_count": _parse_int(raw.get("emergency_shelter_count")),
                    "emergency_shelter_official_link": _parse_str(
                        raw.get("emergency_shelter_official_link")
                    ),
                    # Phase F v3: XKT010/XKT007 (CSV にカラムがあれば値、なければ None)
                    # NOTE: XKT013 由来の population_2025/2050/change は TASK-POPFIX (2026-05-30) で
                    # 除外。z=11 50km四方メッシュ合算が全国 88% で実人口の 2倍超 (最悪 2870倍) の
                    # 異常値になるため。人口は e-Stat (population_total / population_change_pct) を SSoT 化。
                    "medical_facility_count": _parse_int(raw.get("medical_facility_count")),
                    "medical_hospital_count": _parse_int(raw.get("medical_hospital_count")),
                    "medical_clinic_count": _parse_int(raw.get("medical_clinic_count")),
                    "childcare_facility_count": _parse_int(raw.get("childcare_facility_count")),
                    "kindergarten_count": _parse_int(raw.get("kindergarten_count")),
                    "nursery_count": _parse_int(raw.get("nursery_count")),
                    "reinfolib_loaded_at": _parse_str(raw.get("reinfolib_loaded_at"))
                    or dt.datetime.now(dt.UTC).isoformat(),
                    "reinfolib_source_url": _parse_str(raw.get("reinfolib_source_url")),
                }
            )
    return rows


def write_to_bq(
    rows: list[dict[str, object]],
    project: str,
    dataset: str,
    table: str,
) -> None:
    """一時テーブルに upload → MERGE UPDATE で reinfolib 列のみ更新。"""
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    table_ref = f"{project}.{dataset}.{table}"
    tmp_ref = f"{project}.{dataset}._tmp_reinfolib_load"

    schema = [
        bigquery.SchemaField("municipality_code", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("used_apartment_median_price_man_yen", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("used_apartment_sample_size", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("used_apartment_median_unit_price_yen", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("used_apartment_avg_building_age", "FLOAT", mode="NULLABLE"),
        bigquery.SchemaField("emergency_shelter_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("emergency_shelter_official_link", "STRING", mode="NULLABLE"),
        # Phase F v3 (XKT013 population は TASK-POPFIX で除外。e-Stat を SSoT 化)
        bigquery.SchemaField("medical_facility_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("medical_hospital_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("medical_clinic_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("childcare_facility_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("kindergarten_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("nursery_count", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("reinfolib_loaded_at", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("reinfolib_source_url", "STRING", mode="NULLABLE"),
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

    # MERGE UPDATE-only (e-Stat 列は壊さない、新規 INSERT も意図的に無効化)
    merge_sql = f"""
    MERGE INTO `{table_ref}` T
    USING `{tmp_ref}` S
    ON T.municipality_code = S.municipality_code
    WHEN MATCHED THEN UPDATE SET
      used_apartment_median_price_man_yen = S.used_apartment_median_price_man_yen,
      used_apartment_sample_size = S.used_apartment_sample_size,
      used_apartment_median_unit_price_yen = S.used_apartment_median_unit_price_yen,
      used_apartment_avg_building_age = S.used_apartment_avg_building_age,
      emergency_shelter_count = S.emergency_shelter_count,
      emergency_shelter_official_link = S.emergency_shelter_official_link,
      medical_facility_count = S.medical_facility_count,
      medical_hospital_count = S.medical_hospital_count,
      medical_clinic_count = S.medical_clinic_count,
      childcare_facility_count = S.childcare_facility_count,
      kindergarten_count = S.kindergarten_count,
      nursery_count = S.nursery_count,
      reinfolib_loaded_at = S.reinfolib_loaded_at,
      reinfolib_source_url = S.reinfolib_source_url
    """
    merge_job = client.query(merge_sql)
    merge_job.result()
    logger.info("MERGE done dml_stats=%s", merge_job.num_dml_affected_rows)

    # 一時テーブル削除
    client.delete_table(tmp_ref, not_found_ok=True)
    logger.info("dropped temp table %s", tmp_ref)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reinfolib 統計を municipality_stats に MERGE UPDATE",
    )
    parser.add_argument(
        "--input",
        type=Path,
        nargs="+",
        default=[Path("infra/seed/reinfolib_normalized.csv")],
        help="1 つ以上の normalized CSV (複数指定で結合してから MERGE。region 別 9 ファイル等)",
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

    missing = [p for p in args.input if not p.exists()]
    if missing:
        logger.error("input CSV not found: %s", missing)
        return 1

    rows = load_normalized_csvs(args.input)
    logger.info("parsed %d total rows from %d file(s)", len(rows), len(args.input))

    if args.dry_run:
        import json

        for r in rows[:3]:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        print(f"# (dry-run) total {len(rows)} rows ready to MERGE UPDATE")
        # 派生列の非 None 件数を集計 (全 None 上書きで既存値を消さないことの定量確認)
        check_cols = (
            "used_apartment_median_price_man_yen",
            "emergency_shelter_count",
            "medical_facility_count",
            "childcare_facility_count",
            "kindergarten_count",
            "nursery_count",
        )
        print("# 非 None 件数 (列が CSV に実在し値が入っている行数):")
        for col in check_cols:
            n = sum(1 for r in rows if r.get(col) is not None)
            print(f"#   {col}: {n}/{len(rows)}")
        return 0

    if not rows:
        logger.warning("no rows to load — aborting")
        return 1

    write_to_bq(rows, args.project, args.dataset, args.table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
