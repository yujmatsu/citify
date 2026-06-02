"""XKT013 将来推計人口 250m メッシュ集計の test (TASK-POPTREND)。

aggregate_population_series が SHICODE で自治体を絞り込み、各 PT00_YYYY 年次を
正しく合算することを fixture で検証 (50km box 全合算バグの回帰防止)。
"""

from __future__ import annotations

from scrapers.reinfolib.parsers.xkt013 import aggregate_population_series


def _mesh(shicode: str, **year_pop: int) -> dict:
    """1 メッシュ feature を生成。year_pop は {"y2025": 100, ...} 形式 (キーは後で PT00_ に変換)。"""
    props: dict = {"SHICODE": shicode}
    for k, v in year_pop.items():
        year = k.lstrip("y")
        props[f"PT00_{year}"] = v
    return {"type": "Feature", "properties": props}


# ============================================================================
# 1) SHICODE フィルタ: 対象自治体のメッシュだけ合算 (50km box バグ解消の核心)
# ============================================================================


def test_aggregates_only_target_shicode() -> None:
    features = [
        _mesh("13104", y2025=100, y2050=80),  # 新宿区 (対象)
        _mesh("13104", y2025=150, y2050=120),  # 新宿区 (対象)
        _mesh("13101", y2025=9999, y2050=9999),  # 千代田区 (box内だが対象外 → 除外)
        _mesh("13103", y2025=8888, y2050=8888),  # 港区 (対象外 → 除外)
    ]
    series = aggregate_population_series(features, "13104")
    assert series == {2025: 250, 2050: 200}  # 千代田/港は混入しない


# ============================================================================
# 2) 多年次の動的検出 (PT00_2020..2070 が何年あっても集計)
# ============================================================================


def test_detects_arbitrary_years_dynamically() -> None:
    features = [
        _mesh("21203", y2020=500, y2025=480, y2030=450, y2050=380, y2070=300),
    ]
    series = aggregate_population_series(features, "21203")
    assert series == {2020: 500, 2025: 480, 2030: 450, 2050: 380, 2070: 300}
    assert list(series.keys()) == sorted(series.keys())  # 年昇順


# ============================================================================
# 3) 北海道 01xxx の SHICODE ゼロ埋め正規化 (先頭ゼロ落ち対策)
# ============================================================================


def test_normalizes_shicode_zero_padding() -> None:
    # API が SHICODE を int 由来の "1100" / "1100.0" で返しても "01100" と一致させる
    features = [
        {"type": "Feature", "properties": {"SHICODE": 1100, "PT00_2025": 200}},
        {"type": "Feature", "properties": {"SHICODE": "1100.0", "PT00_2025": 300}},
    ]
    series = aggregate_population_series(features, "01100")  # 札幌市
    assert series == {2025: 500}


# ============================================================================
# 4) 秘匿フラグ HITOKU{year}=1 のメッシュは当該年で除外
# ============================================================================


def test_excludes_hitoku_meshes_per_year() -> None:
    features = [
        {
            "type": "Feature",
            "properties": {
                "SHICODE": "13104",
                "PT00_2025": 100,
                "PT00_2050": 80,
                "HITOKU2050": 1,  # 2050 のみ秘匿
            },
        },
        {"type": "Feature", "properties": {"SHICODE": "13104", "PT00_2025": 50, "PT00_2050": 40}},
    ]
    series = aggregate_population_series(features, "13104")
    # 2025 は両方加算 (150)、2050 は秘匿メッシュを除外 (40 のみ)
    assert series == {2025: 150, 2050: 40}


# ============================================================================
# 4b) 政令市: 区コード集合を渡して合算 (Phase 0 検証: メッシュ SHICODE は区コード)
# ============================================================================


def test_aggregates_政令市_by_ward_codes() -> None:
    # 札幌市 (01100) は親コードのメッシュが無く、区 01101-01110 を束ねる
    features = [
        _mesh("01101", y2025=100),  # 中央区
        _mesh("01102", y2025=200),  # 北区
        _mesh("01103", y2025=150),  # 東区
        _mesh("01217", y2025=9999),  # 江別市 (隣接、対象外)
    ]
    wards = {f"011{n:02d}" for n in range(1, 11)}  # 01101..01110
    series = aggregate_population_series(features, wards)
    assert series == {2025: 450}  # 江別市は除外


# ============================================================================
# 5) 対象 SHICODE が無ければ空 dict (カバレッジ不足の検知材料)
# ============================================================================


def test_returns_empty_when_no_matching_shicode() -> None:
    features = [_mesh("13101", y2025=100), _mesh("13103", y2025=200)]
    assert aggregate_population_series(features, "13104") == {}


# ============================================================================
# 6) 不正値・欠損プロパティは graceful に skip
# ============================================================================


def test_graceful_on_malformed_values() -> None:
    features = [
        _mesh("13104", y2025=100),
        {"type": "Feature", "properties": {"SHICODE": "13104", "PT00_2025": "N/A"}},  # 非数値
        {"type": "Feature", "properties": {}},  # SHICODE 欠損
        {},  # properties 欠損
        None,  # feature が None
    ]
    series = aggregate_population_series(features, "13104")
    assert series == {2025: 100}  # 有効な 1 件のみ
