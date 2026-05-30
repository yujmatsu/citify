"""GET /v1/scraper-health endpoint tests (Plan F Phase 3)。"""

from __future__ import annotations

import sys
import types
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _stub_firestore_module() -> None:
    if "google.cloud.firestore" not in sys.modules:
        stub = types.ModuleType("google.cloud.firestore")
        stub.SERVER_TIMESTAMP = object()  # type: ignore[attr-defined]
        stub.Client = MagicMock()  # type: ignore[attr-defined]
        stub.Increment = MagicMock()  # type: ignore[attr-defined]
        sys.modules["google.cloud.firestore"] = stub


def _mock_failure(error_type: str = "SSLError", scraper: str = "kaigiroku_net"):
    from agents.scraper_doctor.schema import ScraperFailureLog

    return ScraperFailureLog(
        failure_id=f"{scraper}__t__0001",
        timestamp=datetime(2026, 5, 25),
        scraper=scraper,  # type: ignore[arg-type]
        tenant_id="prefokayama",
        municipality_code="33101",
        url="https://example.lg.jp/",
        error_type=error_type,
        stack_trace="trace",
        html_snippet="<div></div>",
        html_signature="sig" + error_type[:5],
    )


def _mock_diagnostic(category: str = "ssl_failure"):
    from agents.scraper_doctor.schema import DiagnosticResult

    return DiagnosticResult(
        error_category=category,  # type: ignore[arg-type]
        root_cause_text="SSL証明書失効",
        confidence="high",
        severity="high",
        source="llm",
    )


def _mock_proposal(action: str = "manual_review"):
    from agents.scraper_doctor.schema import RepairProposal

    return RepairProposal(
        proposed_action=action,  # type: ignore[arg-type]
        rationale="証明書更新が必要",
        code_hint="証明書 chain を確認",
        risk_assessment="moderate",
        requires_human_review=True,
        source="llm",
    )


def _setup_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    failures=None,
    diagnostic=None,
    proposal=None,
    fetch_exc: Exception | None = None,
) -> TestClient:
    from apps.api import main as api_main
    from apps.api.main import _SCRAPER_HEALTH_CACHE

    _SCRAPER_HEALTH_CACHE.clear()

    # Repo mock
    mock_repo = MagicMock()
    if fetch_exc is not None:
        mock_repo.fetch_recent.side_effect = fetch_exc
    else:
        mock_repo.fetch_recent.return_value = failures or [_mock_failure()]
        mock_repo.load_sample_seed.return_value = failures or [_mock_failure()]
    monkeypatch.setattr(api_main, "_get_failure_repo", lambda: mock_repo)

    # Diagnostic + Repair agent mock
    mock_diag = MagicMock()
    mock_diag.diagnose.return_value = diagnostic or _mock_diagnostic()
    monkeypatch.setattr(api_main, "_get_diagnostic_agent", lambda: mock_diag)

    mock_repair = MagicMock()
    mock_repair.propose.return_value = proposal or _mock_proposal()
    monkeypatch.setattr(api_main, "_get_repair_agent", lambda: mock_repair)

    return TestClient(api_main.app)


# ============================================================================
# 1) 200 + 構造完備
# ============================================================================


def test_scraper_health_200(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get("/v1/scraper-health", params={"days": 7})
    assert response.status_code == 200
    body = response.json()
    assert "period_start" in body
    assert "period_end" in body
    assert "total_failures" in body
    assert "by_category" in body
    assert "by_scraper" in body
    assert "entries" in body
    assert "drop_candidates" in body
    assert "disclaimer" in body
    assert len(body["entries"]) == 1
    assert body["entries"][0]["proposal"]["requires_human_review"] is True


# ============================================================================
# 2) drop_candidates が proposed_action=drop_tenant から抽出される
# ============================================================================


def test_scraper_health_collects_drop_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(
        monkeypatch,
        failures=[_mock_failure(error_type="HTTPError 403")],
        proposal=_mock_proposal(action="drop_tenant"),
    )
    response = client.get("/v1/scraper-health")
    body = response.json()
    assert body["drop_candidates"] == ["prefokayama"]


# ============================================================================
# 3) Firestore fetch 失敗 → 500
# ============================================================================


def test_scraper_health_500_on_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch, fetch_exc=RuntimeError("Firestore down"))
    response = client.get("/v1/scraper-health")
    assert response.status_code == 500


# ============================================================================
# 4) use_sample=True で sample seed を強制使用
# ============================================================================


def test_scraper_health_use_sample_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """use_sample=true なら load_sample_seed を呼ぶ。"""
    client = _setup_endpoint(monkeypatch)
    response = client.get("/v1/scraper-health", params={"use_sample": "true"})
    assert response.status_code == 200


# ============================================================================
# 5) Agent クラッシュは 1 失敗 skip で全体死しない
# ============================================================================


def test_scraper_health_skips_failed_agent_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """ある failure で Diagnostic が例外を投げても他は処理継続。"""
    from agents.scraper_doctor.schema import ScraperFailureLog

    f1 = _mock_failure(error_type="SSLError")
    f2 = ScraperFailureLog(
        failure_id="ok",
        timestamp=datetime(2026, 5, 26),
        scraper="kokkai",
        tenant_id=None,
        municipality_code="00000",
        url=None,
        error_type="ParserError",
        stack_trace="",
        html_signature="other",
    )

    from apps.api import main as api_main
    from apps.api.main import _SCRAPER_HEALTH_CACHE

    _SCRAPER_HEALTH_CACHE.clear()
    mock_repo = MagicMock()
    mock_repo.fetch_recent.return_value = [f1, f2]
    monkeypatch.setattr(api_main, "_get_failure_repo", lambda: mock_repo)

    # f1 は例外、f2 は成功
    mock_diag = MagicMock()
    mock_diag.diagnose.side_effect = [RuntimeError("oops"), _mock_diagnostic()]
    monkeypatch.setattr(api_main, "_get_diagnostic_agent", lambda: mock_diag)

    mock_repair = MagicMock()
    mock_repair.propose.return_value = _mock_proposal()
    monkeypatch.setattr(api_main, "_get_repair_agent", lambda: mock_repair)

    client = TestClient(api_main.app)
    response = client.get("/v1/scraper-health")
    assert response.status_code == 200
    body = response.json()
    # 1 件は skip された、もう 1 件は成功 → entries は 1 件
    assert len(body["entries"]) == 1


# ============================================================================
# 6) disclaimer がレスポンスに常に含まれる
# ============================================================================


def test_scraper_health_always_includes_disclaimer(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _setup_endpoint(monkeypatch)
    response = client.get("/v1/scraper-health")
    body = response.json()
    assert "自動修正は適用されません" in body["disclaimer"]


# ============================================================================
# 7) Sample seed ファイルから 10 件読める (実 file integration)
# ============================================================================


def test_sample_seed_file_loads_10_failures() -> None:
    """infra/seed/scraper_failures_sample.json から 10 件読める。

    2026-05-30 update: 5 scraper × 2 件 → press_rss 6 件実話 + 他 4 scraper 各 1 件 = 10 件
    (今回の publish-all で観測した実 failure を sample seed に投入、demo 価値向上)。
    """
    from agents.scraper_doctor.firestore_repo import FailureLogRepository

    repo = FailureLogRepository(firestore_client=MagicMock())
    failures = repo.load_sample_seed()
    assert len(failures) == 10

    by_scraper: dict[str, int] = {}
    for f in failures:
        by_scraper[f.scraper] = by_scraper.get(f.scraper, 0) + 1

    # press_rss は実話 6 件 (SSL 3 / HTTP 403 1 / Timeout 1 / HTTP 404 1)
    assert by_scraper.get("press_rss") == 6
    # 他 4 scraper は demo 多様性確保のため各 1 件
    assert by_scraper.get("kaigiroku_net") == 1
    assert by_scraper.get("kokkai") == 1
    assert by_scraper.get("voices_asp") == 1
    assert by_scraper.get("reinfolib") == 1


def test_sample_seed_file_includes_real_publish_all_failures() -> None:
    """sample seed の press_rss 6 件は 2026-05-28 publish-all で観測された実 failure。

    実 publish-all で観測した自治体コード + URL を含むことを確認 (demo 価値の証明)。
    """
    from agents.scraper_doctor.firestore_repo import FailureLogRepository

    repo = FailureLogRepository(firestore_client=MagicMock())
    failures = repo.load_sample_seed()

    # 2026-05-28 publish-all で観測した 9 自治体 + 5-30 新規発見 1 自治体から 6 件選定
    expected_real_munis = {
        "06203",  # 鶴岡市 SSL
        "13213",  # 東村山市 HTTP 403 (UA filter)
        "33203",  # 津山市 ConnectTimeout
        "41201",  # 佐賀市 HTTP 404 (5/30 新規発見)
        "28226",  # 淡路市 SSL
        "43211",  # 宇土市 SSL
    }
    actual_munis = {f.municipality_code for f in failures if f.scraper == "press_rss"}
    assert actual_munis == expected_real_munis
