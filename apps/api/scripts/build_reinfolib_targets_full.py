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

# N03 公式最新: 令和5年(2023)1月1日基準、約 427MB、全国市区町村ポリゴン
# (2024 年版は本記述時点で公式 N03 リストに未掲載のため 2023 年版を採用)
N03_URL = "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2023/N03-20230101_GML.zip"


_PARENT_SUFFIXES = ("100", "130", "140", "150")


def _classify_method(code: str, all_codes: set[str]) -> tuple[str, str, str]:
    """自治体コードから (method, param, kind) を判定。

    - XX000 → ("area", "XX", "都道府県")
    - XX100/XX130/XX140/XX150 → 子区範囲を厳密判定 ("city_sum", "XXNNN-XXMMM", "政令市")
        同 prefecture 内の次の政令市親 suffix を upper bound とし、
        suffix が int で (parent_suffix, upper) の範囲にあるコードを子区とする。
        例: 14100 横浜市 → 次の親 14130 → 子区 14101..14129 (実在は 14101-14118)
            14130 川崎市 → 次の親 14150 → 子区 14131..14149 (実在は 14131-14137)
            14150 相模原市 → 次の親なし → 子区 14151..14199 (実在は 14151-14153)
            01100 札幌市 → 次の親なし → 子区 01101..01199 (実在は 01101-01110)
            27100 大阪市 → 次の親 27140 → 子区 27101..27139 (実在は 27102-27128)
    - その他 5 桁 → ("city", "XXXXX", "中核市/特別区/市町村")
    """
    suffix = code[2:]
    if suffix == "000":
        return "area", code[:2], "都道府県"
    if suffix in _PARENT_SUFFIXES:
        parent_int = int(suffix)
        prefix2 = code[:2]
        # 同 prefecture 内の次の政令市親 suffix を upper bound に
        same_pref_parents = sorted(
            int(c[2:])
            for c in all_codes
            if c.startswith(prefix2) and c[2:] in _PARENT_SUFFIXES and int(c[2:]) > parent_int
        )
        upper = same_pref_parents[0] if same_pref_parents else 200
        # 子区 = 同 prefecture、suffix が int で parent_int < x < upper
        children = sorted(
            c
            for c in all_codes
            if c != code
            and c.startswith(prefix2)
            and len(c) == 5
            and c[2:].isdigit()
            and parent_int < int(c[2:]) < upper
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


def _looks_japanese(s: str) -> bool:
    """文字列に日本語 (ひらがな/カタカナ/漢字) が含まれていれば True。"""
    return any("぀" <= ch <= "鿿" or "゠" <= ch <= "ヿ" for ch in s)


def _detect_code_column(gdf: object) -> str:
    """市区町村コード列 (5 桁) を自動検出。

    N03 の仕様変更に対応:
      - 旧版: N03_007 (全国地方公共団体コード)
      - 新版: N03_005 (デジタル庁推奨)
    """
    candidates = ["N03_007", "N03_005", "N03_004"]
    for col in candidates:
        if col not in gdf.columns:  # type: ignore[attr-defined]
            continue
        sample = gdf[col].dropna().iloc[0] if len(gdf) > 0 else None  # type: ignore[index]
        if sample is None:
            continue
        s = str(sample).strip()
        if s.isdigit() and len(s) == 5:
            logger.info("code_column=%s (sample=%r)", col, s)
            return col
    raise RuntimeError(
        f"市区町村コード列 (5 桁) が見つからない。columns={list(gdf.columns)}"  # type: ignore[attr-defined]
    )


def calc_centroids(shp_path: Path) -> dict[str, tuple[float, float, str, str]]:
    """N03 Shapefile を読んで {code: (lat, lng, pref, name)} dict を返す。

    encoding は UTF-8 → shift_jis → cp932 の順に試行して日本語が読める方を採用。
    code column は N03_007 / N03_005 / N03_004 を自動検出 (仕様変更対応)。
    """
    import geopandas as gpd  # 重い依存なので関数内 import

    gdf = None
    for enc in ("utf-8", "shift_jis", "cp932"):
        try:
            candidate = gpd.read_file(shp_path, encoding=enc)
            sample_pref = ""
            if "N03_001" in candidate.columns and len(candidate) > 0:
                sample_pref = str(candidate["N03_001"].dropna().iloc[0])
            if _looks_japanese(sample_pref):
                logger.info("encoding=%s OK (sample pref=%r)", enc, sample_pref)
                gdf = candidate
                break
            logger.warning("encoding=%s but garbled: %r", enc, sample_pref[:30])
        except Exception as exc:  # noqa: BLE001
            logger.warning("encoding=%s failed: %s", enc, exc)
    if gdf is None:
        raise RuntimeError("encoding 自動検出失敗 (utf-8/shift_jis/cp932 全部 NG)")

    logger.info("features=%d, columns=%s", len(gdf), gdf.columns.tolist())
    code_col = _detect_code_column(gdf)

    gdf = gdf.set_crs("EPSG:4326") if gdf.crs is None else gdf.to_crs("EPSG:4326")
    gdf["centroid"] = gdf.geometry.centroid
    gdf["lat"] = gdf["centroid"].y
    gdf["lng"] = gdf["centroid"].x
    gdf["area_m2"] = gdf.geometry.to_crs("EPSG:6933").area
    # 飛地等で複数ポリゴンの場合、最大面積のものを採用
    gdf = gdf.sort_values("area_m2", ascending=False).drop_duplicates(subset=code_col, keep="first")

    out: dict[str, tuple[float, float, str, str]] = {}
    for _, row in gdf.iterrows():
        code = str(row.get(code_col) or "").strip().zfill(5)
        if not code or code == "00000" or not code.isdigit():
            continue
        pref = str(row.get("N03_001") or "")
        # 市区町村名は N03_004、なければ N03_003 (郡・政令市名) を fallback
        name = (
            str(row.get("N03_004") or "")
            or str(row.get("N03_003") or "")
            or str(row.get("N03_001") or "")  # 都道府県だけのレコード
        )
        out[code] = (float(row["lat"]), float(row["lng"]), pref, name)
    logger.info("centroids (市区町村): %d (unique codes)", len(out))
    return out


def _seirei_parent_code(child_code: str, master_codes: set[str]) -> str | None:
    """政令市の子区コード (例: 14132) から親コード (14130) を master_codes 内で探す。

    判定基準: 同 prefecture (XX) 内の親候補 (XX100/XX130/XX140/XX150) のうち、
    child suffix int が「親 suffix 以上で次の親 suffix 未満」の最大親を返す。

    例:
      14118 横浜市泉区 → 親候補 [14100, 14130, 14150] → 14100 < 118 < 130 で 14100
      14132 川崎市中原区 → 親候補 同上 → 14130 < 132 < 150 で 14130
      14152 相模原市中央区 → 親候補 同上 → 14150 < 152 で 14150
    """
    if len(child_code) != 5 or not child_code[2:].isdigit():
        return None
    child_int = int(child_code[2:])
    if child_int < 100:
        return None
    prefix2 = child_code[:2]
    parents_int = sorted(
        int(c[2:]) for c in master_codes if c.startswith(prefix2) and c[2:] in _PARENT_SUFFIXES
    )
    # 親候補は降順、child_int 以下の最大を採用
    best = None
    for p in parents_int:
        if p < child_int:
            best = p
        else:
            break
    if best is None:
        return None
    return f"{prefix2}{best:03d}"


def expand_centroids(
    centroids: dict[str, tuple[float, float, str, str]],
    master_codes: set[str],
    master_names: dict[str, str],
) -> dict[str, tuple[float, float, str, str]]:
    """市区町村 centroids に都道府県 (XX000) と政令市親 (XX100 等) を派生追加。

    N03 は市区町村ポリゴンしか含まないため、都道府県・政令市親の centroid は
    子市町村 / 子区の centroid 平均で合成する。
    """
    from collections import defaultdict

    expanded = dict(centroids)

    # 1. 都道府県 (XX000) — 子市町村 centroid の平均
    pref_groups: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    for code, (lat, lng, pref, _) in centroids.items():
        pref_code = code[:2] + "000"
        pref_groups[pref_code].append((lat, lng, pref))

    added_pref = 0
    for pref_code, items in pref_groups.items():
        if pref_code in expanded or not items:
            continue
        avg_lat = sum(it[0] for it in items) / len(items)
        avg_lng = sum(it[1] for it in items) / len(items)
        pref_name = master_names.get(pref_code, items[0][2] or pref_code)
        expanded[pref_code] = (avg_lat, avg_lng, items[0][2], pref_name)
        added_pref += 1
    logger.info("expanded prefectures: +%d", added_pref)

    # 2. 政令市親 (XX100/130/140/150) — 子区 centroid の平均
    # 子区 → 親 mapping は master.csv 内の親候補から「次の親未満」で判定
    seirei_children: dict[str, list[tuple[float, float, str]]] = defaultdict(list)
    for code, (lat, lng, pref, _) in centroids.items():
        if code[2:] in _PARENT_SUFFIXES:
            continue  # 親自身は除外
        parent = _seirei_parent_code(code, master_codes)
        if parent and parent != code:
            seirei_children[parent].append((lat, lng, pref))

    added_seirei = 0
    for parent_code, items in seirei_children.items():
        if parent_code in expanded or not items:
            continue
        avg_lat = sum(it[0] for it in items) / len(items)
        avg_lng = sum(it[1] for it in items) / len(items)
        name = master_names.get(parent_code, f"自治体{parent_code}")
        expanded[parent_code] = (avg_lat, avg_lng, items[0][2], name)
        added_seirei += 1
    logger.info(
        "expanded seirei parents: +%d (例: %s)", added_seirei, sorted(seirei_children.keys())[:5]
    )

    return expanded


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

    # master.csv の name 上書き用に dict 化
    master_names: dict[str, str] = {}
    with args.master.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = (row.get("municipality_code") or "").strip().zfill(5)
            name = (row.get("name") or "").strip()
            if code and name:
                master_names[code] = name

    shp_path = download_n03(args.n03_url, args.work_dir)
    centroids = calc_centroids(shp_path)

    # 都道府県 + 政令市親を子市町村 centroid 平均から合成
    centroids = expand_centroids(centroids, master_codes, master_names)
    logger.info("centroids (expanded): %d (市区町村 + 都道府県 + 政令市親)", len(centroids))

    # centroids にあるコードはすべて採用 (N03 が source of truth)
    # master.csv にあれば name を上書き (整合性、市川市/船橋市問題のような乖離を防ぐ)
    targets: list[dict[str, str]] = []
    only_n03 = sorted(
        set(centroids.keys()) - master_codes - {c for c in centroids if c.endswith("000")}
    )
    if only_n03:
        logger.info(
            "centroids にあって master にない code: %d 件 (例: %s)", len(only_n03), only_n03[:5]
        )

    for code in sorted(centroids.keys()):
        if code == "00000":
            continue
        lat, lng, pref, name_n03 = centroids[code]
        # name は master.csv 優先、なければ N03 由来
        name = master_names.get(code, name_n03)
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
