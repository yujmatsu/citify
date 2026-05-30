"""FailureLogRepository tests (Plan F Phase 1.5)。"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from agents.scraper_doctor.firestore_repo import (
    FailureLogRepository,
    compute_html_signature,
    dedupe_by_pattern,
)
from agents.scraper_doctor.schema import ScraperFailureLog


def _make_failure(
    failure_id: str = "kaigiroku_net__2026-03-25T00:00:00__0001",
    scraper: str = "kaigiroku_net",
    error_type: str = "SSLError",
    html_snippet: str | None = "<div><table><tr><td>data</td></tr></table></div>",
    html_signature: str = "",
) -> ScraperFailureLog:
    return ScraperFailureLog(
        failure_id=failure_id,
        timestamp=datetime(2026, 3, 25, 0, 0, 0),
        scraper=scraper,  # type: ignore[arg-type]
        tenant_id="prefokayama",
        municipality_code="33101",
        url="https://example.lg.jp/council/",
        error_type=error_type,
        stack_trace='Traceback (most recent call last):\n  File "x"',
        html_snippet=html_snippet,
        html_signature=html_signature,
    )


# ============================================================================
# 1) compute_html_signature: 同じ tag 構造は同じ hash
# ============================================================================


def test_compute_html_signature_consistent_for_same_structure() -> None:
    a = "<div><span>foo</span></div>"
    b = "<div><span>bar</span></div>"  # 中身違い、タグ構造同じ
    assert compute_html_signature(a) == compute_html_signature(b)


def test_compute_html_signature_differs_for_different_structure() -> None:
    a = "<div><span>foo</span></div>"
    b = "<div><table><tr></tr></table></div>"
    assert compute_html_signature(a) != compute_html_signature(b)


def test_compute_html_signature_handles_empty() -> None:
    assert compute_html_signature("") == ""
    assert compute_html_signature(None) == ""


def test_compute_html_signature_length_is_16() -> None:
    sig = compute_html_signature("<div></div>")
    assert len(sig) == 16


# ============================================================================
# 2) FailureLogRepository.save_failure: PII マスク + signature 計算
# ============================================================================


def test_save_failure_applies_pii_mask_and_signature() -> None:
    """save 前に html_snippet/stack_trace に PII が混入していてもマスクされる。"""
    mock_doc = MagicMock()
    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_doc
    mock_client = MagicMock()
    mock_client.collection.return_value = mock_collection

    repo = FailureLogRepository(firestore_client=mock_client)

    failure = _make_failure(
        html_snippet="<form>email=foo@bar.com phone=03-1234-5678</form>",
    )
    failure_id = repo.save_failure(failure)
    assert failure_id == failure.failure_id

    # mock_doc.set に渡された dict を取り出し、PII がマスクされていることを確認
    assert mock_doc.set.called
    saved_data = mock_doc.set.call_args[0][0]
    assert "foo@bar.com" not in saved_data["html_snippet"]
    assert "03-1234-5678" not in saved_data["html_snippet"]
    assert "[email]" in saved_data["html_snippet"]
    assert "[phone]" in saved_data["html_snippet"]
    # signature が再計算されている
    assert len(saved_data["html_signature"]) == 16


def test_save_failure_graceful_on_firestore_exception() -> None:
    """Firestore set 失敗時も例外を投げず、failure_id を返す (graceful)。"""
    mock_client = MagicMock()
    mock_client.collection.side_effect = RuntimeError("Firestore down")

    repo = FailureLogRepository(firestore_client=mock_client)
    failure = _make_failure()
    failure_id = repo.save_failure(failure)
    # 例外なく failure_id が返る
    assert failure_id == failure.failure_id


# ============================================================================
# 3) dedupe_by_pattern: (scraper, error_type, html_signature) で重複排除
# ============================================================================


def test_dedupe_by_pattern_groups_same_signature() -> None:
    f1 = _make_failure(
        failure_id="kaigiroku_net__t1__0001",
        html_signature="sig123",
    )
    f2 = _make_failure(
        failure_id="kaigiroku_net__t2__0002",
        html_signature="sig123",  # 同じ signature
    )
    f3 = _make_failure(
        failure_id="kaigiroku_net__t3__0003",
        html_signature="sig999",  # 異なる
    )
    result = dedupe_by_pattern([f1, f2, f3])
    assert len(result) == 2  # sig123 1件 + sig999 1件


def test_dedupe_by_pattern_distinguishes_different_scrapers() -> None:
    f1 = _make_failure(scraper="kaigiroku_net", html_signature="sig")
    f2 = _make_failure(scraper="kokkai", html_signature="sig")  # 異なる scraper
    result = dedupe_by_pattern([f1, f2])
    assert len(result) == 2


# ============================================================================
# 4) load_sample_seed: 存在しないパスでも graceful (空 list)
# ============================================================================


def test_load_sample_seed_returns_empty_when_file_missing(tmp_path) -> None:
    """ファイルが存在しない場合は空 list を返す。"""
    repo = FailureLogRepository(firestore_client=MagicMock())
    result = repo.load_sample_seed(path=tmp_path / "missing.json")
    assert result == []
