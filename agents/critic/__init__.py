"""Critic Agent: 翻訳品質を 4 軸 (faithfulness/simplicity/tone/ethics) で評価。

Plan D で独立 Agent として切り出し:
    - TranslatorAgent.translate_with_critique() から DI で受け取り
    - 翻訳品質を自己批評し再翻訳判断に使う
    - 将来 ADK 化や別 LLM (e.g. Pro vs Flash) 切替可能な構造
"""

from .main import CriticAgent
from .schema import CriticScores, CritiqueResult

__all__ = ["CriticAgent", "CriticScores", "CritiqueResult"]
