"""compare-stats レーダー用ロジックの unit test (TASK-FISCAL)。

_percentile_score (純関数) を検証。BQ I/O は対象外。
"""

from __future__ import annotations

from apps.api.main import _median, _percentile_score, _rank


def test_percentile_higher_is_better() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    # 最大値は 100、最小値は 20 (rank/n)
    assert _percentile_score(5.0, vals, "higher") == 100.0
    assert _percentile_score(3.0, vals, "higher") == 60.0


def test_percentile_lower_is_better_inverts() -> None:
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    # 低い元値ほど高 score (外側=良い)。元値1.0 → percentile20 → 反転80
    assert _percentile_score(1.0, vals, "lower") == 80.0
    assert _percentile_score(5.0, vals, "lower") == 0.0


def test_percentile_none_and_empty() -> None:
    assert _percentile_score(None, [1.0, 2.0], "higher") is None
    assert _percentile_score(3.0, [], "higher") is None


def test_rank_higher_lower_ties_empty() -> None:
    # TASK-CITYDATA: 全国順位 (1位=最良)
    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert _rank(5.0, vals, "higher") == {"rank": 1, "total": 5}  # 最大=1位
    assert _rank(1.0, vals, "higher") == {"rank": 5, "total": 5}
    assert _rank(1.0, vals, "lower") == {"rank": 1, "total": 5}  # 最小=1位
    assert _rank(5.0, vals, "lower") == {"rank": 5, "total": 5}
    # タイは上位側に揃える (3.0 が2つ → higher で2位)
    assert _rank(3.0, [1.0, 3.0, 3.0, 5.0], "higher") == {"rank": 2, "total": 4}
    assert _rank(None, vals, "higher") is None
    assert _rank(3.0, [], "higher") is None


def test_median_odd_even_empty() -> None:
    # TASK-CITYDATA: 全国中央値 (レーダー併記)
    assert _median([1.0, 2.0, 3.0]) == 2.0
    assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert _median([]) is None
