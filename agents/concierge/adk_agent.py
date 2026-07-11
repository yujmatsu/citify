"""ADKConciergeAgent: ConciergeAgent の ADK 親 Agent ラッパー (Plan E)。

位置づけ (重要):
    本番の /v1/concierge は agents/concierge/runner.py の GenaiConciergeRunner
    (google.genai function-calling) が実行体であり、**この ADK 親子構成は本番経路では
    使われない**。本ファイルは ADK の親子階層 (sub_agents に translator/relevance を
    従える構成) を実際に組んで動かせることを示す成果物で、demo_adk_chain.py から
    単体実行できる。誇張を避けるため「審査対応のためだけの飾り」ではなく、独立して
    実行可能な ADK 構成として保持している。

設計:
    - tools=[search_municipalities, compare_municipalities, fetch_city_dashboard,
             fetch_city_speeches] (4 つの BQ tool)
    - sub_agents=[ADKTranslatorAgent.as_agent(), ADKRelevanceAgent.as_agent()]
    - ADK は lazy import (Plan C と同じパターン)
    - Runner は同梱せず、外部 (demo / 実験) で必要に応じて構築
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agents.relevance.adk_agent import ADKRelevanceAgent
from agents.translator.adk_agent import ADKTranslatorAgent

from . import tools as concierge_tools
from .prompts.system import SYSTEM_PROMPT

if TYPE_CHECKING:
    from google.adk import Agent
    from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

ADK_AGENT_DESCRIPTION = (
    "Citify の街診断 Migration Concierge Agent。ユーザーの自己紹介から、合う自治体 TOP5 を "
    "BQ 統計 + 議事録/RSS を tool として叩いて提案する。"
    "必要に応じて translator / relevance sub-agent も呼ぶマルチエージェント親 Agent。"
)


class ADKConciergeAgent:
    """ConciergeAgent の ADK Agent ラッパー。

    Args:
        project_id: GCP project ID (sub-agents Translator/Relevance に伝播)
        model: Gemini モデル名
        translator: テスト用 mock 注入 (ADKTranslatorAgent)
        relevance: テスト用 mock 注入 (ADKRelevanceAgent)
    """

    def __init__(
        self,
        project_id: str | None = None,
        model: str = "gemini-2.5-flash",
        translator: ADKTranslatorAgent | None = None,
        relevance: ADKRelevanceAgent | None = None,
    ) -> None:
        self.project_id = project_id
        self.model = model
        self._translator = translator or ADKTranslatorAgent(project_id=project_id)
        self._relevance = relevance or ADKRelevanceAgent(project_id=project_id)

    @property
    def translator(self) -> ADKTranslatorAgent:
        """sub-agent への直接アクセス (debug 用)。"""
        return self._translator

    @property
    def relevance(self) -> ADKRelevanceAgent:
        """sub-agent への直接アクセス (debug 用)。"""
        return self._relevance

    def _build_function_tools(self) -> list[FunctionTool]:
        """4 つの Concierge tool を ADK FunctionTool に wrap。"""
        from google.adk.tools import FunctionTool

        return [
            FunctionTool(func=concierge_tools.search_municipalities),
            FunctionTool(func=concierge_tools.compare_municipalities),
            FunctionTool(func=concierge_tools.fetch_city_dashboard),
            FunctionTool(func=concierge_tools.fetch_city_speeches),
        ]

    def as_agent(self, name: str = "concierge") -> Agent:
        """ADK Agent オブジェクトを返す (Runner で実行可能、本番 endpoint の主役)。

        構成:
            - tools: 4 つの BQ function tool
            - sub_agents: [translator agent, relevance agent] (親子階層)

        Args:
            name: Agent 名 (Runner ログ用)

        Returns:
            `google.adk.Agent` (tools + sub_agents 構成済)
        """
        from google.adk import Agent

        function_tools = self._build_function_tools()
        sub_agents = [
            self._translator.as_agent(name="translator"),
            self._relevance.as_agent(name="relevance"),
        ]

        return Agent(
            name=name,
            description=ADK_AGENT_DESCRIPTION,
            model=self.model,
            instruction=SYSTEM_PROMPT,
            tools=function_tools,
            sub_agents=sub_agents,
        )

    def as_tools(self) -> list[FunctionTool]:
        """Concierge の 4 つの function tool を返す (sub-agent としては使わない)。

        外部 (例: 上位 Orchestrator Agent) が Concierge を tool として使いたい時の
        ためのインターフェース。現バージョンでは未使用だが、将来の拡張用に保持。
        """
        return self._build_function_tools()

    def build_runner_kwargs(self) -> dict[str, Any]:
        """Concierge ADK Runner を構築するための kwargs を返す。

        FastAPI endpoint (Phase 3) から:
            >>> kwargs = adk_concierge.build_runner_kwargs()
            >>> from google.adk import Runner
            >>> runner = Runner(**kwargs)
            >>> result = runner.run(...)

        の形で使用する。本ファイル内では Runner を import しない (lazy)。
        """
        return {
            "agent": self.as_agent(),
        }
