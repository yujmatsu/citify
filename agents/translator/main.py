"""TranslatorAgent: Gemini 2.5 Flash で議事録 → 若者向け 3 行サマリ。

設計:
    - google.genai SDK (Vertex AI 経由) で構造化出力 (response_schema)
    - max 3 回までリトライ (ガードレール違反検出時)
    - 入力空の場合は empty() で短絡
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

from .prompts.system import PROMPT_VERSION, SYSTEM_PROMPT, build_user_prompt
from .schema import TranslateInput, TranslatorOutput

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"  # Gemini が最も安定したリージョン
DEFAULT_TEMPERATURE = 0.3  # 翻訳は再現性重視、低めに
# Gemini 2.5 系は thinking tokens を内部消費するため余裕を持たせる
# (1024 だと「{ title: ...」途中で truncate される実例あり)
DEFAULT_MAX_OUTPUT_TOKENS = 2048
DEFAULT_THINKING_BUDGET = 0  # 翻訳に深い推論不要、token 節約 + 速度向上
MAX_RETRIES = 3

# 倫理ガードレール: 出力に含まれてはいけないキーワード (post-validation)
FORBIDDEN_PATTERNS = [
    re.compile(r"処方"),
    re.compile(r"投票.{0,5}推奨"),
    re.compile(r"必ず投票"),
    re.compile(r"絶対に.{0,3}(賛成|反対)"),
]


class _GenAIClientProto(Protocol):
    """テスト用に google.genai.Client を mock 可能にする。"""

    models: Any


class TranslatorAgent:
    """役所言葉 → 若者向け 3 行サマリの翻訳 Agent。

    Args:
        project_id: GCP project ID (Vertex AI へのアクセス用)
        location: Vertex AI location (Gemini 提供リージョン)
        model: Gemini モデル名 (default: gemini-2.5-flash)
        prompt_version: プロンプトバージョン (LLMOps 用、ログに記録)
        client: テスト用 mock 注入
    """

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
        """遅延 import: テストで mock 注入時は google.genai 不要。"""
        if self._client is not None:
            return self._client
        from google import genai

        self._client = genai.Client(vertexai=True, project=self.project_id, location=self.location)
        return self._client

    def translate(self, input: TranslateInput) -> TranslatorOutput:
        """発言を平易化。倫理違反検出時は最大 3 回までリトライ。"""
        # 早期 return: 空入力
        if not input.content_text.strip():
            logger.warning("translator.empty_input speech_id=%s", input.speech_id)
            return TranslatorOutput.empty("発言本文が空です")

        client = self._ensure_client()
        user_prompt = build_user_prompt(
            content_text=input.content_text,
            speaker_position=input.speaker_position,
            meeting_context=input.meeting_context,
            age_group=input.age_group,
        )

        last_output: TranslatorOutput | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            output = self._call_gemini(client, user_prompt)
            last_output = output

            # 倫理ガードレール: post-validation
            ethical_issues = self._validate_ethics(output, input)
            if not ethical_issues:
                logger.info(
                    "translator.success speech_id=%s attempt=%d prompt_version=%s",
                    input.speech_id,
                    attempt,
                    self.prompt_version,
                )
                return output

            logger.warning(
                "translator.ethics_violation speech_id=%s attempt=%d/%d issues=%s",
                input.speech_id,
                attempt,
                MAX_RETRIES,
                ethical_issues,
            )

        # 全試行で倫理違反 → 警告して empty を返す (production では監視 alert)
        logger.error(
            "translator.give_up speech_id=%s last_output=%s",
            input.speech_id,
            (last_output.model_dump() if last_output else None),
        )
        return TranslatorOutput.empty("倫理ガードレール違反のため出力を破棄")

    def _call_gemini(self, client: _GenAIClientProto, user_prompt: str) -> TranslatorOutput:
        """Gemini への 1 回呼び出し (response_schema で構造化出力強制)。"""
        # 遅延 import: テストで mock 時は不要
        from google.genai import types

        # Gemini 2.5 系の thinking_budget を制御 (翻訳には不要、token 節約)
        config_kwargs: dict[str, object] = {
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": TranslatorOutput,
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

        # response.parsed は response_schema があれば自動で Pydantic instance
        parsed = getattr(response, "parsed", None)
        if parsed is not None and isinstance(parsed, TranslatorOutput):
            return parsed

        # fallback: text を JSON として parse
        text = getattr(response, "text", "") or ""
        if not text:
            return TranslatorOutput.empty("Gemini から空のレスポンス")
        try:
            return TranslatorOutput.model_validate_json(text)
        except Exception as exc:  # noqa: BLE001
            # truncation や schema mismatch でパース失敗 (debug 用に text の冒頭をログ)
            logger.error(
                "translator.json_parse_failed text_preview=%r error=%s",
                text[:200],
                exc,
            )
            return TranslatorOutput.empty(f"Gemini レスポンス parse 失敗: {exc.__class__.__name__}")

    def _validate_ethics(self, output: TranslatorOutput, input: TranslateInput) -> list[str]:
        """出力の倫理チェック。問題があれば説明文字列のリストを返す。"""
        issues: list[str] = []

        # LLM 自己申告チェック
        if output.contains_politician_names:
            issues.append("contains_politician_names=True")
        if output.contains_political_judgment:
            issues.append("contains_political_judgment=True")

        # post-validation: speaker 名が出力に混入していないか
        if input.speaker:
            for field in [output.title, *output.summary]:
                if input.speaker in field:
                    issues.append(f"speaker_name_leaked: '{input.speaker}'")
                    break

        # post-validation: 政党名が出力に混入していないか
        if input.speaker_group:
            party_short = input.speaker_group.split("・")[0]  # "立憲民主・無所属" → "立憲民主"
            for field in [output.title, *output.summary]:
                if party_short in field:
                    issues.append(f"party_name_leaked: '{party_short}'")
                    break

        # post-validation: 禁止語チェック
        for field in [output.title, *output.summary]:
            for pattern in FORBIDDEN_PATTERNS:
                if pattern.search(field):
                    issues.append(f"forbidden_pattern: {pattern.pattern}")

        return issues
