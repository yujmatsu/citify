"""RelevanceAgent の ADK (Agent Development Kit) wrapper (Plan C)。

既存 `RelevanceAgent.score()` / `score_multi()` の core logic はそのまま保持し、
ADK の `Agent` / `FunctionTool` インターフェースに準拠した形で
他の Agent (E: Concierge 等) から subcall 可能にする薄い wrapper。

設計方針 (Translator の adk_agent.py と並列):
    - 既存 23 tests への影響ゼロ (RelevanceAgent は変更しない)
    - ADK は lazy import
    - `score_speech_single` / `score_speech_multi_persona` の 2 つを Tool として公開
      (single = score、multi = score_multi、production worker は multi を使用)

使用例 (E: Concierge Agent から subcall):
    >>> from agents.relevance.adk_agent import ADKRelevanceAgent
    >>> adk_relevance = ADKRelevanceAgent(project_id="citify-dev")
    >>> tools = adk_relevance.as_tools()  # [single tool, multi tool]
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .main import RelevanceAgent
from .schema import (
    PersonaRelevanceOutput,
    RelevanceInput,
    RelevanceOutput,
    UserPersona,
)

if TYPE_CHECKING:
    from google.adk import Agent
    from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

ADK_AGENT_DESCRIPTION = (
    "1 つの発言が指定ペルソナにとってどれだけ関心が高いかを 0-100 スコアで返す Agent。"
    "topic / age / geographic / urgency の 4 軸スコアの内訳と reasoning も出力。"
    "single (1 persona) と multi (N persona 一括) の 2 つの tool を公開。"
)

ADK_AGENT_INSTRUCTION = (
    "ユーザー入力に応じて `score_speech_single` (1 persona) または "
    "`score_speech_multi_persona` (N persona 一括) のいずれかの tool を呼んでください。"
    "production worker では multi を使用しますが、single 評価が必要な場合 (例: "
    "Concierge が 1 人のユーザーに対し評価) は single を使ってください。"
)


class ADKRelevanceAgent:
    """RelevanceAgent の ADK wrapper。

    Args:
        project_id: GCP project ID (内部 RelevanceAgent 生成用)
        relevance: Dependency Injection 用 (テストで mock 注入可)
        **relevance_kwargs: RelevanceAgent.__init__ に渡す追加 kwargs
    """

    def __init__(
        self,
        project_id: str | None = None,
        relevance: RelevanceAgent | None = None,
        **relevance_kwargs: object,
    ) -> None:
        self._relevance = relevance or RelevanceAgent(
            project_id=project_id,
            **relevance_kwargs,  # type: ignore[arg-type]
        )

    @property
    def relevance(self) -> RelevanceAgent:
        """内部 RelevanceAgent への直接アクセス (debug/inspection 用)。"""
        return self._relevance

    @property
    def prompt_version(self) -> str:
        """内部 RelevanceAgent の prompt_version を transparent に公開。"""
        return self._relevance.prompt_version

    def score_speech_single(self, input: RelevanceInput) -> RelevanceOutput:
        """1 ペルソナ × 1 speech のスコアリング。ADK FunctionTool として exposed。

        Args:
            input: 評価対象の speech + 評価先 user persona

        Returns:
            0-100 スコア + 4 軸内訳 + reasoning + 倫理メタデータ
        """
        return self._relevance.score(input)

    def score_speech_multi_persona(
        self,
        input: RelevanceInput,
        personas: list[UserPersona],
    ) -> list[PersonaRelevanceOutput]:
        """N ペルソナ × 1 speech を 1 API 呼び出しで一括スコアリング。

        production worker (Phase Y) で使用しているパターン。
        失敗 / 倫理違反 persona は below_threshold で graceful 返却。

        Args:
            input: 評価対象の speech (user フィールドは無視、personas で上書き)
            personas: 評価先 user persona のリスト (典型 5 personas)

        Returns:
            persona ごとのスコア結果リスト (入力 personas と同順)
        """
        return self._relevance.score_multi(input, personas)

    def as_tools(self) -> list[FunctionTool]:
        """ADK FunctionTool のリストを返す (single と multi の 2 つ)。"""
        from google.adk.tools import FunctionTool

        return [
            FunctionTool(func=self.score_speech_single),
            FunctionTool(func=self.score_speech_multi_persona),
        ]

    def as_tool(self) -> FunctionTool:
        """ADK FunctionTool 1 つ (multi-persona を default として公開)。

        production の worker と同じ multi-persona パターンを推奨。
        single だけ必要なら `as_tools()[0]` で取得可能。
        """
        from google.adk.tools import FunctionTool

        return FunctionTool(func=self.score_speech_multi_persona)

    def as_agent(self, name: str = "relevance") -> Agent:
        """単独 ADK Agent として返す。Runner で直接実行可能、demo 用途。

        Args:
            name: Agent 名 (Runner ログや multi-agent 階層で使用)

        Returns:
            `google.adk.Agent` (score_speech_single + multi_persona tools を持つ)
        """
        from google.adk import Agent

        return Agent(
            name=name,
            description=ADK_AGENT_DESCRIPTION,
            model=self._relevance.model,
            instruction=ADK_AGENT_INSTRUCTION,
            input_schema=RelevanceInput,
            output_schema=RelevanceOutput,
            tools=self.as_tools(),
        )
