"""DistributorAgent: 候補 speech 群を ranking して For You フィードを生成。

LLM 不要、純粋なアルゴリズムによる ranking + 多様性確保 (MMR 風 greedy)。

ロジック:
    1. relevance_score >= min_relevance で filter
    2. 各候補に freshness_boost (新鮮 +5 / 標準 0 / 古い -5) を加算
    3. Greedy 選択: 各 round で残り候補の中から
       「relevance + freshness - diversity_penalty」が最大のものを選ぶ
    4. diversity_penalty は「既選択 item と matched_interests / speaker_position が重複する度合い」
    5. feed_size 件埋まるか候補尽きるまで繰り返し
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date

from .schema import FeedCandidate, FeedItem

logger = logging.getLogger(__name__)

DEFAULT_MIN_RELEVANCE = 50
DEFAULT_FEED_SIZE = 20
DEFAULT_DIVERSITY_WEIGHT = 0.3  # 0.0 = 多様性無視、1.0 = 多様性最優先
DEFAULT_FRESHNESS_WINDOW_DAYS = 30  # この期間内 = 新鮮
DEFAULT_FRESHNESS_BOOST = 5
DEFAULT_OLD_THRESHOLD_DAYS = 90  # この期間超 = 古い (penalty)
DEFAULT_SPEAKER_REPETITION_PENALTY = (
    5.0  # 同役職連続のペナルティ (3 だと同点 tie が起きやすい、5 で確実に再順位化)
)


class DistributorAgent:
    """A-5/A-6 出力を集約して、ユーザー別 For You フィードを生成。

    Args:
        min_relevance: フィルタ閾値 (FEATURES.md A-6 仕様、default 50)
        feed_size: 1 ユーザーに返す item 数 (default 20)
        diversity_weight: 多様性ペナルティの強さ (0.0-1.0)
        freshness_window_days: この期間内の speech に boost
        freshness_boost: 新鮮さ加算スコア
        old_threshold_days: この期間超で penalty
        speaker_repetition_penalty: 同 speaker_position 重複ペナルティ
        today: 基準日 (テスト用、default は実行日)
    """

    def __init__(
        self,
        min_relevance: int = DEFAULT_MIN_RELEVANCE,
        feed_size: int = DEFAULT_FEED_SIZE,
        diversity_weight: float = DEFAULT_DIVERSITY_WEIGHT,
        freshness_window_days: int = DEFAULT_FRESHNESS_WINDOW_DAYS,
        freshness_boost: int = DEFAULT_FRESHNESS_BOOST,
        old_threshold_days: int = DEFAULT_OLD_THRESHOLD_DAYS,
        speaker_repetition_penalty: float = DEFAULT_SPEAKER_REPETITION_PENALTY,
        today: date | None = None,
    ) -> None:
        if not 0.0 <= diversity_weight <= 1.0:
            raise ValueError(f"diversity_weight must be 0.0-1.0, got {diversity_weight}")
        self.min_relevance = min_relevance
        self.feed_size = feed_size
        self.diversity_weight = diversity_weight
        self.freshness_window_days = freshness_window_days
        self.freshness_boost = freshness_boost
        self.old_threshold_days = old_threshold_days
        self.speaker_repetition_penalty = speaker_repetition_penalty
        self._today = today  # None なら generate_feed 時に date.today()

    def generate_feed(self, candidates: list[FeedCandidate]) -> list[FeedItem]:
        """候補から feed_size 件を選んで順位付きで返す。

        Returns:
            list[FeedItem] (final_rank で昇順、最大 feed_size 件)
        """
        # 1. Filter
        pool = [c for c in candidates if c.relevance_score >= self.min_relevance]
        if not pool:
            logger.info(
                "distributor.empty_feed n_candidates=%d min_relevance=%d",
                len(candidates),
                self.min_relevance,
            )
            return []

        today = self._today or date.today()

        # 2. Greedy MMR-style selection
        selected: list[FeedItem] = []
        seen_interests: Counter[str] = Counter()
        seen_speakers: Counter[str] = Counter()
        remaining = pool.copy()

        while remaining and len(selected) < self.feed_size:
            best: FeedCandidate | None = None
            best_score: float = float("-inf")
            best_freshness: int = 0
            best_penalty: float = 0.0

            for candidate in remaining:
                freshness = self._freshness_boost(candidate.meeting_date, today)
                penalty = self._diversity_penalty(candidate, seen_interests, seen_speakers)
                adjusted = candidate.relevance_score + freshness - penalty

                if adjusted > best_score:
                    best_score = adjusted
                    best = candidate
                    best_freshness = freshness
                    best_penalty = penalty

            if best is None:
                break  # 安全弁

            item = self._build_item(
                candidate=best,
                rank=len(selected) + 1,
                adjusted_score=best_score,
                freshness_boost=best_freshness,
                diversity_penalty=best_penalty,
            )
            selected.append(item)

            # tracking 更新
            for interest in best.matched_interests:
                seen_interests[interest] += 1
            if best.speaker_position:
                seen_speakers[best.speaker_position] += 1
            remaining.remove(best)

        logger.info(
            "distributor.feed_generated n_candidates=%d filtered=%d feed_size=%d",
            len(candidates),
            len(pool),
            len(selected),
        )
        return selected

    def _freshness_boost(self, meeting_date: date | None, today: date) -> int:
        """新鮮さに応じて +freshness_boost / 0 / -freshness_boost を返す。"""
        if meeting_date is None:
            return 0
        days_ago = (today - meeting_date).days
        if days_ago <= self.freshness_window_days:
            return self.freshness_boost
        if days_ago > self.old_threshold_days:
            return -self.freshness_boost
        return 0

    def _diversity_penalty(
        self,
        candidate: FeedCandidate,
        seen_interests: Counter[str],
        seen_speakers: Counter[str],
    ) -> float:
        """既選択 item との関心軸 / speaker 重複に基づくペナルティ。"""
        # 関心軸の重複ペナルティ: 既選択 item に同じ関心軸がある分だけ加算
        interest_overlap = sum(seen_interests[i] for i in candidate.matched_interests)
        interest_penalty = self.diversity_weight * interest_overlap * 5.0

        # speaker_position の重複ペナルティ
        speaker_penalty = 0.0
        if candidate.speaker_position and seen_speakers[candidate.speaker_position] > 0:
            speaker_penalty = (
                self.speaker_repetition_penalty * seen_speakers[candidate.speaker_position]
            )

        return interest_penalty + speaker_penalty

    def _build_item(
        self,
        *,
        candidate: FeedCandidate,
        rank: int,
        adjusted_score: float,
        freshness_boost: int,
        diversity_penalty: float,
    ) -> FeedItem:
        """FeedCandidate + ランキングメタ → FeedItem 構築。"""
        return FeedItem(
            speech_id=candidate.speech_id,
            title=candidate.title,
            summary=candidate.summary,
            tone=candidate.tone,
            relevance_score=candidate.relevance_score,
            matched_interests=candidate.matched_interests,
            reasoning=candidate.reasoning,
            speaker_position=candidate.speaker_position,
            municipality_code=candidate.municipality_code,
            meeting_date=candidate.meeting_date,
            meeting_url=candidate.meeting_url,
            name_of_meeting=candidate.name_of_meeting,
            final_rank=rank,
            adjusted_score=adjusted_score,
            display_reason=self._build_display_reason(candidate),
            diversity_penalty=diversity_penalty,
            freshness_boost=freshness_boost,
        )

    def _build_display_reason(self, candidate: FeedCandidate) -> str:
        """ユーザー向けに「なぜこれが表示されているか」を 1 行で。"""
        if candidate.matched_interests:
            interests = "・".join(candidate.matched_interests[:3])  # 最大 3 件
            return f"あなたの関心軸「{interests}」と合致 (関連度 {candidate.relevance_score})"
        return f"関連度 {candidate.relevance_score} 点"
