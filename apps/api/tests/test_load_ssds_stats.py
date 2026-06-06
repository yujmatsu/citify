"""scripts/load_ssds_stats.py の unit test (TASK-FISCAL、BQ は対象外)。

CSV パース・型変換・欠損(空/"-")の None 化・zfill・ssds_loaded_at 付与を検証。
write_to_bq は BQ 依存のため対象外 (dry-run で別途確認)。
"""

from __future__ import annotations

import sys
from pathlib import Path

# pythonpath=["."] は repo root のため、apps/api を解決できるよう挿入。
_APPS_API_DIR = Path(__file__).resolve().parents[1]
if str(_APPS_API_DIR) not in sys.path:
    sys.path.insert(0, str(_APPS_API_DIR))

from scripts.load_ssds_stats import load_normalized_csv  # noqa: E402

_HEADER = (
    "municipality_code,financial_capability_index,real_debt_service_ratio_pct,"
    "taxable_income_per_capita_yen,homeownership_rate_pct,crime_rate_per_1000,"
    "ssds_data_year,ssds_source_url"
)


def _write(path: Path, rows: list[str]) -> None:
    path.write_text(_HEADER + "\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_parses_values_and_adds_loaded_at(tmp_path: Path) -> None:
    csv = tmp_path / "ssds.csv"
    _write(csv, ["11227,0.98,4.9,3947780,53.7,13.49,2025,https://e-stat.example/00200502"])
    rows = load_normalized_csv(csv)
    assert len(rows) == 1
    r = rows[0]
    assert r["municipality_code"] == "11227"
    assert r["financial_capability_index"] == 0.98
    assert r["real_debt_service_ratio_pct"] == 4.9
    assert r["taxable_income_per_capita_yen"] == 3947780
    assert r["homeownership_rate_pct"] == 53.7
    assert r["crime_rate_per_1000"] == 13.49
    assert r["ssds_data_year"] == 2025
    assert r["ssds_source_url"].startswith("https://")
    assert r["ssds_loaded_at"]  # 付与される


def test_missing_values_become_none(tmp_path: Path) -> None:
    """特別区など財政力指数が空、住調欠損で持ち家率が空 → None (既存値を壊さない MERGE 前提)。"""
    csv = tmp_path / "ssds.csv"
    _write(csv, ["13104,,-3.2,6205126,,31.01,2025,https://e-stat.example/00200502"])
    r = load_normalized_csv(csv)[0]
    assert r["financial_capability_index"] is None
    assert r["homeownership_rate_pct"] is None
    # マイナス値(実質公債費比率)は正しく保持
    assert r["real_debt_service_ratio_pct"] == -3.2


def test_zfill_and_skip_empty_code(tmp_path: Path) -> None:
    csv = tmp_path / "ssds.csv"
    _write(
        csv,
        [
            "1100,0.5,3.0,3000000,60.0,8.0,2025,u",  # 4桁 → zfill 01100
            ",0.1,1.0,1,1.0,1.0,2025,u",  # コード空 → skip
        ],
    )
    rows = load_normalized_csv(csv)
    assert len(rows) == 1
    assert rows[0]["municipality_code"] == "01100"
