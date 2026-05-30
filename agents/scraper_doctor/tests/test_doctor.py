"""DiagnosticAgent + RepairProposalAgent tests (Plan F Phase 2.5)。"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.scraper_doctor.main import (
    _CATEGORY_TO_DEFAULT_ACTION,
    DiagnosticAgent,
    RepairProposalAgent,
    _classify_error_type,
)
from agents.scraper_doctor.schema import (
    DiagnosticResult,
    RepairProposal,
    ScraperFailureLog,
)


def _make_failure(
    error_type: str = "SSLError",
    scraper: str = "kaigiroku_net",
    stack_trace: str = "Traceback at line 42",
    html_snippet: str = "<div><span>error page</span></div>",
) -> ScraperFailureLog:
    return ScraperFailureLog(
        failure_id="kaigiroku_net__2026-03-25T00:00:00__0001",
        timestamp=datetime(2026, 3, 25),
        scraper=scraper,  # type: ignore[arg-type]
        tenant_id="prefokayama",
        municipality_code="33101",
        url="https://example.lg.jp/council/",
        error_type=error_type,
        stack_trace=stack_trace,
        html_snippet=html_snippet,
        html_signature="abc123",
    )


def _mock_diagnostic_result(
    category: str = "ssl_failure",
    root_cause: str = "SSL証明書失効によるTLS hand-shake失敗",
    source: str = "llm",
) -> DiagnosticResult:
    return DiagnosticResult(
        error_category=category,  # type: ignore[arg-type]
        root_cause_text=root_cause,
        confidence="high",
        severity="high",
        source=source,  # type: ignore[arg-type]
    )


def _mock_repair_proposal(
    action: str = "manual_review",
    rationale: str = "SSL証明書の手動更新が必要",
    code_hint: str = "scraper の verify=False は使わず、証明書 chain を確認",
    risk: str = "moderate",
    source: str = "llm",
) -> RepairProposal:
    return RepairProposal(
        proposed_action=action,  # type: ignore[arg-type]
        rationale=rationale,
        code_hint=code_hint,
        risk_assessment=risk,  # type: ignore[arg-type]
        requires_human_review=True,
        source=source,  # type: ignore[arg-type]
    )


# ============================================================================
# 1) DiagnosticAgent: LLM 成功 path → source="llm"
# ============================================================================


def test_diagnostic_returns_llm_result_on_success() -> None:
    expected = _mock_diagnostic_result()
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=expected, text="")

    agent = DiagnosticAgent(client=client)
    result = agent.diagnose(_make_failure())
    assert result.source == "llm"
    assert result.error_category == "ssl_failure"


# ============================================================================
# 2) DiagnosticAgent: LLM 失敗 → rule_based fallback (error_type 推定)
# ============================================================================


def test_diagnostic_falls_back_on_llm_exception() -> None:
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("Gemini timeout")

    agent = DiagnosticAgent(client=client)
    result = agent.diagnose(_make_failure(error_type="HTTPError 403"))
    assert result.source == "rule_based"
    assert result.error_category == "auth_403"
    assert "(rule-based)" in result.root_cause_text
    assert "llm_failed" in result.root_cause_text


# ============================================================================
# 3) DiagnosticAgent: leak 検出 (Reviewer High #2) → fallback
# ============================================================================


def test_diagnostic_falls_back_on_political_leak() -> None:
    leaky = _mock_diagnostic_result(
        root_cause="石破総理が新しい規制を発表したため、scraper がブロックされた",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky, text="")

    agent = DiagnosticAgent(client=client)
    result = agent.diagnose(_make_failure())
    assert result.source == "rule_based"
    assert "石破総理" not in result.root_cause_text


def test_diagnostic_falls_back_on_prefecture_leak() -> None:
    leaky = _mock_diagnostic_result(
        root_cause="東京都の議会サイトで SSL 証明書が失効",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky, text="")

    agent = DiagnosticAgent(client=client)
    result = agent.diagnose(_make_failure())
    assert result.source == "rule_based"
    assert "東京都" not in result.root_cause_text


# ============================================================================
# 4) RepairProposalAgent: LLM 成功 → source="llm" + requires_human_review=True 強制
# ============================================================================


def test_repair_returns_llm_proposal_on_success() -> None:
    expected = _mock_repair_proposal()
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=expected, text="")

    agent = RepairProposalAgent(client=client)
    result = agent.propose(_mock_diagnostic_result(), _make_failure())
    assert result.source == "llm"
    assert result.requires_human_review is True  # 構造的に True 強制


def test_repair_forces_requires_human_review_even_if_llm_returns_false() -> None:
    """LLM が requires_human_review=False を返してもサーバー側で True に強制 (構造防止)。"""
    sneaky = _mock_repair_proposal()
    sneaky.requires_human_review = False  # LLM が False にしても...

    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=sneaky, text="")

    agent = RepairProposalAgent(client=client)
    result = agent.propose(_mock_diagnostic_result(), _make_failure())
    assert result.requires_human_review is True  # 強制 True


# ============================================================================
# 5) RepairProposalAgent: LLM 失敗 → rule_based fallback
# ============================================================================


def test_repair_falls_back_on_llm_exception() -> None:
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("API down")

    agent = RepairProposalAgent(client=client)
    diagnostic = _mock_diagnostic_result(category="auth_403")
    result = agent.propose(diagnostic, _make_failure())
    assert result.source == "rule_based"
    assert result.proposed_action == "user_agent_change"  # category マッピング
    assert "(rule-based)" in result.rationale


# ============================================================================
# 6) RepairProposalAgent: leak in rationale → fallback
# ============================================================================


def test_repair_falls_back_on_leak_in_rationale() -> None:
    leaky = _mock_repair_proposal(
        rationale="新宿区の HTML 構造変更に対応するため parser を更新",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky, text="")

    agent = RepairProposalAgent(client=client)
    result = agent.propose(_mock_diagnostic_result(), _make_failure())
    assert result.source == "rule_based"
    assert "新宿区" not in result.rationale


def test_repair_falls_back_on_leak_in_code_hint() -> None:
    """code_hint への leak も検出されて fallback (Reviewer High #2)。"""
    leaky = _mock_repair_proposal(
        code_hint="scrapers/kaigiroku_net/client.py の横浜市処理を更新",
    )
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=leaky, text="")

    agent = RepairProposalAgent(client=client)
    result = agent.propose(_mock_diagnostic_result(), _make_failure())
    assert result.source == "rule_based"
    assert "横浜市" not in result.code_hint


# ============================================================================
# 7) _classify_error_type rule_based マッピング
# ============================================================================


def test_classify_error_type_known_keywords() -> None:
    assert _classify_error_type("SSLError") == "ssl_failure"
    assert _classify_error_type("HTTPError 403: Forbidden") == "auth_403"
    assert _classify_error_type("HTTPError 429 Too Many") == "rate_limit"
    assert _classify_error_type("ConnectionTimeout after 30s") == "network_timeout"
    assert _classify_error_type("KeyError: 'title'") == "parser_logic"
    assert _classify_error_type("AttributeError on NoneType") == "html_structure_change"


def test_classify_error_type_unknown_returns_unknown() -> None:
    assert _classify_error_type("WeirdCustomError") == "unknown"


# ============================================================================
# 8) _CATEGORY_TO_DEFAULT_ACTION マッピング完全性
# ============================================================================


def test_category_to_default_action_covers_all_categories() -> None:
    """8 つの error_category 全てに default action が定義されている。"""
    all_categories = [
        "ssl_failure",
        "auth_403",
        "html_structure_change",
        "robots_disallow",
        "network_timeout",
        "rate_limit",
        "parser_logic",
        "unknown",
    ]
    for cat in all_categories:
        assert cat in _CATEGORY_TO_DEFAULT_ACTION


# ============================================================================
# 9) RepairProposal schema 強制: requires_human_review default=True
# ============================================================================


def test_repair_proposal_schema_default_requires_human_review_true() -> None:
    """RepairProposal を最小引数で作っても requires_human_review=True (Auto-PR 構造防止)。"""
    proposal = RepairProposal(
        proposed_action="user_agent_change",
        rationale="テスト",
        risk_assessment="safe",
    )
    assert proposal.requires_human_review is True
