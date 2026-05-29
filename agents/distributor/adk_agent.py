"""DistributorAgent の ADK (Agent Development Kit) wrapper (Plan C)。

既存 `DistributorAgent.generate_feed()` の core logic はそのまま保持し、
ADK の `Agent` / `FunctionTool` インターフェースに準拠した形で
他の Agent (E: Concierge 等) から subcall 可能にする薄い wrapper。

設計方針 (Translator/Relevance の adk_agent.py と並列):
    - 既存 27 tests への影響ゼロ (DistributorAgent は変更しない)
    - ADK は lazy import
    - Distributor は LLM 呼ばない (純粋アルゴリズム) ので as_agent は demo 用、
      production worker は引き続き既存 DistributorAgent を直接呼ぶ

使用例 (E: Concierge Agent から subcall):
    >>> from agents.distributor.adk_agent import ADKDistributorAgent
    >>> adk_distributor = ADKDistributorAgent()
    >>> tool = adk_distributor.as_tool()  # FunctionTool として渡す
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .main import DistributorAgent
from .schema import FeedCandidate, FeedItem, FeedSnapshot

if TYPE_CHECKING:
    from google.adk import Agent
    from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

ADK_AGENT_DESCRIPTION = (
    "候補 speech 群を ranking して For You フィードを生成する Agent。"
    "LLM は使わず、relevance_score + 新鮮さ boost + 多様性 penalty で "
    "最大 feed_size 件を greedy 選択する純粋アルゴリズム。"
)

ADK_AGENT_INSTRUCTION = (
    "ユーザー入力 (FeedCandidate のリスト) を `generate_feed` ツールに渡して "
    "ランキング結果 (FeedItem のリスト) を返してください。"
    "Tool は決定論的なアルゴリズムなので、追加判断不要で結果を素通しで OK。"
)


class ADKDistributorAgent:
    """DistributorAgent の ADK wrapper。

    Args:
        distributor: Dependency Injection 用 (テストで mock 注入可)
        **distributor_kwargs: DistributorAgent.__init__ に渡す追加 kwargs
                              (min_relevance / feed_size / diversity_weight 等)
    """

    def __init__(
        self,
        distributor: DistributorAgent | None = None,
        **distributor_kwargs: object,
    ) -> None:
        self._distributor = distributor or DistributorAgent(
            **distributor_kwargs,  # type: ignore[arg-type]
        )

    @property
    def distributor(self) -> DistributorAgent:
        """内部 DistributorAgent への直接アクセス (debug/inspection 用)。"""
        return self._distributor

    @property
    def feed_size(self) -> int:
        """内部 DistributorAgent の feed_size を transparent に公開。"""
        return self._distributor.feed_size

    def generate_feed(self, candidates: list[FeedCandidate]) -> list[FeedItem]:
        """候補から feed_size 件を ranking して返す。ADK FunctionTool として exposed。

        Args:
            candidates: 候補 speech 群 (FeedCandidate のリスト)

        Returns:
            ランキング済 FeedItem (final_rank 昇順、最大 feed_size 件)
        """
        return self._distributor.generate_feed(candidates)

    def as_tool(self) -> FunctionTool:
        """ADK FunctionTool として返す。他 Agent (Concierge 等) から subcall 用。

        Returns:
            `google.adk.tools.FunctionTool` (generate_feed をラップ)
        """
        from google.adk.tools import FunctionTool

        return FunctionTool(func=self.generate_feed)

    def as_agent(self, name: str = "distributor") -> Agent:
        """単独 ADK Agent として返す。Runner で直接実行可能、demo 用途。

        Note:
            Distributor は LLM 不要だが、ADK Agent の枠組みで他 Agent 階層に
            組み込む際に必要 (E: Concierge が distribute を tool として呼ぶ)。

        Args:
            name: Agent 名

        Returns:
            `google.adk.Agent` (generate_feed tool を持つ Agent)
        """
        from google.adk import Agent

        # output_schema は list[FeedItem] を直接表現できないので FeedSnapshot を使う
        # (FeedSnapshot は items + meta の wrapper、demo で利便性向上)
        return Agent(
            name=name,
            description=ADK_AGENT_DESCRIPTION,
            # LLM を使わないが、ADK の Agent 抽象を保つため gemini-2.5-flash を指定
            # (実際の処理は tool 側の generate_feed が決定論的に行う)
            model="gemini-2.5-flash",
            instruction=ADK_AGENT_INSTRUCTION,
            output_schema=FeedSnapshot,
            tools=[self.as_tool()],
        )
