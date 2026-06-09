"""移住支援金マッチング純関数の test (TASK-SUPPORT P1)。"""

from __future__ import annotations

from agents.watcher.support import (
    _home_category,
    load_support_seed,
    match_national_support,
)

# 参加自治体 seed (テスト用): 福岡市40130 が対象
_SEED = {"40130": {"official_url": "https://example.jp/", "note": "test"}}


def test_home_category() -> None:
    assert _home_category("13104") == "tokyo23"  # 新宿区(23区)
    assert _home_category("13201") == "tokyo_area"  # 八王子(東京都だが23区外)
    assert _home_category("14100") == "tokyo_area"  # 横浜(神奈川=東京圏)
    assert _home_category("27100") == "other"  # 大阪(東京圏外)


def test_match_tokyo23_family_likely() -> None:
    n = match_national_support("13104", "40130", "family_kids", _SEED)
    assert n.eligibility == "likely"
    assert n.amount_man == 100  # 世帯
    assert n.child_addition is True
    assert n.official_url == "https://example.jp/"
    assert n.requirements  # 就業要件を併記


def test_match_tokyo23_single_60() -> None:
    n = match_national_support("13104", "40130", "single", _SEED)
    assert n.eligibility == "likely"
    assert n.amount_man == 60


def test_match_tokyo_area_conditional() -> None:
    # 東京圏(横浜)在住 → 23区通勤要件で conditional
    n = match_national_support("14100", "40130", "couple", _SEED)
    assert n.eligibility == "conditional"
    assert n.amount_man == 100


def test_match_home_outside_tokyo_unlikely() -> None:
    # 現住所が東京圏外(大阪) → 対象外の可能性
    n = match_national_support("27100", "40130", "single", _SEED)
    assert n.eligibility == "unlikely"
    assert n.amount_man is None


def test_match_target_not_participating_unlikely() -> None:
    # 移住先が参加自治体でない(小田原=東京圏でそもそも対象地域外)
    n = match_national_support("13104", "14206", "family_kids", _SEED)
    assert n.eligibility == "unlikely"
    assert n.amount_man is None
    assert n.child_addition is True  # 世帯情報は保持


def test_match_household_unknown_amount_none() -> None:
    n = match_national_support("13104", "40130", "", _SEED)
    assert n.eligibility == "likely"
    assert n.amount_man is None  # 世帯構成未設定 → 額は範囲表示に委ねる


def test_load_support_seed_real_csv() -> None:
    seed = load_support_seed()
    assert "40130" in seed  # 福岡市は seed に含まれる
    assert seed["40130"]["official_url"]


def test_parse_local_lines() -> None:
    from agents.watcher.support import _parse_local_lines

    text = (
        "- 子育て応援金｜第2子以降に給付\n"
        "移住支援金｜東京圏からの移住で給付\n"
        "雑談行(区切りなし)\n"
        "必ず投票に行こう｜禁止語を含む行\n"  # 倫理スキャンで除去
    )
    out = _parse_local_lines(text, ["https://example.jp/iju"])
    names = [x.name for x in out]
    assert "子育て応援金" in names
    assert "移住支援金" in names
    assert all("投票" not in x.name for x in out)  # 禁止語行は除去
    assert out[0].official_url == "https://example.jp/iju"  # 出典付与


def test_parse_local_lines_empty() -> None:
    from agents.watcher.support import _parse_local_lines

    assert _parse_local_lines("", []) == []
    assert _parse_local_lines("区切りのない普通の文章です", []) == []
