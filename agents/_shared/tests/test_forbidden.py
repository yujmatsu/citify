"""agents._shared.forbidden の回帰テスト (W4 対策)。

FORBIDDEN_PATTERNS (賛否・投票) と find_political_leak (政党名・氏名+役職) の
カバレッジを固定し、translator/relevance/concierge/watcher へ配線した検出が
将来 drift しても気付けるようにする。
"""

from __future__ import annotations

from agents._shared.forbidden import (
    find_forbidden_matches,
    find_political_leak,
)


class TestForbiddenPatterns:
    def test_voting_recommendation_flagged(self) -> None:
        assert find_forbidden_matches("この候補に投票を推奨します")

    def test_absolute_stance_flagged(self) -> None:
        assert find_forbidden_matches("この議案には絶対に賛成すべきだ")

    def test_neutral_text_clean(self) -> None:
        assert find_forbidden_matches("待機児童対策の予算が議論されました") == []


class TestPoliticalLeak:
    def test_party_name_flagged(self) -> None:
        assert find_political_leak("立憲民主党が反対した") == "立憲民主党"

    def test_person_plus_role_flagged(self) -> None:
        # 「氏名2-4字 + 役職」= 高確度。個人名+役職を捕捉。
        assert find_political_leak("石破総理が答弁した") is not None

    def test_role_only_not_flagged(self) -> None:
        # 役職名そのもの (総理大臣) は leak ではない (§5「役職表現は可」)。
        assert find_political_leak("総理大臣が所信表明を行った") is None

    def test_neutral_text_clean(self) -> None:
        assert find_political_leak("市の子育て支援計画が更新されました") is None

    def test_honorific_pattern_toggle(self) -> None:
        # include_honorific=False だと「議員さん」等の敬称は無視 (watcher の
        # 全体破棄ゲートで誤検知を避けるため)。
        text = "田中さんが発言した"
        assert find_political_leak(text, include_honorific=True) is not None
        assert find_political_leak(text, include_honorific=False) is None

    def test_party_still_caught_in_strict_mode(self) -> None:
        # honorific を切っても政党名は高精度サブセットなので必ず捕捉。
        assert find_political_leak("公明党の主張", include_honorific=False) == "公明党"
