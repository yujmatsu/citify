"""prep_estat_population_history.py の test (TASK-POPTREND Stage 2)。

純関数は常に実行。実 xlsx (infra/seed/da0614.xlsx 神奈川) があれば統合 test も実行。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APPS_API_DIR = Path(__file__).resolve().parents[1]
if str(_APPS_API_DIR) not in sys.path:
    sys.path.insert(0, str(_APPS_API_DIR))

from scripts.prep_estat_population_history import (  # noqa: E402
    _YEAR_RE,
    _col_index,
    _parse_pop,
    parse_xlsx,
)

_REPO_ROOT = _APPS_API_DIR.parents[1]
_KANAGAWA_XLSX = _REPO_ROOT / "infra" / "seed" / "da0614.xlsx"


# ============================================================================
# 純関数
# ============================================================================


def test_parse_pop_handles_numbers_and_secret_markers() -> None:
    assert _parse_pop("8245900") == 8245900
    assert _parse_pop("3,426,651") == 3426651  # カンマ区切り
    assert _parse_pop("") is None
    assert _parse_pop("-") is None
    assert _parse_pop("***") is None  # 秘匿
    assert _parse_pop("X") is None
    assert _parse_pop("abc") is None


def test_col_index_excel_ref() -> None:
    assert _col_index("A10") == 0
    assert _col_index("C10") == 2  # 自治体コード列
    assert _col_index("E7") == 4  # 総数列
    assert _col_index("AA1") == 26
    assert _col_index(None) is None


def test_year_regex_extracts_seireki() -> None:
    assert _YEAR_RE.search("2000年").group(1) == "2000"
    assert _YEAR_RE.search("1995年").group(1) == "1995"
    assert _YEAR_RE.search("地域") is None


# ============================================================================
# 実 xlsx 統合 (神奈川 da0614.xlsx があれば)
# ============================================================================


@pytest.mark.skipif(not _KANAGAWA_XLSX.exists(), reason="da0614.xlsx 未配置")
def test_parse_kanagawa_yokohama_population() -> None:
    """横浜市 14100 の 2000/2005/2010 総人口が実人口相当か (政令市親コード)。"""
    master = {"14100", "14130", "14000"}  # 横浜市 / 川崎市 / 神奈川県
    rows = parse_xlsx(_KANAGAWA_XLSX, master_codes=master, years=(2000, 2005, 2010))

    by_key = {(r["municipality_code"], r["year"]): r["population"] for r in rows}
    # 横浜市 2000 ≈ 342 万 (政令市親コードで区合算不要)
    assert by_key[("14100", 2000)] == 3426651
    assert by_key[("14100", 2010)] == 3688773
    # 川崎市 2000 ≈ 125 万
    assert by_key[("14130", 2000)] == 1249905
    # 区コード (14101 鶴見区) は master に無いので除外される
    assert all(r["municipality_code"] not in ("14101", "14102") for r in rows)
    # 全行 2000/2005/2010 のみ
    assert {r["year"] for r in rows} <= {2000, 2005, 2010}


@pytest.mark.skipif(not _KANAGAWA_XLSX.exists(), reason="da0614.xlsx 未配置")
def test_parse_kanagawa_excludes_unlisted_codes() -> None:
    """master に無いコードは出力されない。"""
    rows = parse_xlsx(_KANAGAWA_XLSX, master_codes={"14100"}, years=(2000, 2005, 2010))
    assert {r["municipality_code"] for r in rows} == {"14100"}
    assert len(rows) == 3  # 3 年分
