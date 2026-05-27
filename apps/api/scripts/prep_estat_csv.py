"""Plan A Phase D — e-Stat 生 CSV を municipality_stats_normalized.csv に整形。

e-Stat からダウンロードした **生 CSV (cp932 / 階層的ヘッダ付き)** を読み込み、
infra/seed/municipality_stats_normalized.csv (UTF-8、列名 fixed) を出力する。
出力は apps/api/scripts/load_estat_stats.py の入力フォーマットに揃える。

対応する e-Stat 表 (v1: census-age のみ、他は今後追加):
  - census-age      : 令和2年国勢調査 表 2-7-1 (5歳階級別人口) — 市区町村別
  - census-household: 令和2年国勢調査 (世帯表) — 市区町村別の世帯総数  [TODO]
  - census-2015     : 平成27年国勢調査 (人口総数) — 市区町村別           [TODO]
  - births          : 人口動態 2023 (市区町村別出生数)                  [TODO]

municipality_master.csv に存在する code のみ採用し、prefecture もそこから取得する。

使用方法:
    cd apps/api
    .venv/bin/python -m scripts.prep_estat_csv \\
        --census-age ../../infra/seed/Tokei.csv \\
        --master ../../infra/seed/municipality_master.csv \\
        --output ../../infra/seed/municipality_stats_normalized.csv

将来 (4 ファイル揃った段階):
    .venv/bin/python -m scripts.prep_estat_csv \\
        --census-age ../../infra/seed/Tokei.csv \\
        --census-household ../../infra/seed/Tokei_household.csv \\
        --census-2015 ../../infra/seed/Tokei_2015.csv \\
        --births ../../infra/seed/Tokei_births.csv \\
        --master ../../infra/seed/municipality_master.csv \\
        --output ../../infra/seed/municipality_stats_normalized.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


_OUTPUT_COLUMNS = (
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

# e-Stat 表 2-7-1 source URL (公開ページ)
_SOURCE_URL_CENSUS_2020 = "https://www.e-stat.go.jp/stat-search/database?statdisp_id=0003445245"

# 国勢調査 2020 表 2-7-1 の列インデックス (0-origin)
# 0:時間軸code 1:時間軸補助 2:時間軸
# 3:国籍code 4:国籍補助 5:国籍
# 6:男女code 7:男女補助 8:男女
# 9:全国都道府県市区町村code 10:同補助 11:同名称
# 12:/年齢
# 13:総数 14:注釈 15:0-4歳 16:注釈 17:5-9歳 18:注釈 19:10-14歳 20:注釈
# 21:15-19歳 22:注釈 23:20-24歳 24:注釈 25:25-29歳 26:注釈
# ... 63:65歳以上(再掲) 64:注釈
_COL_NATIONALITY_CODE = 3
_COL_GENDER_CODE = 6
_COL_MUNI_CODE = 9
_COL_MUNI_NAME = 11
_COL_POP_TOTAL = 13
_COL_POP_15_19 = 21
_COL_POP_20_24 = 23
_COL_POP_25_29 = 25
_COL_POP_65_PLUS = 63

# ヘッダ行数 (e-Stat 2-7-1 は 14 行 = データ開始は 15 行目)
_HEADER_ROWS = 14


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    s = value.strip().replace(",", "").replace('"', "")
    if not s or s in ("-", "***", "X", "*", "…", "・"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _load_master(master_path: Path) -> dict[str, tuple[str, str]]:
    """municipality_master.csv を読み {code: (name, prefecture)} dict を返す。

    00000 (国会) は自治体ではないので除外。
    """
    out: dict[str, tuple[str, str]] = {}
    with master_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("municipality_code") or "").strip().zfill(5)
            name = (row.get("name") or "").strip()
            pref = (row.get("prefecture") or "").strip()
            if code == "00000" or pref == "国":
                continue
            if code and name and pref:
                out[code] = (name, pref)
    return out


def _parse_census_age(
    csv_path: Path,
    master: dict[str, tuple[str, str]],
) -> dict[str, dict[str, int | None]]:
    """国勢調査 2020 表 2-7-1 から code -> {pop_total, pop_15_29, pop_65_plus} を抽出。

    フィルタ条件:
      - 国籍コード = "0" (国籍総数)
      - 男女コード = "0" (総数)
      - 市区町村コードが municipality_master.csv に存在
    """
    out: dict[str, dict[str, int | None]] = {}
    with csv_path.open("r", encoding="cp932") as f:
        reader = csv.reader(f)
        for i, row in enumerate(reader):
            if i < _HEADER_ROWS:
                continue
            if len(row) <= _COL_POP_65_PLUS:
                continue
            if row[_COL_NATIONALITY_CODE].strip() != "0":
                continue
            if row[_COL_GENDER_CODE].strip() != "0":
                continue
            code = row[_COL_MUNI_CODE].strip().zfill(5)
            if code not in master:
                continue
            pop_total = _parse_int(row[_COL_POP_TOTAL])
            pop_15_19 = _parse_int(row[_COL_POP_15_19]) or 0
            pop_20_24 = _parse_int(row[_COL_POP_20_24]) or 0
            pop_25_29 = _parse_int(row[_COL_POP_25_29]) or 0
            pop_15_29: int | None = pop_15_19 + pop_20_24 + pop_25_29
            if pop_15_29 == 0:
                pop_15_29 = None
            pop_65_plus = _parse_int(row[_COL_POP_65_PLUS])
            out[code] = {
                "population_total": pop_total,
                "population_15_29": pop_15_29,
                "population_65_plus": pop_65_plus,
            }
    return out


def _write_output(
    output_path: Path,
    master: dict[str, tuple[str, str]],
    census_age: dict[str, dict[str, int | None]],
) -> int:
    """master のすべての code について 1 行ずつ出力 (census_age 不在ならカラム空)。"""
    written = 0
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_OUTPUT_COLUMNS)
        for code in sorted(master):
            name, pref = master[code]
            age = census_age.get(code, {})
            pop_total = age.get("population_total")
            pop_15_29 = age.get("population_15_29")
            pop_65_plus = age.get("population_65_plus")
            # MVP v1: 世帯/2015/出生は未対応
            row = [
                code,
                name,
                pref,
                "" if pop_total is None else pop_total,
                "" if pop_15_29 is None else pop_15_29,
                "" if pop_65_plus is None else pop_65_plus,
                "",  # population_2015
                "",  # households_total
                "",  # births_annual
                2020,
                _SOURCE_URL_CENSUS_2020,
            ]
            writer.writerow(row)
            written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="e-Stat 生 CSV を municipality_stats_normalized.csv に整形",
    )
    parser.add_argument(
        "--census-age",
        type=Path,
        required=True,
        help="国勢調査 2020 表 2-7-1 (5歳階級別人口) CSV — cp932",
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("infra/seed/municipality_master.csv"),
        help="municipality_master.csv",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("infra/seed/municipality_stats_normalized.csv"),
        help="出力先 (UTF-8)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    if not args.master.exists():
        logger.error("master CSV not found: %s", args.master)
        return 1
    if not args.census_age.exists():
        logger.error("census-age CSV not found: %s", args.census_age)
        return 1

    master = _load_master(args.master)
    logger.info("loaded %d entries from master", len(master))

    census_age = _parse_census_age(args.census_age, master)
    logger.info("parsed census-age for %d municipalities", len(census_age))
    missing = [c for c in master if c not in census_age]
    if missing:
        logger.warning("census-age missing for %d codes (sample=%s)", len(missing), missing[:5])

    written = _write_output(args.output, master, census_age)
    logger.info("wrote %d rows to %s", written, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
