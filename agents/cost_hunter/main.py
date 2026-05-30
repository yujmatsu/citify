"""CostRootCauseAgent (Plan CC): Cost anomaly に対する LLM 削減提案。

倫理ガード:
    - Plan PP / F と同じ `_detect_any_leak` を rationale + root_cause_hypothesis に適用
    - `requires_human_review=True` schema 強制 (Plan F と同じ構造防止)
    - `monthly_savings_estimate_jpy` を schema le=100_000 + server clamp で二重防御 (Reviewer Critical)
    - `proposed_action=scale_down` + service in (vertex_ai, cloud_run) は自動で risky 上書き (Reviewer High #3)
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from agents.forecast.main import _detect_any_leak

from .prompts.system import (
    ROOT_CAUSE_PROMPT_VERSION,
    ROOT_CAUSE_SYSTEM_PROMPT,
    build_root_cause_user_prompt,
)
from .schema import (
    CostAnomaly,
    CostRootCauseProposal,
    ProposedAction,
    ServiceName,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_OUTPUT_TOKENS = 1024
DEFAULT_THINKING_BUDGET = 256

MAX_MONTHLY_SAVINGS_CAP = 100_000  # Reviewer Critical: schema le + server clamp で二重防御

# Reviewer High #3: scale_down + ユーザー影響大 service の組合せは強制 risky
_USER_IMPACT_SERVICES: tuple[ServiceName, ...] = ("vertex_ai", "cloud_run")


# anomaly_type + service → デフォルト action (rule_based fallback 用)
def _default_action_for(anomaly: CostAnomaly) -> ProposedAction:
    if anomaly.anomaly_type == "normal":
        return "investigate_logs"
    if anomaly.service == "bigquery":
        return "optimize_query"
    if anomaly.service in ("cloud_run", "vertex_ai"):
        if anomaly.spike_ratio >= 2.0:
            return "rate_limit"
        return "investigate_logs"
    if anomaly.service == "firestore":
        return "optimize_query"
    return "manual_review"


class _GenAIClientProto(Protocol):
    """テスト用 mock 用 minimal interface。"""

    models: Any


def _enforce_safety_constraints(
    proposal: CostRootCauseProposal,
    anomaly: CostAnomaly,
) -> CostRootCauseProposal:
    """サーバー側構造防止 (LLM 出力が rule を破ったら上書き)。

    1. monthly_savings_estimate_jpy: 0 以下 / 上限超過を clamp (Reviewer Critical)
    2. requires_human_review=True 強制 (Plan F と同じ)
    3. scale_down + ユーザー影響 service は risky に上書き (Reviewer High #3)
    """
    # 1. savings 上限 clamp
    clamped_savings = max(0, min(proposal.monthly_savings_estimate_jpy, MAX_MONTHLY_SAVINGS_CAP))

    # 2. requires_human_review は常に True (LLM が False を返してもサーバー側 True)
    # 3. scale_down + user impact service は risky 強制
    risk = proposal.risk_assessment
    if proposal.proposed_action == "scale_down" and anomaly.service in _USER_IMPACT_SERVICES:
        risk = "risky"

    return proposal.model_copy(
        update={
            "monthly_savings_estimate_jpy": clamped_savings,
            "requires_human_review": True,
            "risk_assessment": risk,
        }
    )


class CostRootCauseAgent:
    """Cost anomaly に対する LLM 削減提案 Agent。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = ROOT_CAUSE_PROMPT_VERSION,
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

    def propose(
        self,
        anomaly: CostAnomaly,
        trend_summary: str = "",
    ) -> CostRootCauseProposal:
        """Cost anomaly から提案を生成。LLM 失敗 / leak / safety 違反は自動補正。"""
        try:
            proposal = self._call_gemini(anomaly, trend_summary)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "cost_hunter.llm_failed service=%s err=%s",
                anomaly.service,
                exc,
            )
            return self._rule_based(anomaly, reason="llm_failed")

        # 倫理 post-validation (Reviewer 想定)
        for text in (proposal.root_cause_hypothesis, proposal.rationale):
            leaked = _detect_any_leak(text)
            if leaked:
                logger.warning(
                    "cost_hunter.leak_detected service=%s leaked=%s",
                    anomaly.service,
                    leaked,
                )
                return self._rule_based(anomaly, reason="ethics_leak")

        # サーバー側 safety 上書き (Reviewer Critical + High #3)
        enforced = _enforce_safety_constraints(proposal, anomaly)
        enforced.source = "llm"
        logger.info(
            "cost_hunter.done service=%s action=%s savings=¥%d risk=%s",
            anomaly.service,
            enforced.proposed_action,
            enforced.monthly_savings_estimate_jpy,
            enforced.risk_assessment,
        )
        return enforced

    def _call_gemini(
        self,
        anomaly: CostAnomaly,
        trend_summary: str,
    ) -> CostRootCauseProposal:
        from google.genai import types

        client = self._ensure_client()
        user_prompt = build_root_cause_user_prompt(
            service=anomaly.service,
            anomaly_type=anomaly.anomaly_type,
            spike_ratio=anomaly.spike_ratio,
            z_score=anomaly.z_score,
            cost_jpy=anomaly.cost_jpy,
            baseline_avg=anomaly.baseline_avg_7d,
            severity=anomaly.severity,
            trend_summary=trend_summary,
        )

        config_kwargs: dict[str, object] = {
            "system_instruction": ROOT_CAUSE_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": CostRootCauseProposal,
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
        if parsed is not None and isinstance(parsed, CostRootCauseProposal):
            return parsed
        text = getattr(response, "text", "") or ""
        if not text:
            raise RuntimeError("Gemini returned empty cost rootcause response")
        return CostRootCauseProposal.model_validate_json(text)

    def _rule_based(self, anomaly: CostAnomaly, reason: str) -> CostRootCauseProposal:
        """LLM 失敗 / leak 時の rule_based fallback。"""
        action = _default_action_for(anomaly)
        # 安全側: rule_based は savings 推定なし (0)、risky 評価
        risk_assessment = "risky" if action == "scale_down" else "moderate"
        if anomaly.service in _USER_IMPACT_SERVICES and action == "scale_down":
            risk_assessment = "risky"

        proposal = CostRootCauseProposal(
            root_cause_hypothesis=(
                f"(rule-based) {anomaly.service} の {anomaly.anomaly_type} 検出 "
                f"(spike_ratio={anomaly.spike_ratio:.2f}x、severity={anomaly.severity})。"
                f"LLM 診断は利用できなかったため、rule_based mapping を適用 ({reason})。"
            )[:240],
            proposed_action=action,
            rationale=(
                f"(rule-based) {anomaly.service} で {anomaly.anomaly_type} を検出、"
                f"default action='{action}' を提案。詳細は手動調査を推奨。"
            )[:240],
            monthly_savings_estimate_jpy=0,  # rule_based では推定なし
            risk_assessment=risk_assessment,  # type: ignore[arg-type]
            requires_human_review=True,
            source="rule_based",
        )
        # サーバー側 safety を fallback path にも適用 (一貫性)
        return _enforce_safety_constraints(proposal, anomaly)
