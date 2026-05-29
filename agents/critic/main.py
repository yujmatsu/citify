"""CriticAgent: 翻訳品質を 4 軸スコアリング (Plan D)。

Translator から DI で受け取られ、`translate_with_critique()` の中で 1 度呼ばれる。
Gemini Flash で構造化出力 (CriticScores response_schema)。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from agents.translator.schema import TranslateInput, TranslatorOutput

from .prompts.system import (
    CRITIC_PROMPT_VERSION,
    CRITIC_SYSTEM_PROMPT,
    build_critic_user_prompt,
)
from .schema import CriticScores, CritiqueResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.1  # 評価は再現性最優先、低温度
DEFAULT_MAX_OUTPUT_TOKENS = 1024
DEFAULT_THINKING_BUDGET = 0  # 評価はパターン照合中心、深い推論不要

# 強制 revise トリガー (overall_score が threshold 以上でも ethics 低なら revise)
ETHICS_HARD_FLOOR = 60


class _GenAIClientProto(Protocol):
    """テスト用 mock 用 minimal interface。"""

    models: Any


class CriticAgent:
    """翻訳品質評価 Agent (4 軸スコアリング + feedback 生成)。

    Args:
        project_id: GCP project ID
        location: Vertex AI location
        model: Gemini モデル名
        prompt_version: prompt バージョン (LLMOps 用ログ)
        client: テスト用 mock 注入
    """

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = CRITIC_PROMPT_VERSION,
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

    def critique(
        self,
        draft: TranslatorOutput,
        input: TranslateInput,
        threshold: int = 70,
    ) -> CritiqueResult:
        """draft を 4 軸スコアリング + feedback を返す。

        Args:
            draft: TranslatorAgent.translate() の結果
            input: 翻訳の元 input (原典 / age_group 等で評価)
            threshold: passed 判定の overall_score 下限

        Returns:
            CritiqueResult (scores + overall + feedback + passed)
        """
        # 空 draft (empty_reason: ... で始まる notes) は critique skip
        if draft.notes.startswith("empty_reason:"):
            logger.info("critic.skip_empty speech_id=%s reason=%s", input.speech_id, draft.notes)
            return CritiqueResult.empty_skip(draft.notes)

        client = self._ensure_client()
        user_prompt = build_critic_user_prompt(
            title=draft.title,
            summary=list(draft.summary),
            tone=draft.tone,
            notes=draft.notes,
            content_text=input.content_text,
            speaker_position=input.speaker_position,
            age_group=input.age_group,
            meeting_context=input.meeting_context,
        )

        scores, feedback = self._call_gemini(client, user_prompt)
        overall = round((scores.faithfulness + scores.simplicity + scores.tone + scores.ethics) / 4)
        # ethics が hard floor 未満なら threshold 満たしても passed=False
        passed = overall >= threshold and scores.ethics >= ETHICS_HARD_FLOOR

        logger.info(
            "critic.done speech_id=%s overall=%d ethics=%d passed=%s prompt_version=%s",
            input.speech_id,
            overall,
            scores.ethics,
            passed,
            self.prompt_version,
        )

        return CritiqueResult(
            scores=scores,
            overall_score=overall,
            feedback=feedback[:500],
            passed=passed,
        )

    def _call_gemini(self, client: _GenAIClientProto, user_prompt: str) -> tuple[CriticScores, str]:
        """Gemini call で CriticScores + feedback を構造化取得。

        response_schema は CriticScores のみ、feedback は別途 text として後段で抽出
        … ではなく、内部用 Pydantic で 2 つを束ねた `_CriticRawOutput` を一発で取得する。
        """
        from google.genai import types
        from pydantic import BaseModel as _BM
        from pydantic import Field as _F

        # 内部 schema: scores + feedback を Gemini に 1 回で返してもらう
        class _CriticRawOutput(_BM):
            faithfulness: int = _F(ge=0, le=100)
            simplicity: int = _F(ge=0, le=100)
            tone: int = _F(ge=0, le=100)
            ethics: int = _F(ge=0, le=100)
            feedback: str = _F(default="", max_length=500)

        config_kwargs: dict[str, object] = {
            "system_instruction": CRITIC_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": _CriticRawOutput,
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
        if parsed is not None and isinstance(parsed, _CriticRawOutput):
            raw = parsed
        else:
            text = getattr(response, "text", "") or ""
            if not text:
                logger.warning("critic.empty_response defaulting to 0 scores")
                return CriticScores(faithfulness=0, simplicity=0, tone=0, ethics=0), "(no response)"
            try:
                raw = _CriticRawOutput.model_validate_json(text)
            except Exception as exc:  # noqa: BLE001
                logger.error("critic.parse_failed text_preview=%r err=%s", text[:200], exc)
                return (
                    CriticScores(faithfulness=0, simplicity=0, tone=0, ethics=0),
                    f"critic_parse_failed: {exc.__class__.__name__}",
                )

        scores = CriticScores(
            faithfulness=raw.faithfulness,
            simplicity=raw.simplicity,
            tone=raw.tone,
            ethics=raw.ethics,
        )
        return scores, raw.feedback
