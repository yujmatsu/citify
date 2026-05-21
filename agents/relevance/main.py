"""RelevanceAgent: Gemini 2.5 Flash でペルソナ × speech の影響度を 0-100 算出。

設計 (TranslatorAgent と並列):
    - google.genai SDK (Vertex AI 経由) で response_schema 構造化出力
    - dimension スコア合計の整合性チェック + 自動補正
    - 倫理違反検出時最大 3 回 retry
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from .prompts.system import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from .schema import RelevanceInput, RelevanceOutput

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.2  # 採点タスクは特に再現性重視
DEFAULT_MAX_OUTPUT_TOKENS = 2048
DEFAULT_THINKING_BUDGET = 0
MAX_RETRIES = 3

# A-5 と同じ禁止語 (倫理一貫性)
FORBIDDEN_PATTERNS = [
    re.compile(r"処方"),
    re.compile(r"投票.{0,5}推奨"),
    re.compile(r"必ず投票"),
    re.compile(r"絶対に.{0,3}(賛成|反対)"),
]


class _GenAIClientProto(Protocol):
    models: Any


class RelevanceAgent:
    """ペルソナ × speech の影響度を 0-100 で評価する Agent。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = PROMPT_VERSION,
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

    def score(self, input: RelevanceInput) -> RelevanceOutput:
        """関連性スコアを返す。倫理違反検出時は最大 3 回 retry。"""
        # 早期 return: 評価対象テキストが空
        has_summary = bool(input.translated_summary)
        has_content = bool(input.content_text.strip())
        if not has_summary and not has_content:
            logger.warning("relevance.empty_input speech_id=%s", input.speech_id)
            return RelevanceOutput.below_threshold("評価対象テキストが空です")

        client = self._ensure_client()
        user_prompt = build_user_prompt(
            title=input.title,
            translated_summary=input.translated_summary,
            content_text=input.content_text,
            speaker_position=input.speaker_position,
            meeting_context=input.meeting_context,
            municipality_code=input.municipality_code,
            age_group=input.user.age_group,
            interests=list(input.user.interests),
            municipality_codes=list(input.user.municipality_codes),
        )

        last_output: RelevanceOutput | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            output = self._call_gemini(client, user_prompt)
            # dimension スコア合計と relevance_score の整合性を自動補正
            output = self._normalize_score(output)
            last_output = output

            ethical_issues = self._validate_ethics(output)
            if not ethical_issues:
                logger.info(
                    "relevance.success speech_id=%s user=%s score=%d attempt=%d prompt_version=%s",
                    input.speech_id,
                    input.user.user_id,
                    output.relevance_score,
                    attempt,
                    self.prompt_version,
                )
                return output

            logger.warning(
                "relevance.ethics_violation speech_id=%s attempt=%d/%d issues=%s",
                input.speech_id,
                attempt,
                MAX_RETRIES,
                ethical_issues,
            )

        logger.error(
            "relevance.give_up speech_id=%s last_output=%s",
            input.speech_id,
            (last_output.model_dump() if last_output else None),
        )
        return RelevanceOutput.below_threshold("倫理ガードレール違反のため非表示")

    def _call_gemini(self, client: _GenAIClientProto, user_prompt: str) -> RelevanceOutput:
        """Gemini への 1 回呼び出し (response_schema で構造化出力強制)。"""
        from google.genai import types

        config_kwargs: dict[str, object] = {
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": RelevanceOutput,
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
        if parsed is not None and isinstance(parsed, RelevanceOutput):
            return parsed

        text = getattr(response, "text", "") or ""
        if not text:
            return RelevanceOutput.below_threshold("Gemini から空のレスポンス")
        try:
            return RelevanceOutput.model_validate_json(text)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "relevance.json_parse_failed text_preview=%r error=%s",
                text[:200],
                exc,
            )
            return RelevanceOutput.below_threshold(
                f"Gemini レスポンス parse 失敗: {exc.__class__.__name__}"
            )

    def _normalize_score(self, output: RelevanceOutput) -> RelevanceOutput:
        """4 軸合計と relevance_score の不整合を補正 (LLM 算数ミス対策)。

        差が 5 点以上なら 4 軸合計を優先 (合計の方が個別 dim の整合より信頼可)。
        """
        computed = (
            output.score_topic + output.score_age + output.score_geographic + output.score_urgency
        )
        if abs(computed - output.relevance_score) >= 5:
            logger.info(
                "relevance.score_normalized declared=%d computed=%d",
                output.relevance_score,
                computed,
            )
            return output.model_copy(update={"relevance_score": min(computed, 100)})
        return output

    def _validate_ethics(self, output: RelevanceOutput) -> list[str]:
        """reasoning の倫理チェック。"""
        issues: list[str] = []
        if output.contains_political_judgment:
            issues.append("contains_political_judgment=True")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(output.reasoning):
                issues.append(f"forbidden_pattern: {pattern.pattern}")
        return issues
