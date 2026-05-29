"""TranslatorAgent の ADK (Agent Development Kit) wrapper (Plan C)。

既存 `TranslatorAgent.translate()` の core logic はそのまま保持し、
ADK の `Agent` / `FunctionTool` インターフェースに準拠した形で
他の Agent (E: Concierge 等) から subcall 可能にする薄い wrapper。

設計方針:
    - 既存 68 tests への影響ゼロ (TranslatorAgent は変更しない)
    - ADK は **lazy import** (`as_tool()` / `as_agent()` 内で import)
      → ADK 未 install 環境でも `import agents.translator.adk_agent` は成功
    - `translate_speech()` は内部で `TranslatorAgent.translate()` を呼ぶだけ
      → 2 重 LLM call にならない (ADK Agent 経由でも Translator core は 1 回)

使用例 (E: Concierge Agent から subcall):
    >>> from agents.translator.adk_agent import ADKTranslatorAgent
    >>> adk_translator = ADKTranslatorAgent(project_id="citify-dev")
    >>> tool = adk_translator.as_tool()  # FunctionTool として渡す
    >>> concierge = Agent(name="concierge", tools=[tool, ...])
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .main import TranslatorAgent
from .schema import TranslateInput, TranslatorOutput

if TYPE_CHECKING:
    from google.adk import Agent
    from google.adk.tools import FunctionTool

logger = logging.getLogger(__name__)

# ADK Agent としての説明文 (LLM が tool を選ぶ際の説明)
ADK_AGENT_DESCRIPTION = (
    "自治体の議事録・プレスリリースの発言を若者向けに平易化して "
    "3 行サマリに翻訳する Agent。固有名詞や政党名は出力しない倫理ガードレール内蔵。"
)

ADK_AGENT_INSTRUCTION = (
    "ユーザー入力 (TranslateInput) を `translate_speech` ツールに渡して "
    "翻訳結果 (TranslatorOutput) を返してください。倫理違反 (政治家名や賛否表明) は "
    "tool 側で検出・再生成済なので、tool の出力をそのまま返却すれば OK です。"
)


class ADKTranslatorAgent:
    """TranslatorAgent の ADK wrapper。

    Args:
        project_id: GCP project ID (内部 TranslatorAgent 生成用)
        translator: Dependency Injection 用 (テストで mock 注入可)
        **translator_kwargs: TranslatorAgent.__init__ に渡す追加 kwargs
    """

    def __init__(
        self,
        project_id: str | None = None,
        translator: TranslatorAgent | None = None,
        **translator_kwargs: object,
    ) -> None:
        self._translator = translator or TranslatorAgent(
            project_id=project_id,
            **translator_kwargs,  # type: ignore[arg-type]
        )

    @property
    def translator(self) -> TranslatorAgent:
        """内部 TranslatorAgent への直接アクセス (debug/inspection 用)。"""
        return self._translator

    @property
    def prompt_version(self) -> str:
        """内部 TranslatorAgent の prompt_version を transparent に公開。"""
        return self._translator.prompt_version

    def translate_speech(self, input: TranslateInput) -> TranslatorOutput:
        """1 発言を翻訳。ADK FunctionTool として exposed される public 関数。

        Args:
            input: 翻訳対象の発言 + ペルソナ情報

        Returns:
            翻訳結果 (3 行サマリ + tone + 倫理メタデータ)
        """
        return self._translator.translate(input)

    def as_tool(self) -> FunctionTool:
        """ADK FunctionTool として返す。他 Agent (Concierge 等) から subcall 用。

        Returns:
            `google.adk.tools.FunctionTool` (translate_speech をラップ)
        """
        from google.adk.tools import FunctionTool

        return FunctionTool(func=self.translate_speech)

    def as_agent(self, name: str = "translator") -> Agent:
        """単独 ADK Agent として返す。Runner で直接実行可能、demo 用途。

        Args:
            name: Agent 名 (Runner ログや multi-agent 階層で使用)

        Returns:
            `google.adk.Agent` (translate_speech tool を持つ Agent)
        """
        from google.adk import Agent

        return Agent(
            name=name,
            description=ADK_AGENT_DESCRIPTION,
            model=self._translator.model,
            instruction=ADK_AGENT_INSTRUCTION,
            input_schema=TranslateInput,
            output_schema=TranslatorOutput,
            tools=[self.as_tool()],
        )
