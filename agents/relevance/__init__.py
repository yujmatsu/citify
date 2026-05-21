"""影響度 Agent (A-6): ペルソナ × speech のマッチング + 0-100 スコアリング。

入力: speech + ユーザーペルソナ (年代, 関心軸, 登録自治体)
出力: 0-100 の relevance_score + 4 軸内訳 + matched_interests + 理由

スコアリング方針 (各 0-25 点、合計 0-100):
    1. トピック関連性: 発言テーマがペルソナの関心軸と合致するか
    2. 年代適合性: 発言内容がペルソナの年代に直接的か
    3. 地理関連性: 発言対象自治体が登録自治体と合致するか
    4. 緊急性: 直近の具体的施策 (高) vs 抽象的議論 (低)

50 点未満は FEATURES.md A-6 仕様によりフィード非表示。
"""

from .main import RelevanceAgent
from .schema import (
    AgeGroup,
    Interest,
    RelevanceInput,
    RelevanceOutput,
    UserPersona,
)

__all__ = [
    "AgeGroup",
    "Interest",
    "RelevanceAgent",
    "RelevanceInput",
    "RelevanceOutput",
    "UserPersona",
]
