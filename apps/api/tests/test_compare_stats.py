"""compare-stats レーダー用ロジックの unit test (TASK-FISCAL)。

_percentile_score (純関数) を検証。BQ I/O は対象外。
"""

from __future__ import annotations

from apps.api.main import _median, _percentile_score


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


def test_median_odd_even_empty() -> None:
    # TASK-CITYDATA: 全国中央値 (レーダー併記)
    assert _median([1.0, 2.0, 3.0]) == 2.0
    assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5
    assert _median([]) is None
