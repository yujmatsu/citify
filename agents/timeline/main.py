"""TimelineAgent: 候補 speeches を受けて議論変遷ナラティブを生成 (Plan N)。

Gemini Flash + Chain-of-Thought、LLM 失敗時 / 倫理 leak / 捏造 source_speech_id 検出時は
raw 上位 5 speeches を date 順で並べた rule-based fallback に degrade。
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from typing import Any, Protocol

from .prompts.system import (
    TIMELINE_PROMPT_VERSION,
    TIMELINE_SYSTEM_PROMPT,
    build_timeline_user_prompt,
    format_candidate_line,
)
from .schema import (
    CandidateSpeech,
    TimelineEvent,
    TimelineNarrative,
    TimelineRequest,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_OUTPUT_TOKENS = 2048  # narrative 240 + events 10 × ~150 ≈ 1800
DEFAULT_THINKING_BUDGET = 512  # Chain-of-Thought (グルーピング + 重要度判定) 用

# 縮退判定閾値: valid event がこの件数未満なら fallback
MIN_VALID_EVENTS = 3

# Reviewer Critical #1: 政治家名 / 政党名 leak 検出 (FORBIDDEN_PATTERNS と独立、Timeline 専用)
POLITICAL_PERSON_PATTERNS: list[re.Pattern[str]] = [
    # 「○○議員/首相/総理/大臣/長官/知事/市長/町長/村長/区長」(2-4 字の漢字 + 役職)
    re.compile(r"[一-鿿]{2,4}(議員|首相|総理|大臣|長官|知事|市長|町長|村長|区長)"),
    # 「○○氏 / さん」(個人名末尾)
    re.compile(r"[一-鿿]{2,4}(氏|さん)"),
    # 主要政党名
    re.compile(
        r"(自民党|立憲民主党|公明党|国民民主党|共産党|維新の会|社民党|れいわ|参政党|N国|無所属)"
    ),
]

# 役職名そのもの (個人名の prefix 判定から除外、PROJECT.md §5 の「役職表現は OK」と整合)
_ROLE_ONLY_PREFIXES: tuple[str, ...] = (
    "総理",
    "副総",
    "首相",
    "副首",
    "国務",
    "厚生",
    "農林",
    "経済",
    "総務",
    "文部",
    "外務",
    "防衛",
    "内閣",
    "副大",
    "副議",
    "副市",
    "副区",
    "副知",
)


def _detect_political_leak(text: str) -> str | None:
    """text に政治家名/政党名 leak が含まれていれば最初の match を返す。

    matched が標準役職名そのもの (「総理大臣」「副市長」等) で始まる場合は除外。
    """
    for pattern in POLITICAL_PERSON_PATTERNS:
        for m in pattern.finditer(text):
            matched = m.group()
            # 役職名で始まる場合 (e.g. "総理大臣") は除外、個人名 + 役職 (e.g. "石破総理") のみ flag
            if any(matched.startswith(role) for role in _ROLE_ONLY_PREFIXES):
                continue
            return matched
    return None


class _GenAIClientProto(Protocol):
    """テスト用 mock 用 minimal interface。"""

    models: Any


class TimelineAgent:
    """議論タイムライン Agent (Plan N、独立 Agent)。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = TIMELINE_PROMPT_VERSION,
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
        candidates: list[CandidateSpeech],
        request: TimelineRequest,
        period_start: date,
        period_end: date,
    ) -> TimelineNarrative:
        """候補 speeches から議論変遷ナラティブを生成。失敗時は rule-based fallback。"""
        # データ不足 (Reviewer 想定ケース)
        if len(candidates) < 3:
            logger.info(
                "timeline.insufficient_candidates user_id=%s interest=%s n=%d",
                request.user_id,
                request.theme_interest,
                len(candidates),
            )
            return TimelineNarrative(
                theme_label=request.theme_interest,
                period_start=period_start,
                period_end=period_end,
                overall_summary="この期間・条件では議論データが不足しています。期間を伸ばすか別の関心軸をお試しください。",
                events=[],
                source="rule_based",
            )

        # LLM call
        try:
            narrative = self._call_gemini(candidates, request, period_start, period_end)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "timeline.llm_failed user_id=%s interest=%s err=%s",
                request.user_id,
                request.theme_interest,
                exc,
            )
            return self._rule_based_fallback(
                candidates, request, period_start, period_end, reason="llm_failed"
            )

        # Reviewer High #4: source_speech_id 捏造防止
        candidate_ids = {c.speech_id for c in candidates}
        valid_events = [e for e in narrative.events if e.source_speech_id in candidate_ids]

        # 倫理 post-validation (overall_summary + 全 event 各フィールド)
        all_texts = [narrative.overall_summary] + [
            t for e in valid_events for t in (e.headline, e.detail)
        ]
        for text in all_texts:
            leaked = _detect_political_leak(text)
            if leaked:
                logger.warning(
                    "timeline.political_leak user_id=%s leaked=%s",
                    request.user_id,
                    leaked,
                )
                return self._rule_based_fallback(
                    candidates,
                    request,
                    period_start,
                    period_end,
                    reason="political_leak",
                )

        # 縮退ケース: 3 件未満なら fallback
        if len(valid_events) < MIN_VALID_EVENTS:
            logger.warning(
                "timeline.too_few_valid_events user_id=%s n_valid=%d n_total=%d",
                request.user_id,
                len(valid_events),
                len(narrative.events),
            )
            return self._rule_based_fallback(
                candidates,
                request,
                period_start,
                period_end,
                reason="too_few_valid_events",
            )

        narrative.events = valid_events
        narrative.source = "llm"
        logger.info(
            "timeline.done user_id=%s interest=%s n_events=%d prompt_version=%s",
            request.user_id,
            request.theme_interest,
            len(valid_events),
            self.prompt_version,
        )
        return narrative

    def _call_gemini(
        self,
        candidates: list[CandidateSpeech],
        request: TimelineRequest,
        period_start: date,
        period_end: date,
    ) -> TimelineNarrative:
        """Gemini に Chain-of-Thought ナラティブ生成を依頼。"""
        from google.genai import types

        client = self._ensure_client()
        candidates_text = "\n".join(
            format_candidate_line(
                idx=i + 1,
                speech_id=c.speech_id,
                meeting_date_iso=(c.meeting_date.isoformat() if c.meeting_date else "(date不明)"),
                municipality_name=c.municipality_name or f"自治体{c.municipality_code}",
                title=c.title[:80],
                summary_first_line=c.summary_first_line[:120],
                speaker_position=c.speaker_position,
            )
            for i, c in enumerate(candidates[:30])
        )
        user_prompt = build_timeline_user_prompt(
            theme_interest=request.theme_interest,
            municipality_code=request.municipality_code,
            period_start_iso=period_start.isoformat(),
            period_end_iso=period_end.isoformat(),
            candidates_text=candidates_text,
        )

        config_kwargs: dict[str, object] = {
            "system_instruction": TIMELINE_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": TimelineNarrative,
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
        if parsed is not None and isinstance(parsed, TimelineNarrative):
            return parsed

        text = getattr(response, "text", "") or ""
        if not text:
            raise RuntimeError("Gemini returned empty response")
        return TimelineNarrative.model_validate_json(text)

    def _rule_based_fallback(
        self,
        candidates: list[CandidateSpeech],
        request: TimelineRequest,
        period_start: date,
        period_end: date,
        reason: str,
    ) -> TimelineNarrative:
        """raw 上位 5 candidates を date 順に並べた timeline。LLM 失敗時に degrade。"""
        # date 順、relevance_score 降順で上位 5 件
        sorted_cs = sorted(
            candidates,
            key=lambda c: (
                c.meeting_date or datetime.now(UTC).date(),
                -c.relevance_score,
            ),
        )[:5]

        events = [
            TimelineEvent(
                event_date=c.meeting_date or period_end,
                municipality_code=c.municipality_code,
                municipality_name=c.municipality_name or f"自治体{c.municipality_code}",
                headline=c.title[:40] or "(タイトル不明)",
                detail=c.summary_first_line[:80] or "(要約なし)",
                source_speech_id=c.speech_id,
                importance=50,
            )
            for c in sorted_cs
        ]

        return TimelineNarrative(
            theme_label=request.theme_interest,
            period_start=period_start,
            period_end=period_end,
            overall_summary=(
                f"(rule-based fallback: {reason}) "
                f"Agent ナラティブ生成は利用できなかったため、関連発言の生 data を時系列順に表示しています。"
            ),
            events=events,
            source="rule_based",
        )
