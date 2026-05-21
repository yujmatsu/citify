"""配信 Agent (A-7): For You フィード生成 + 優先度ソート + 多様性確保。

A-5 翻訳 + A-6 影響度スコアの結果を集約して、ユーザー別の最終 feed を生成する。

設計方針 (LLM 不要のランキングロジック):
    1. Filter: relevance_score < 50 を除外 (FEATURES.md A-6 仕様)
    2. Greedy MMR: 関連性 × 多様性ペナルティ × 新鮮さブースト で feed_size 件を順次選択
    3. 各 item に display_reason (なぜ表示するか) を付与
"""

from .main import DistributorAgent
from .schema import FeedCandidate, FeedItem

__all__ = ["DistributorAgent", "FeedCandidate", "FeedItem"]
