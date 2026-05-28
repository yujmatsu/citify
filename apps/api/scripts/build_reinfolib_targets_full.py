"""Phase F v4 — 全 1794 自治体の Reinfolib targets を生成 (N03 centroid + master.csv マージ)。

国土数値情報 N03 (行政区域) Shapefile をダウンロードし、自治体ポリゴンの
重心 (centroid) を計算 → master.csv とマージ → method (area/city/city_sum)
を自動判定して `infra/seed/reinfolib_targets_full.csv` に出力。

使用方法:
    cd apps/api
    pip install geopandas pyogrio   # 初回のみ
    .venv/bin/python -m scripts.build_reinfolib_targets_full \\
        --output ../../infra/seed/reinfolib_targets_full.csv

出力 CSV 列 (既存 reinfolib_targets.csv と互換):
    municipality_code, name, kind, xit001_method, xit001_param,
    center_lat, center_lng, notes
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

N03_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2024/N03-20240101_GML.zip"


def _classify_method(code: str, all_codes: set[str]) -> tuple[str, str, str]:
    """自治体コードから (method, param, kind) を判定。

    - XX000 → ("area", "XX", "都道府県")
    - XX100/XX130/XX140/XX150 → 子区を範囲指定 ("city_sum", "XXAAA-XXBBB", "政令市")
    - その他 5 桁 → ("city", "XXXXX", "中核市/特別区/市町村")
    """
    suffix = code[2:]
    if suffix == "000":
        return "area", code[:2], "都道府県"
    if suffix in ("100", "130", "140", "150"):
        prefix3 = code[:3]
        children = sorted(
            c
            for c in all_codes
            if c != code
            and c.startswith(prefix3)
            and c[2:] not in ("000", "100", "130", "140", "150")
        )
        if children:
            return "city_sum", f"{children[0]}-{children[-1]}", "政令市"
        return "city", code, "政令市親 (区なし)"
    if code.startswith("13") and "101" <= suffix <= "123":
        return "city", code, "特別区"
    return "city", code, "市町村"


def download_n03(url: str = N03_URL, work_dir: Path | None = None) -> Path:
    """N03 zip を DL → unzip → Shapefile のパスを返す。"""
    work_dir = work_dir or Path("/tmp/citify_n03")
    work_dir.mkdir(parents=True, exist_ok=True)
    zip_path = work_dir / "N03.zip"
    if not zip_path.exists():
        logger.info("downloading N03 from %s ...", url)
        urllib.request.urlretrieve(url, zip_path)
        logger.info("downloaded: %.1f MB", zip_path.stat().st_size / 1024 / 1024)
    extract_dir = work_dir / "extracted"
    if not extract_dir.exists():
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)
    shp_files = list(extract_dir.rglob("*.shp"))
    if not shp_files:
        raise FileNotFoundError(f"shp not found in {extract_dir}")
    logger.info("shp: %s", shp_files[0])
    return shp_files[0]


def calc_centroids(shp_path: Path) -> dict[str, tuple[float, float, str, str]]:
    """N03 Shapefile を読んで {code: (lat, lng, pref, name)} dict を返す。"""
    import geopandas as gpd  # 重い依存なので関数内 import

    gdf = gpd.read_file(shp_path, encoding="shift_jis")
    logger.info("features: %d, columns: %s", len(gdf), gdf.columns.tolist())

    gdf = gdf.set_crs("EPSG:4326") if gdf.crs is None else gdf.to_crs("EPSG:4326")
    gdf["centroid"] = gdf.geometry.centroid
    gdf["lat"] = gdf["centroid"].y
    gdf["lng"] = gdf["centroid"].x
    # 飛地等で複数ポリゴンの場合、最大面積のものを採用
    gdf["area_m2"] = gdf.geometry.to_crs("EPSG:6933").area
    gdf = gdf.sort_values("area_m2", ascending=False).drop_duplicates(
        subset="N03_007", keep="first"
    )

    out: dict[str, tuple[float, float, str, str]] = {}
    for _, row in gdf.iterrows():
        code = str(row.get("N03_007") or "").zfill(5)
        if not code or code == "00000":
            continue
        pref = str(row.get("N03_001") or "")
        name = str(row.get("N03_004") or "")
        out[code] = (float(row["lat"]), float(row["lng"]), pref, name)
    logger.info("centroids: %d", len(out))
    return out


def load_master_codes(master_csv: Path) -> set[str]:
    """master.csv の municipality_code 一覧を set で返す。"""
    codes: set[str] = set()
    with master_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("municipality_code") or "").strip().zfill(5)
            if code and code != "00000":
                codes.add(code)
    return codes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="N03 centroid + master.csv で reinfolib_targets_full.csv を生成"
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=Path("../../infra/seed/municipality_master.csv"),
        help="master.csv のパス (apps/api 起点で ../../infra/seed/...)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("../../infra/seed/reinfolib_targets_full.csv"),
    )
    parser.add_argument(
        "--n03-url",
        default=N03_URL,
        help="N03 ダウンロード URL (年度更新時に変更)",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("/tmp/citify_n03"),
        help="N03 zip / shp の作業ディレクトリ",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    if not args.master.exists():
        logger.error("master.csv not found: %s", args.master)
        return 1

    master_codes = load_master_codes(args.master)
    logger.info("master codes: %d", len(master_codes))

    shp_path = download_n03(args.n03_url, args.work_dir)
    centroids = calc_centroids(shp_path)

    targets: list[dict[str, str]] = []
    for code in sorted(master_codes | centroids.keys()):
        if code not in centroids:
            logger.debug("skip (no centroid): %s", code)
            continue
        if code not in master_codes and not code.endswith("000"):
            # master.csv にない & 都道府県でない場合 skip (master.csv が source of truth)
            logger.debug("skip (not in master): %s", code)
            continue
        lat, lng, pref, name = centroids[code]
        method, param, kind = _classify_method(code, centroids.keys())
        targets.append(
            {
                "municipality_code": code,
                "name": name,
                "kind": kind,
                "xit001_method": method,
                "xit001_param": param,
                "center_lat": f"{lat:.4f}",
                "center_lng": f"{lng:.4f}",
                "notes": pref,
            }
        )

    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "municipality_code",
                "name",
                "kind",
                "xit001_method",
                "xit001_param",
                "center_lat",
                "center_lng",
                "notes",
            ],
        )
        writer.writeheader()
        writer.writerows(targets)
    logger.info("wrote %d targets to %s", len(targets), args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
