"""TASK-POPTREND Stage 2 — e-Stat 国勢調査 時系列 Excel → 過去人口 long CSV。

e-Stat「時系列データ 第6表 年齢(3区分),男女別人口 － 都道府県,市区町村」の
**都道府県別 Excel (.xlsx、47 ファイル)** を読み、2000/2005/2010 の市区町村別総人口を
long CSV (municipality_code, year, population) に整形する。後段は load_population_series.py。

設計 (実ファイル da0614.xlsx で確認):
  - 各 xlsx は 11 シート (各年 1980-2020)。行は long (列1=年次西暦, 列3=コード, 列5=総数)
  - 年次は各行の列1 ("2000年") から判定 → シート名解決やヘッダ行数前提に依存しない
  - 政令市は親コード行 (14100 横浜市) が存在 → municipality_master のコードで filter するだけ
    (区 14101+ は master に無いので自動除外、区合算不要)
  - openpyxl 不使用、xlsx を zipfile + XML で直接パース (標準ライブラリのみ)

使い方:
    cd apps/api
    .venv/bin/python -m scripts.prep_estat_population_history \\
        --input-dir ../../infra/seed \\
        --glob 'da06*.xlsx' \\
        --master ../../infra/seed/municipality_master.csv \\
        --output ../../infra/seed/population_series_census_history.csv
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_M = {"m": _NS}

# Stage 2 で採用する年次 (2015/2020 は既存 municipality_stats を使うため除外)
DEFAULT_YEARS = (2000, 2005, 2010)

_YEAR_RE = re.compile(r"(\d{4})\s*年")
OUTPUT_COLUMNS = ("municipality_code", "year", "population")

# Excel 列インデックス (0-origin、実ファイル確認済)
_COL_YEAR = 0  # 列1 年次西暦 "2000年"
_COL_CODE = 2  # 列3 自治体コード
_COL_POP = 4  # 列5 総数 (総人口)


def _load_master_codes(master_csv: Path) -> set[str]:
    """municipality_master.csv の現行自治体コード集合 (5桁ゼロ埋め)。"""
    codes: set[str] = set()
    with master_csv.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            c = (row.get("municipality_code") or "").strip()
            if c:
                codes.add(c.zfill(5))
    return codes


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    out: list[str] = []
    for si in root.findall("m:si", _M):
        out.append("".join(t.text or "" for t in si.iter(f"{{{_NS}}}t")))
    return out


def _cell_text(c: ET.Element, shared: list[str]) -> str:
    v = c.find("m:v", _M)
    if v is None or v.text is None:
        return ""
    if c.get("t") == "s":
        idx = int(v.text)
        return shared[idx] if 0 <= idx < len(shared) else ""
    return v.text


def _col_index(cell_ref: str | None) -> int | None:
    """セル参照 'C10' から 0-origin 列インデックス (A=0)。"""
    if not cell_ref:
        return None
    m = re.match(r"([A-Z]+)\d+", cell_ref)
    if not m:
        return None
    col = 0
    for ch in m.group(1):
        col = col * 26 + (ord(ch) - ord("A") + 1)
    return col - 1


def _parse_pop(raw: str) -> int | None:
    s = (raw or "").strip().replace(",", "")
    if not s or s in ("-", "***", "X", "…", "－"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _row_cells(row: ET.Element, shared: list[str]) -> dict[int, str]:
    """row の {列インデックス: 文字列} を返す (欠損セルは抜ける)。"""
    out: dict[int, str] = {}
    for c in row.findall("m:c", _M):
        idx = _col_index(c.get("r"))
        if idx is not None:
            out[idx] = _cell_text(c, shared)
    return out


def parse_xlsx(path: Path, master_codes: set[str], years: tuple[int, ...]) -> list[dict]:
    """1 つの都道府県 xlsx から (code, year, population) を抽出。"""
    rows_out: list[dict] = []
    with zipfile.ZipFile(path) as z:
        shared = _shared_strings(z)
        sheets = [n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n)]
        for sheet in sheets:
            root = ET.fromstring(z.read(sheet))
            sd = root.find("m:sheetData", _M)
            if sd is None:
                continue
            for row in sd.findall("m:row", _M):
                cells = _row_cells(row, shared)
                year_m = _YEAR_RE.search(cells.get(_COL_YEAR, ""))
                code = (cells.get(_COL_CODE, "") or "").strip()
                if not year_m or not code.isdigit():
                    continue
                year = int(year_m.group(1))
                code5 = code.zfill(5)
                if year not in years or code5 not in master_codes:
                    continue
                pop = _parse_pop(cells.get(_COL_POP, ""))
                if pop is None:
                    continue
                rows_out.append({"municipality_code": code5, "year": year, "population": pop})
    return rows_out


def main() -> int:
    p = argparse.ArgumentParser(description="e-Stat 時系列 Excel → 過去人口 long CSV")
    p.add_argument("--input-dir", type=Path, default=Path("infra/seed"))
    p.add_argument("--glob", default="da06*.xlsx", help="対象 xlsx の glob")
    p.add_argument("--master", type=Path, default=Path("infra/seed/municipality_master.csv"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument(
        "--years",
        type=int,
        nargs="+",
        default=list(DEFAULT_YEARS),
        help="採用年次 (default 2000 2005 2010)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    master_codes = _load_master_codes(args.master)
    files = sorted(args.input_dir.glob(args.glob))
    if not files:
        logger.error("no xlsx matched: %s/%s", args.input_dir, args.glob)
        return 1
    logger.info(
        "prep start files=%d master_codes=%d years=%s", len(files), len(master_codes), args.years
    )

    # (code, year) 防御的 dedup (都道府県別なので実際は重複しないはず)
    merged: dict[tuple[str, int], dict] = {}
    for f in files:
        rows = parse_xlsx(f, master_codes, tuple(args.years))
        for r in rows:
            merged[(r["municipality_code"], r["year"])] = r
        logger.info("parsed %s rows=%d", f.name, len(rows))

    out_rows = sorted(merged.values(), key=lambda r: (r["municipality_code"], r["year"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(out_rows)
    logger.info("prep done output=%s rows=%d", args.output, len(out_rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
