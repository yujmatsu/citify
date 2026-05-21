"""翻訳 Agent (A-5): 役所言葉 → 若者向け 3 行サマリ。

入力: 議事録の speech 1 件 + ペルソナの年代
出力: 平易タイトル (40 字) + 3 行サマリ (各 60 字) + トーン + 安全性 metadata

倫理ガードレール (PROJECT.md §5 準拠):
    - 政治家の固有名詞は役職で表現 ("石破総理" → "総理大臣")
    - 賛否判定はしない、事実のみ要約
    - 特定政党の推奨/批判はしない
    - 専門用語は () で補足
"""

from .main import TranslatorAgent
from .schema import TranslateInput, TranslatorOutput

__all__ = ["TranslateInput", "TranslatorAgent", "TranslatorOutput"]
