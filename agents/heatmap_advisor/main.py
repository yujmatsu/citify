"""HeatmapAdvisor: ペルソナを踏まえてヒートマップ指標を選定 (Plan X)。

Gemini Flash で構造化出力、LLM 失敗時は FALLBACK_METRIC_BY_INTEREST に graceful degrade。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from agents.relevance.schema import Interest

from .prompts.system import (
    HEATMAP_ADVISOR_PROMPT_VERSION,
    HEATMAP_ADVISOR_SYSTEM_PROMPT,
    PREFECTURE_NAMES_JA,
    build_advisor_user_prompt,
)
from .schema import HeatmapAdvice, HeatmapMetricSpec, PersonaContext

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.2  # 選定は再現性重視
DEFAULT_MAX_OUTPUT_TOKENS = 1024
DEFAULT_THINKING_BUDGET = 256  # Chain-of-Thought 用に少し確保


# ============================================================================
# Fallback mapping (LLM 失敗時の固定 rule、関心軸 → 指標)
# ============================================================================

FALLBACK_METRIC_BY_INTEREST: dict[Interest, HeatmapMetricSpec] = {
    "住居": HeatmapMetricSpec(
        column="used_apartment_median_price_man_yen",
        label_ja="中古マンション中央値",
        direction="lower_is_better",
        unit="万円",
    ),
    "雇用": HeatmapMetricSpec(
        column="youth_share_pct",
        label_ja="若者比率 (15-29 歳)",
        direction="higher_is_better",
        unit="%",
    ),
    "結婚": HeatmapMetricSpec(
        column="youth_share_pct",
        label_ja="若者比率 (15-29 歳)",
        direction="higher_is_better",
        unit="%",
    ),
    "子育て": HeatmapMetricSpec(
        column="childcare_facility_count",
        label_ja="保育・幼児教育施設数",
        direction="higher_is_better",
        unit="件",
    ),
    "税": HeatmapMetricSpec(
        column="population_change_pct",
        label_ja="人口増減率 (直近国勢調査)",
        direction="higher_is_better",
        unit="%",
    ),
    "起業": HeatmapMetricSpec(
        column="youth_share_pct",
        label_ja="若者比率 (15-29 歳)",
        direction="higher_is_better",
        unit="%",
    ),
    "防災": HeatmapMetricSpec(
        column="emergency_shelter_count",
        label_ja="緊急避難場所数",
        direction="higher_is_better",
        unit="件",
    ),
    "医療": HeatmapMetricSpec(
        column="medical_facility_count",
        label_ja="医療機関数",
        direction="higher_is_better",
        unit="件",
    ),
    "教育": HeatmapMetricSpec(
        column="childcare_facility_count",
        label_ja="保育・幼児教育施設数",
        direction="higher_is_better",
        unit="件",
    ),
    "移住": HeatmapMetricSpec(
        column="population_change_pct",
        label_ja="人口増減率 (直近国勢調査)",
        direction="higher_is_better",
        unit="%",
    ),
}


class _GenAIClientProto(Protocol):
    """テスト用 mock 用 minimal interface。"""

    models: Any


def _contains_prefecture_name(text: str) -> str | None:
    """text に 47 都道府県名が含まれていれば最初の 1 件を返す。倫理ガード判定用。"""
    for name in PREFECTURE_NAMES_JA:
        if name in text:
            return name
    return None


class HeatmapAdvisor:
    """ペルソナを受けて全国ヒートマップの色付け指標を選定する Agent。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = HEATMAP_ADVISOR_PROMPT_VERSION,
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

    def suggest_metric(self, persona: PersonaContext) -> HeatmapAdvice:
        """ペルソナを受けて HeatmapAdvice を返す。LLM 失敗時は fallback。"""
        try:
            advice = self._call_gemini(persona)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "heatmap_advisor.llm_failed user_id=%s err=%s",
                persona.user_id,
                exc,
            )
            return self._fallback(persona, reason=f"llm_failed: {exc.__class__.__name__}")

        # 倫理ガード post-validation: reasoning に 47 都道府県名が含まれたら fallback
        leaked = _contains_prefecture_name(advice.reasoning)
        if leaked is not None:
            logger.warning(
                "heatmap_advisor.ethics_leak user_id=%s leaked=%s",
                persona.user_id,
                leaked,
            )
            # ユーザー向け reasoning に leaked 県名を含めない (ログのみで詳細追跡)
            return self._fallback(persona, reason="ethics_leak")

        logger.info(
            "heatmap_advisor.done user_id=%s metric=%s direction=%s prompt_version=%s",
            persona.user_id,
            advice.metric_column,
            advice.direction,
            self.prompt_version,
        )
        return advice

    def _call_gemini(self, persona: PersonaContext) -> HeatmapAdvice:
        """Gemini call で構造化 HeatmapAdvice を取得。"""
        from google.genai import types

        client = self._ensure_client()
        user_prompt = build_advisor_user_prompt(
            age_group=persona.age_group,
            interests=list(persona.interests),
            free_form_context=persona.free_form_context,
            focus_interest=persona.focus_interest,
        )

        config_kwargs: dict[str, object] = {
            "system_instruction": HEATMAP_ADVISOR_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": HeatmapAdvice,
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
        if parsed is not None and isinstance(parsed, HeatmapAdvice):
            parsed.source = "llm"
            return parsed

        text = getattr(response, "text", "") or ""
        if not text:
            raise RuntimeError("Gemini returned empty response")
        advice = HeatmapAdvice.model_validate_json(text)
        advice.source = "llm"
        return advice

    def _fallback(self, persona: PersonaContext, reason: str) -> HeatmapAdvice:
        """LLM 失敗時 / 倫理 leak 検出時の rule-based fallback。"""
        spec = FALLBACK_METRIC_BY_INTEREST.get(
            persona.focus_interest,
            FALLBACK_METRIC_BY_INTEREST["住居"],
        )
        return HeatmapAdvice(
            metric_column=spec.column,
            metric_label_ja=spec.label_ja,
            direction=spec.direction,
            unit=spec.unit,
            reasoning=(
                f"(rule-based) {persona.focus_interest} 軸では一般的に "
                f"{spec.label_ja}を見ます。LLM 選定は利用できなかったため固定ルールを適用しました ({reason})。"
            ),
            persona_summary=(f"{persona.age_group} / 関心軸: {persona.focus_interest}"),
            source="rule_based",
        )
