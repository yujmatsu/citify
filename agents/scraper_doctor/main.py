"""Scraper Doctor Agents (Plan F): DiagnosticAgent + RepairProposalAgent。

2 段階構成 (Plan X / Z と一貫):
    - DiagnosticAgent: 失敗ログ → error_category + root_cause + severity
    - RepairProposalAgent: diagnostic → 修正提案 (人間レビュー前提、Auto-PR 構造防止)

倫理ガード:
    - 両 Agent 出力で _detect_any_leak (Plan Z 流用、47 県 + 主要市区 + 政治家/政党) を実行
    - leak 検出時は rule_based fallback (leaked 文字列はユーザー向け文に残らない)
    - RepairProposal.requires_human_review=True は schema 既定で強制
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from agents.forecast.main import _detect_any_leak

from .pii import mask_pii
from .prompts.system import (
    DIAGNOSTIC_PROMPT_VERSION,
    DIAGNOSTIC_SYSTEM_PROMPT,
    REPAIR_PROMPT_VERSION,
    REPAIR_SYSTEM_PROMPT,
    build_diagnostic_user_prompt,
    build_repair_user_prompt,
)
from .schema import (
    DiagnosticResult,
    ErrorCategory,
    ProposedAction,
    RepairProposal,
    ScraperFailureLog,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_OUTPUT_TOKENS = 1024
DEFAULT_THINKING_BUDGET = 256


# error_type → error_category 簡易マッピング (rule_based fallback 用)
_ERROR_TYPE_TO_CATEGORY: dict[str, ErrorCategory] = {
    "SSLError": "ssl_failure",
    "CertificateError": "ssl_failure",
    "HTTPError 403": "auth_403",
    "Forbidden": "auth_403",
    "HTTPError 429": "rate_limit",
    "TooManyRequests": "rate_limit",
    "ConnectionTimeout": "network_timeout",
    "ReadTimeout": "network_timeout",
    "DNSError": "network_timeout",
    "ParserError": "parser_logic",
    "KeyError": "parser_logic",
    "IndexError": "parser_logic",
    "TypeError": "parser_logic",
    "AttributeError": "html_structure_change",
    "RobotsDisallowed": "robots_disallow",
}


def _classify_error_type(error_type: str) -> ErrorCategory:
    """error_type 文字列から rule_based に error_category を推定。"""
    for keyword, category in _ERROR_TYPE_TO_CATEGORY.items():
        if keyword.lower() in error_type.lower():
            return category
    return "unknown"


class _GenAIClientProto(Protocol):
    """テスト用 mock 用 minimal interface。"""

    models: Any


# ============================================================================
# DiagnosticAgent
# ============================================================================


class DiagnosticAgent:
    """失敗ログ → error_category + root_cause + severity (Plan F の 1/2)。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = DIAGNOSTIC_PROMPT_VERSION,
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

    def diagnose(self, failure: ScraperFailureLog) -> DiagnosticResult:
        """失敗を診断。LLM 失敗時 / leak 時は rule_based fallback。"""
        try:
            result = self._call_gemini(failure)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "doctor.diagnostic_llm_failed scraper=%s err=%s",
                failure.scraper,
                exc,
            )
            return self._rule_based(failure, reason="llm_failed")

        # 倫理 post-validation (Reviewer High #2)
        leaked = _detect_any_leak(result.root_cause_text)
        if leaked:
            logger.warning(
                "doctor.diagnostic_leak scraper=%s leaked=%s",
                failure.scraper,
                leaked,
            )
            return self._rule_based(failure, reason="ethics_leak")

        result.source = "llm"
        logger.info(
            "doctor.diagnostic_done scraper=%s category=%s severity=%s",
            failure.scraper,
            result.error_category,
            result.severity,
        )
        return result

    def _call_gemini(self, failure: ScraperFailureLog) -> DiagnosticResult:
        from google.genai import types

        client = self._ensure_client()
        # PII 最終マスク (二重防御、storage 側で済んでいる前提だが念のため)
        user_prompt = build_diagnostic_user_prompt(
            scraper=failure.scraper,
            error_type=failure.error_type,
            stack_trace=mask_pii(failure.stack_trace),
            html_snippet=mask_pii(failure.html_snippet),
            url=failure.url,
        )

        config_kwargs: dict[str, object] = {
            "system_instruction": DIAGNOSTIC_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": DiagnosticResult,
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
        if parsed is not None and isinstance(parsed, DiagnosticResult):
            return parsed
        text = getattr(response, "text", "") or ""
        if not text:
            raise RuntimeError("Gemini returned empty diagnostic response")
        return DiagnosticResult.model_validate_json(text)

    def _rule_based(self, failure: ScraperFailureLog, reason: str) -> DiagnosticResult:
        """LLM 失敗時 / leak 時の fallback。error_type から推定。"""
        category = _classify_error_type(failure.error_type)
        severity_map: dict[ErrorCategory, str] = {
            "ssl_failure": "high",
            "auth_403": "high",
            "html_structure_change": "high",
            "robots_disallow": "medium",
            "network_timeout": "low",
            "rate_limit": "medium",
            "parser_logic": "medium",
            "unknown": "medium",
        }
        return DiagnosticResult(
            error_category=category,
            root_cause_text=(
                f"(rule-based) error_type='{failure.error_type}' から {category} と推定。({reason})"
            )[:240],
            confidence="low",
            severity=severity_map.get(category, "medium"),  # type: ignore[arg-type]
            source="rule_based",
        )


# ============================================================================
# RepairProposalAgent
# ============================================================================


# error_category → 推奨 action のデフォルトマッピング (rule_based fallback 用)
_CATEGORY_TO_DEFAULT_ACTION: dict[ErrorCategory, ProposedAction] = {
    "ssl_failure": "manual_review",
    "auth_403": "user_agent_change",
    "html_structure_change": "parser_path_update",
    "robots_disallow": "robots_check",
    "network_timeout": "retry_strategy_adjust",
    "rate_limit": "retry_strategy_adjust",
    "parser_logic": "manual_review",
    "unknown": "manual_review",
}


class RepairProposalAgent:
    """diagnostic → 修正提案 (人間レビュー前提、Auto-PR 構造防止) (Plan F の 2/2)。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = REPAIR_PROMPT_VERSION,
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
        diagnostic: DiagnosticResult,
        failure: ScraperFailureLog,
    ) -> RepairProposal:
        """修正提案を生成。LLM 失敗時 / leak 時は rule_based fallback。"""
        try:
            proposal = self._call_gemini(diagnostic, failure)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "doctor.repair_llm_failed scraper=%s err=%s",
                failure.scraper,
                exc,
            )
            return self._rule_based(diagnostic, failure, reason="llm_failed")

        # 倫理 post-validation (Reviewer High #2: rationale + code_hint 両方)
        for text in (proposal.rationale, proposal.code_hint):
            leaked = _detect_any_leak(text)
            if leaked:
                logger.warning(
                    "doctor.repair_leak scraper=%s leaked=%s",
                    failure.scraper,
                    leaked,
                )
                return self._rule_based(diagnostic, failure, reason="ethics_leak")

        # **構造的安全性: requires_human_review は LLM が変更してもサーバー側で True に強制**
        proposal.requires_human_review = True
        proposal.source = "llm"
        logger.info(
            "doctor.repair_done scraper=%s action=%s risk=%s",
            failure.scraper,
            proposal.proposed_action,
            proposal.risk_assessment,
        )
        return proposal

    def _call_gemini(
        self,
        diagnostic: DiagnosticResult,
        failure: ScraperFailureLog,
    ) -> RepairProposal:
        from google.genai import types

        client = self._ensure_client()
        user_prompt = build_repair_user_prompt(
            scraper=failure.scraper,
            error_category=diagnostic.error_category,
            root_cause=diagnostic.root_cause_text,
            tenant_id=failure.tenant_id,
        )

        config_kwargs: dict[str, object] = {
            "system_instruction": REPAIR_SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_schema": RepairProposal,
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
        if parsed is not None and isinstance(parsed, RepairProposal):
            return parsed
        text = getattr(response, "text", "") or ""
        if not text:
            raise RuntimeError("Gemini returned empty repair response")
        return RepairProposal.model_validate_json(text)

    def _rule_based(
        self,
        diagnostic: DiagnosticResult,
        failure: ScraperFailureLog,
        reason: str,
    ) -> RepairProposal:
        """LLM 失敗時 / leak 時の fallback (category → default action マップ)。"""
        action = _CATEGORY_TO_DEFAULT_ACTION.get(diagnostic.error_category, "manual_review")
        risk_map: dict[ProposedAction, str] = {
            "user_agent_change": "safe",
            "retry_strategy_adjust": "safe",
            "parser_path_update": "moderate",
            "drop_tenant": "moderate",
            "robots_check": "safe",
            "manual_review": "moderate",
        }
        return RepairProposal(
            proposed_action=action,
            rationale=(
                f"(rule-based) error_category='{diagnostic.error_category}' に対する "
                f"デフォルト action='{action}' を提案 ({reason})。"
            )[:240],
            code_hint=(
                f"(rule-based) {failure.scraper} の対応 module を確認し、{action} を実施してください。"
            )[:300],
            risk_assessment=risk_map.get(action, "moderate"),  # type: ignore[arg-type]
            requires_human_review=True,  # 構造的に True 固定
            source="rule_based",
        )
