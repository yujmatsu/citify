"""ForecastNarrator: ForecastSeries (純計算済) を受けて介入的な headline + reasoning を生成 (Plan Z)。

Gemini Flash + Chain-of-Thought、LLM 失敗時 / 倫理 leak 時は rule_based fallback。
倫理ガード: Plan X の 47 都道府県名 + Plan N の政治家/政党名 + 主要市区町村名 blocklist。
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from agents.heatmap_advisor.prompts.system import PREFECTURE_NAMES_JA
from agents.timeline.main import _detect_political_leak

from .prompts.system import (
    FORECAST_PROMPT_VERSION,
    FORECAST_SYSTEM_PROMPT,
    build_narrator_user_prompt,
)
from .schema import ForecastNarrative, ForecastSeries, PersonaContext

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_OUTPUT_TOKENS = 1024  # headline 40 + reasoning 240 << 1024
DEFAULT_THINKING_BUDGET = 256  # CoT 軽量

# 主要市区町村名 blocklist (Reviewer High #1)
# 政令市 + 特別区 + 主要都市、apps/api/_MUNI_NAME_MAP から抽出
MAJOR_MUNI_NAMES: tuple[str, ...] = (
    # 政令市
    "札幌市",
    "仙台市",
    "さいたま市",
    "千葉市",
    "横浜市",
    "川崎市",
    "相模原市",
    "新潟市",
    "静岡市",
    "浜松市",
    "名古屋市",
    "京都市",
    "大阪市",
    "堺市",
    "神戸市",
    "岡山市",
    "広島市",
    "北九州市",
    "福岡市",
    "熊本市",
    # 東京 23 区
    "千代田区",
    "中央区",
    "港区",
    "新宿区",
    "文京区",
    "台東区",
    "墨田区",
    "江東区",
    "品川区",
    "目黒区",
    "大田区",
    "世田谷区",
    "渋谷区",
    "中野区",
    "杉並区",
    "豊島区",
    "北区",
    "荒川区",
    "板橋区",
    "練馬区",
    "足立区",
    "葛飾区",
    "江戸川区",
)


def _detect_geographic_leak(text: str) -> str | None:
    """text に 47 都道府県名 or 主要市区町村名が含まれていれば最初の match を返す。"""
    for name in PREFECTURE_NAMES_JA:
        if name in text:
            return name
    for muni_name in MAJOR_MUNI_NAMES:
        if muni_name in text:
            return muni_name
    return None


def _detect_any_leak(text: str) -> str | None:
    """政治家/政党 + 地理 の両方をチェック。"""
    geo = _detect_geographic_leak(text)
    if geo:
        return geo
    return _detect_political_leak(text)


class _GenAIClientProto(Protocol):
    """テスト用 mock 用 minimal interface。"""

    models: Any


class ForecastNarrator:
    """ForecastSeries 計算結果を介入的に説明する LLM Narrator (Plan Z)。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = FORECAST_PROMPT_VERSION,
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

    def narrate(
        self,
        series: ForecastSeries,
        persona: PersonaContext,
        municipality_label: str = "全国",
    ) -> ForecastNarrative:
        """ForecastSeries を受けて headline + reasoning を生成。LLM 失敗時 / leak 時 fallback。"""
        # データ不足 → rule_based template (LLM call せず)
        if series.months_in_history < 3:
            return self._rule_based(series, persona, reason="insufficient_data")

        try:
            narrative = self._call_gemini(series, persona, municipality_label)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "forecast.llm_failed user_id=%s focus=%s err=%s",
                persona.user_id,
                persona.focus_interest,
                exc,
            )
            return self._rule_based(series, persona, reason="llm_failed")

        # 倫理 post-validation (headline + reasoning)
        for text in (narrative.headline, narrative.reasoning):
            leaked = _detect_any_leak(text)
            if leaked:
                logger.warning(
                    "forecast.leak_detected user_id=%s leaked=%s",
                    persona.user_id,
                    leaked,
                )
                return self._rule_based(series, persona, reason="ethics_leak")

        narrative.source = "llm"
        logger.info(
            "forecast.done user_id=%s focus=%s trend=%s confidence=%s",
            persona.user_id,
            persona.focus_interest,
            series.trend_classification,
            series.confidence,
        )
        return narrative

    def _call_gemini(
        self,
        series: ForecastSeries,
        persona: PersonaContext,
        municipality_label: str,
    ) -> ForecastNarrative:
        from google.genai import types

        client = self._ensure_client()
        # historical を 1 行 summary に圧縮 (token 節約、LLM が数値を勝手に解釈しないよう生数値のみ)
        historical_summary = ", ".join(
            f"{m.year_month}: {int(m.speech_count)}件" for m in series.historical
        )
        user_prompt = build_narrator_user_prompt(
            theme_interest=persona.focus_interest,
            age_group=persona.age_group,
            interests_list=list(persona.interests),
            municipality_label=municipality_label,
            trend_classification=series.trend_classification,
            slope=series.slope,
            confidence=series.confidence,
            historical_summary=historical_summary,
        )

        config_kwargs: dict[str, object] = {
            "system_instruction": FORECAST_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": ForecastNarrative,
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
        if parsed is not None and isinstance(parsed, ForecastNarrative):
            return parsed
        text = getattr(response, "text", "") or ""
        if not text:
            raise RuntimeError("Gemini returned empty response")
        return ForecastNarrative.model_validate_json(text)

    def _rule_based(
        self,
        series: ForecastSeries,
        persona: PersonaContext,
        reason: str,
    ) -> ForecastNarrative:
        """LLM 失敗時 / 倫理 leak 検出時の rule_based fallback (trend 分類テンプレ)。"""
        templates: dict[str, tuple[str, str]] = {
            "surge": (
                f"{persona.focus_interest} 議題が急増中",
                f"(rule-based) {persona.focus_interest} 関連の議論件数が急増しています。月あたり {series.slope:.1f} 件のペースで増加、政策議論のホットトピックに。",
            ),
            "increasing": (
                f"{persona.focus_interest} 議題は緩やかに増加",
                f"(rule-based) {persona.focus_interest} 関連の議論件数が緩やかに増加しています。月あたり {series.slope:.1f} 件の増加傾向。",
            ),
            "flat": (
                f"{persona.focus_interest} 議題は横ばい",
                f"(rule-based) {persona.focus_interest} 関連の議論件数は横ばいで、議論の重心は安定しています。",
            ),
            "decreasing": (
                f"{persona.focus_interest} 議題は減少傾向",
                f"(rule-based) {persona.focus_interest} 関連の議論件数が減少しています。月あたり {abs(series.slope):.1f} 件減のペース、議論の重心が他軸に移行している可能性。",
            ),
            "crash": (
                f"{persona.focus_interest} 議題が急減",
                f"(rule-based) {persona.focus_interest} 関連の議論件数が急減しています。月あたり {abs(series.slope):.1f} 件減、議論の場での扱いが大きく縮小。",
            ),
        }
        headline, reasoning = templates.get(
            series.trend_classification,
            (
                f"{persona.focus_interest} 議題のトレンド",
                f"(rule-based) {persona.focus_interest} 関連議題の動向を表示しています ({reason})。",
            ),
        )
        # データ不足の場合は専用 messaging
        if reason == "insufficient_data":
            headline = "データ不足のため予測なし"
            reasoning = (
                f"(rule-based) {persona.focus_interest} 関連の月別データが不足しているため、"
                f"信頼できる予測を提示できません。期間を伸ばすか別の関心軸をお試しください。"
            )
        return ForecastNarrative(
            headline=headline[:40],
            reasoning=reasoning[:240],
            source="rule_based",
        )
