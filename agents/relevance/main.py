"""RelevanceAgent: Gemini 2.5 Flash でペルソナ × speech の影響度を 0-100 算出。

設計 (TranslatorAgent と並列):
    - google.genai SDK (Vertex AI 経由) で response_schema 構造化出力
    - dimension スコア合計の整合性チェック + 自動補正
    - 倫理違反検出時最大 3 回 retry
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from agents._shared.forbidden import FORBIDDEN_PATTERNS

from .prompts.system import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_multi_user_prompt,
    build_user_prompt,
)
from .schema import (
    MultiPersonaRelevanceOutput,
    PersonaRelevanceOutput,
    RelevanceInput,
    RelevanceOutput,
    UserPersona,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.2  # 採点タスクは特に再現性重視
DEFAULT_MAX_OUTPUT_TOKENS = 2048
DEFAULT_THINKING_BUDGET = 0
MAX_RETRIES = 3

# Plan E で agents/_shared/forbidden.py に集約済 (再 export で後方互換維持)
__all__ = ["FORBIDDEN_PATTERNS", "RelevanceAgent"]


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

    # ------------------------------------------------------------------------
    # Phase Y: multi-persona fan-out
    # ------------------------------------------------------------------------

    def score_multi(
        self,
        input: RelevanceInput,
        personas: list[UserPersona],
    ) -> list[PersonaRelevanceOutput]:
        """1 speech に対し N ペルソナを 1 API 呼び出しで一括採点。

        失敗時は below_threshold 相当の結果を全 persona に返す (graceful)。
        個別 persona の倫理違反は当該 persona のみ below_threshold に置換。
        """
        if not personas:
            return []

        has_summary = bool(input.translated_summary)
        has_content = bool(input.content_text.strip())
        if not has_summary and not has_content:
            logger.warning("relevance.multi.empty_input speech_id=%s", input.speech_id)
            return [self._below_threshold_persona(p, "評価対象テキストが空") for p in personas]

        client = self._ensure_client()
        user_prompt = build_multi_user_prompt(
            title=input.title,
            translated_summary=input.translated_summary,
            content_text=input.content_text,
            speaker_position=input.speaker_position,
            meeting_context=input.meeting_context,
            municipality_code=input.municipality_code,
            personas=[
                {
                    "user_id": p.user_id,
                    "age_group": p.age_group,
                    "interests": list(p.interests),
                    "municipality_codes": list(p.municipality_codes),
                }
                for p in personas
            ],
        )

        try:
            multi_output = self._call_gemini_multi(client, user_prompt)
        except Exception as exc:  # noqa: BLE001
            logger.exception("relevance.multi.api_failed speech_id=%s err=%s", input.speech_id, exc)
            return [self._below_threshold_persona(p, "Gemini API 失敗") for p in personas]

        # 入力順 ≠ 出力順の場合に備えて user_id で map
        by_user_id: dict[str, PersonaRelevanceOutput] = {r.user_id: r for r in multi_output.results}
        results: list[PersonaRelevanceOutput] = []
        for persona in personas:
            r = by_user_id.get(persona.user_id)
            if r is None:
                logger.warning(
                    "relevance.multi.missing_user_id speech_id=%s user_id=%s",
                    input.speech_id,
                    persona.user_id,
                )
                results.append(self._below_threshold_persona(persona, "Gemini 出力に user_id 不在"))
                continue
            # 正規化 + 倫理チェック (相当する RelevanceOutput を作って既存ロジック流用)
            ro = self._normalize_score(r.to_relevance_output())
            ethics_issues = self._validate_ethics(ro)
            if ethics_issues:
                logger.warning(
                    "relevance.multi.ethics_violation speech_id=%s user_id=%s issues=%s",
                    input.speech_id,
                    persona.user_id,
                    ethics_issues,
                )
                results.append(self._below_threshold_persona(persona, "倫理ガードレール違反"))
                continue
            results.append(
                PersonaRelevanceOutput(
                    user_id=persona.user_id,
                    relevance_score=ro.relevance_score,
                    score_topic=ro.score_topic,
                    score_age=ro.score_age,
                    score_geographic=ro.score_geographic,
                    score_urgency=ro.score_urgency,
                    matched_interests=list(ro.matched_interests),
                    reasoning=ro.reasoning,
                    contains_political_judgment=ro.contains_political_judgment,
                )
            )

        logger.info(
            "relevance.multi.success speech_id=%s n=%d scores=%s",
            input.speech_id,
            len(results),
            ",".join(f"{r.user_id}:{r.relevance_score}" for r in results),
        )
        return results

    def _call_gemini_multi(
        self, client: _GenAIClientProto, user_prompt: str
    ) -> MultiPersonaRelevanceOutput:
        from google.genai import types

        config_kwargs: dict[str, object] = {
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": MultiPersonaRelevanceOutput,
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
        if parsed is not None and isinstance(parsed, MultiPersonaRelevanceOutput):
            return parsed

        text = getattr(response, "text", "") or ""
        if not text:
            return MultiPersonaRelevanceOutput(results=[])
        return MultiPersonaRelevanceOutput.model_validate_json(text)

    @staticmethod
    def _below_threshold_persona(persona: UserPersona, reason: str) -> PersonaRelevanceOutput:
        return PersonaRelevanceOutput(
            user_id=persona.user_id,
            relevance_score=0,
            score_topic=0,
            score_age=0,
            score_geographic=0,
            score_urgency=0,
            matched_interests=[],
            reasoning=reason,
            contains_political_judgment=False,
        )
