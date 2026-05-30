"""scripts/load_reinfolib_stats.py の unit test (Phase F v4、BQ は対象外)。

CSV パース・複数ファイル結合・後勝ち dedup・municipality_code zfill を検証。
write_to_bq は BQ 依存のため対象外 (段階実行 + dry-run で別途確認)。
"""

from __future__ import annotations

import sys
from pathlib import Path

# root から (`pytest apps/api`) も apps/api から実行されても `scripts` を解決できるよう、
# apps/api ディレクトリを sys.path に挿入 (pythonpath=["."] は repo root のため)。
_APPS_API_DIR = Path(__file__).resolve().parents[1]
if str(_APPS_API_DIR) not in sys.path:
    sys.path.insert(0, str(_APPS_API_DIR))

from scripts.load_reinfolib_stats import load_normalized_csv, load_normalized_csvs  # noqa: E402

_HEADER = (
    "municipality_code,used_apartment_median_price_man_yen,used_apartment_sample_size,"
    "used_apartment_median_unit_price_yen,used_apartment_avg_building_age,"
    "emergency_shelter_count,emergency_shelter_official_link,"
    "population_2025_estimated,population_2050_estimated,population_change_2025_2050_pct,"
    "medical_facility_count,medical_hospital_count,medical_clinic_count,"
    "childcare_facility_count,kindergarten_count,nursery_count,"
    "reinfolib_loaded_at,reinfolib_source_url"
)


def _write_csv(path: Path, data_rows: list[str]) -> None:
    path.write_text(_HEADER + "\n" + "\n".join(data_rows) + "\n", encoding="utf-8")


# ============================================================================
# 1) 単一 CSV パース (型変換)
# ============================================================================


def test_load_single_csv_parses_types(tmp_path: Path) -> None:
    csv = tmp_path / "a.csv"
    _write_csv(
        csv,
        [
            '13104,5800,120,950000,18.5,300,"https://hz.example/13104",'
            "346000,300000,-13.3,500,40,300,80,20,60,"
            "2026-05-28T16:00:00+00:00,https://www.reinfolib.mlit.go.jp/",
        ],
    )
    rows = load_normalized_csv(csv)
    assert len(rows) == 1
    r = rows[0]
    assert r["municipality_code"] == "13104"
    assert r["used_apartment_median_price_man_yen"] == 5800  # int
    assert r["used_apartment_avg_building_age"] == 18.5  # float
    assert r["population_change_2025_2050_pct"] == -13.3
    assert r["emergency_shelter_official_link"] == "https://hz.example/13104"  # str
    assert r["medical_facility_count"] == 500


# ============================================================================
# 2) 空文字 / nan は None に
# ============================================================================


def test_load_csv_empty_and_nan_become_none(tmp_path: Path) -> None:
    csv = tmp_path / "b.csv"
    _write_csv(
        csv,
        [
            "08000,2400,518,314285,20.4,498,,1066013,881454,-17.31,157,12,80,,,,"
            "2026-05-28T16:27:57+00:00,https://www.reinfolib.mlit.go.jp/",
        ],
    )
    r = load_normalized_csv(csv)[0]
    # childcare/kindergarten/nursery は空 → None
    assert r["childcare_facility_count"] is None
    assert r["kindergarten_count"] is None
    assert r["nursery_count"] is None
    # 値ありは保持
    assert r["population_2025_estimated"] == 1066013


# ============================================================================
# 3) municipality_code を zfill(5)
# ============================================================================


def test_load_csv_zfills_municipality_code(tmp_path: Path) -> None:
    csv = tmp_path / "c.csv"
    _write_csv(
        csv,
        ["1100,2000,10,250000,15.0,50,,100,90,-10.0,10,1,5,,,,2026-05-28T00:00:00+00:00,https://x"],
    )
    r = load_normalized_csv(csv)[0]
    assert r["municipality_code"] == "01100"  # 4 桁 → 5 桁ゼロ埋め


# ============================================================================
# 4) 複数 CSV 結合
# ============================================================================


def test_load_multiple_csvs_concatenates(tmp_path: Path) -> None:
    a = tmp_path / "kanto.csv"
    b = tmp_path / "kinki.csv"
    _write_csv(a, ["13104,5800,120,950000,18.5,300,,346000,300000,-13.3,500,40,300,80,20,60,t,u"])
    _write_csv(b, ["27100,4200,90,720000,22.1,210,,270000,230000,-14.8,400,30,250,60,15,45,t,u"])
    rows = load_normalized_csvs([a, b])
    codes = {r["municipality_code"] for r in rows}
    assert codes == {"13104", "27100"}
    assert len(rows) == 2


# ============================================================================
# 5) 重複 municipality_code は後勝ち
# ============================================================================


def test_load_multiple_csvs_dedup_last_wins(tmp_path: Path) -> None:
    a = tmp_path / "first.csv"
    b = tmp_path / "second.csv"
    _write_csv(a, ["13104,1000,10,100000,10.0,100,,100,90,-10.0,10,1,5,,,,t,u"])
    _write_csv(b, ["13104,9999,99,999999,99.9,999,,999,888,-99.9,99,9,90,,,,t,u"])
    rows = load_normalized_csvs([a, b])
    assert len(rows) == 1  # 重複は 1 件に集約
    assert rows[0]["used_apartment_median_price_man_yen"] == 9999  # 後勝ち


# ============================================================================
# 6) 空 municipality_code 行は skip
# ============================================================================


def test_load_csv_skips_blank_code(tmp_path: Path) -> None:
    csv = tmp_path / "d.csv"
    _write_csv(
        csv,
        [
            "13104,5800,120,950000,18.5,300,,346000,300000,-13.3,500,40,300,80,20,60,t,u",
            ",,,,,,,,,,,,,,,,,",  # 全カラム空 → code 空 → skip
        ],
    )
    rows = load_normalized_csv(csv)
    assert len(rows) == 1
    assert rows[0]["municipality_code"] == "13104"
