"""Concierge Agent: 街診断 Migration Concierge (Plan E)。

ユーザーの自己紹介 (年代 + 関心軸 + 制約) から、合う自治体 TOP5 を提案し、
比較 / 詳細議題 を対話的に提示する ADK Agent。

設計:
    - Plan C の ADKTranslatorAgent / ADKRelevanceAgent を sub-agent として活用
    - 既存 BQ municipality_stats + scored_speeches_latest を tool 経由で参照
    - 倫理ガードレールは agents._shared.forbidden の FORBIDDEN_PATTERNS で集約
"""
