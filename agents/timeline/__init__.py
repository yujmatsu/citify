"""Timeline Agent (Plan N): theme + 自治体 + 期間で議論変遷を物語化。

候補 speeches を BQ から取得し、TimelineAgent が 5-10 個の重要イベントに圧縮 + ナラティブ生成。
ハッカソン審査基準②「ストーリー性」を強化、Plan E Concierge / Plan X Heatmap と並ぶ独立 Agent。
"""

from .main import POLITICAL_PERSON_PATTERNS, TimelineAgent
from .schema import (
    CandidateSpeech,
    TimelineEvent,
    TimelineNarrative,
    TimelineRequest,
)

__all__ = [
    "POLITICAL_PERSON_PATTERNS",
    "CandidateSpeech",
    "TimelineAgent",
    "TimelineEvent",
    "TimelineNarrative",
    "TimelineRequest",
]
