"""MetaReasoningAgent (Plan PP): Meta-Reasoner pattern (Reflexion / CoVe)。

入出力 3 フィールド + 4 出力 list に対する 3 層倫理ガード (連鎖防止):
    - 入力 (raw_reasoning / agent_output_summary / persona_context) に leak があれば fallback
    - 出力 (plain_summary / influencing_factors / counterfactuals / caveats) も全フィールド検査
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from agents.forecast.main import _detect_any_leak

from .prompts.system import (
    META_REASONING_PROMPT_VERSION,
    META_REASONING_SYSTEM_PROMPT,
    build_meta_user_prompt,
)
from .schema import (
    AgentName,
    ReasoningExplanation,
    ReasoningInspectInput,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_OUTPUT_TOKENS = 1536
# Reviewer Medium #5: 6 フィールド埋めるため forecast の 256 から 512 に増
DEFAULT_THINKING_BUDGET = 512


# Agent 毎の rule_based fallback テンプレ (LLM 失敗時)
_RULE_BASED_TEMPLATES: dict[AgentName, dict[str, str]] = {
    "concierge": {
        "factor": "ユーザーペルソナ (年代 / 関心軸) + 自治体統計データ",
        "counterfactual": "別の関心軸を選んだら、Agent は異なる候補自治体を提示する可能性があります",
    },
    "translator": {
        "factor": "発言原文 + ペルソナ年代に基づく tone 設定",
        "counterfactual": "別の年代を指定したら、より formal または casual な訳に変わる可能性があります",
    },
    "critic": {
        "factor": "4 軸スコア (faithfulness / simplicity / tone / ethics)",
        "counterfactual": "別の軸を重く評価したら、合格判定が変わる可能性があります",
    },
    "heatmap_advisor": {
        "factor": "関心軸 + 統計指標の direction 方針",
        "counterfactual": "別の関心軸なら、別の統計指標が示唆的になる可能性があります",
    },
    "timeline": {
        "factor": "候補発言の時系列 + relevance score",
        "counterfactual": "対象期間や自治体を変えたら、別の議論変遷が見える可能性があります",
    },
    "forecast": {
        "factor": "過去 N か月の月別件数 + 線形回帰 slope",
        "counterfactual": "history が短かったり分散が大きいと、信頼度は低くなります",
    },
    "scraper_doctor": {
        "factor": "error_type / stack_trace / html 構造",
        "counterfactual": "別のスクレイパーや別のエラーパターンなら、推奨 action が変わります",
    },
}


def _validate_input_leaks(input: ReasoningInspectInput) -> str | None:
    """3 入力フィールド全てに leak チェック (Reviewer High #1)。leak があれば文字列、なければ None。"""
    for field_name, text in (
        ("raw_reasoning", input.raw_reasoning),
        ("agent_output_summary", input.agent_output_summary),
        ("persona_context", input.persona_context or ""),
    ):
        leaked = _detect_any_leak(text)
        if leaked:
            return f"{field_name}: {leaked}"
    return None


def _validate_output_leaks(explanation: ReasoningExplanation) -> str | None:
    """出力全フィールドに leak チェック (Reviewer Medium #4)。"""
    all_texts: list[str] = [explanation.plain_summary]
    all_texts.extend(explanation.influencing_factors)
    all_texts.extend(explanation.counterfactuals)
    all_texts.extend(explanation.caveats)
    for text in all_texts:
        leaked = _detect_any_leak(text)
        if leaked:
            return leaked
    return None


class _GenAIClientProto(Protocol):
    """テスト用 mock 用 minimal interface。"""

    models: Any


class MetaReasoningAgent:
    """各 Agent の reasoning を第三者観測者視点で再構成する Meta-Reasoner (Plan PP)。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = META_REASONING_PROMPT_VERSION,
        temperature: float = DEFAULT_TEMPERATURE,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        thinking_budget: int = DEFAULT_THINKING_BUDGET,
        client: _GenAIClientProto | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.model = model
        self.prompt_version = prompt_version
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.thinking_budget = thinking_budget
        self._client = client

    def _ensure_client(self) -> _GenAIClientProto:
        if self._client is not None:
            return self._client
        from google import genai

        self._client = genai.Client(vertexai=True, project=self.project_id, location=self.location)
        return self._client

    def explain(self, input: ReasoningInspectInput) -> ReasoningExplanation:
        """対象 Agent の reasoning を第三者視点で再構成。LLM 失敗 / leak で fallback。"""
        # 入力 leak 検査 (Reviewer High #1、連鎖防止)
        input_leak = _validate_input_leaks(input)
        if input_leak:
            logger.warning(
                "reasoner.input_leak agent=%s leak=%s",
                input.agent_name,
                input_leak,
            )
            return self._rule_based(input, reason="input_leak_chain_prevent")

        try:
            explanation = self._call_gemini(input)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "reasoner.llm_failed agent=%s err=%s",
                input.agent_name,
                exc,
            )
            return self._rule_based(input, reason="llm_failed")

        # 出力 leak 検査 (Reviewer Medium #4)
        output_leak = _validate_output_leaks(explanation)
        if output_leak:
            logger.warning(
                "reasoner.output_leak agent=%s leak=%s",
                input.agent_name,
                output_leak,
            )
            return self._rule_based(input, reason="output_leak")

        explanation.source = "llm"
        logger.info(
            "reasoner.done agent=%s confidence=%s n_factors=%d n_cf=%d",
            input.agent_name,
            explanation.confidence,
            len(explanation.influencing_factors),
            len(explanation.counterfactuals),
        )
        return explanation

    def _call_gemini(self, input: ReasoningInspectInput) -> ReasoningExplanation:
        from google.genai import types

        client = self._ensure_client()
        user_prompt = build_meta_user_prompt(
            agent_name=input.agent_name,
            raw_reasoning=input.raw_reasoning,
            agent_output_summary=input.agent_output_summary,
            persona_context=input.persona_context,
        )

        config_kwargs: dict[str, object] = {
            "system_instruction": META_REASONING_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": ReasoningExplanation,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
        }
        if self.thinking_budget >= 0 and hasattr(types, "ThinkingConfig"):
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_budget=self.thinking_budget,
            )

        response = client.models.generate_content(
            model=self.model,
            contents=user_prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        parsed = getattr(response, "parsed", None)
        if parsed is not None and isinstance(parsed, ReasoningExplanation):
            return parsed
        text = getattr(response, "text", "") or ""
        if not text:
            raise RuntimeError("Gemini returned empty meta reasoning")
        return ReasoningExplanation.model_validate_json(text)

    def _rule_based(
        self,
        input: ReasoningInspectInput,
        reason: str,
    ) -> ReasoningExplanation:
        """LLM 失敗時 / leak 連鎖検出時の rule_based fallback (agent 別テンプレ)。"""
        template = _RULE_BASED_TEMPLATES.get(
            input.agent_name,
            {"factor": "Agent input 全般", "counterfactual": "input が異なれば結論も変わる可能性"},
        )
        return ReasoningExplanation(
            plain_summary=(
                f"(rule-based) {input.agent_name} Agent の判断ログを表示しています。"
                f"LLM による平易化説明は利用できなかったため、テンプレ要約のみです ({reason})。"
            )[:300],
            influencing_factors=[template["factor"]],
            counterfactuals=[template["counterfactual"]],
            caveats=[
                "rule_based fallback のため、Agent 固有の詳細な reasoning は省略されています",
            ],
            confidence="low",
            source="rule_based",
        )
