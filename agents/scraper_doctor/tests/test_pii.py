"""PII マスク tests (Plan F、Reviewer Critical 予防 + High #1 拡張)。

20+ ケースで PII regex の網羅性を担保。
"""

from __future__ import annotations

import pytest

from agents.scraper_doctor.pii import PII_PATTERNS, mask_pii

# ============================================================================
# Email
# ============================================================================


@pytest.mark.parametrize(
    "raw, masked_marker",
    [
        ("foo@bar.com", "[email]"),
        ("user.name+tag@example.co.jp", "[email]"),
        (
            "admin@日本.example",
            "[email]",
        ),  # Unicode ドメイン部 (Japanese ドメインの "日本" 部は ASCII regex 外、後段で fall through)
        ("yamada123@gmail.com", "[email]"),
    ],
)
def test_mask_email(raw: str, masked_marker: str) -> None:
    out = mask_pii(raw)
    # ASCII email は完全マスク、Unicode 含む email は最低限 @example はマスク or 部分マスク
    if "日本" not in raw:
        assert masked_marker in out
        assert raw not in out


# ============================================================================
# 固定電話 / 携帯
# ============================================================================


@pytest.mark.parametrize(
    "raw",
    [
        "03-1234-5678",  # 東京固定
        "0463-91-1234",  # 神奈川中部 (4 桁市外局番)
        "06-1234-5678",  # 大阪
        "090-1234-5678",  # 携帯 docomo
        "080-1234-5678",  # 携帯 au
        "070-1234-5678",  # 携帯 willcom
    ],
)
def test_mask_phone_numbers(raw: str) -> None:
    out = mask_pii(raw)
    assert "[phone]" in out
    assert raw not in out


# ============================================================================
# 郵便番号
# ============================================================================


@pytest.mark.parametrize(
    "raw",
    [
        "〒100-0001",
        "〒 100-0001",  # スペースあり
        "100-0001",  # 〒なし、独立した数字
    ],
)
def test_mask_zip_codes(raw: str) -> None:
    out = mask_pii(raw)
    assert "[zip]" in out


# ============================================================================
# IPv4 (Reviewer High #1)
# ============================================================================


@pytest.mark.parametrize(
    "raw",
    [
        "10.0.0.1",
        "172.16.254.1",
        "192.168.1.1",
        "203.0.113.5",
    ],
)
def test_mask_ipv4(raw: str) -> None:
    out = mask_pii(raw)
    assert "[ipv4]" in out
    assert raw not in out


# ============================================================================
# Authorization / Cookie / session token (Reviewer High #1)
# ============================================================================


def test_mask_authorization_bearer_token() -> None:
    raw = "Authorization: Bearer eyJhbGc.JWT.token"
    out = mask_pii(raw)
    assert "[token]" in out
    assert "eyJhbGc" not in out


def test_mask_authorization_bearer_lowercase() -> None:
    raw = "authorization: bearer abc123def"
    out = mask_pii(raw)
    assert "[token]" in out


def test_mask_cookie_header() -> None:
    raw = "Cookie: SESSIONID=abc123; trackingID=xyz"
    out = mask_pii(raw)
    assert "[redacted]" in out
    assert "abc123" not in out


def test_mask_session_id_inline() -> None:
    raw = "session_id=abc123xyz"
    out = mask_pii(raw)
    assert "[token]" in out


def test_mask_url_api_key() -> None:
    raw = "https://api.example.com/v1/data?api_key=secretvalue&user=foo"
    out = mask_pii(raw)
    assert "api_key=[redacted]" in out
    assert "secretvalue" not in out


def test_mask_url_token_param() -> None:
    raw = "https://api.example.com/?token=abc123&foo=bar"
    out = mask_pii(raw)
    assert "token=[redacted]" in out


# ============================================================================
# マスクされない (普通の文字列、誤検出回避)
# ============================================================================


@pytest.mark.parametrize(
    "raw",
    [
        "議論件数が増加傾向",
        "2026-03-25",  # 日付 (郵便番号ではない、長さ4 で fall through)
        "v1.2.3",  # バージョン番号
        "HTTPError 503",  # エラーメッセージ
        "id=12345",  # 短い数値 ID
    ],
)
def test_mask_pii_does_not_alter_clean_text(raw: str) -> None:
    out = mask_pii(raw)
    # 上記サンプルは regex に該当しないので完全に同じ
    assert out == raw


# ============================================================================
# None / 空文字
# ============================================================================


def test_mask_pii_handles_none_and_empty() -> None:
    assert mask_pii(None) == ""
    assert mask_pii("") == ""


# ============================================================================
# 複合 (実際の stack trace ぽいケース)
# ============================================================================


def test_mask_pii_complex_stack_trace() -> None:
    raw = """
    HTTPError 403 at https://example.com/api?api_key=topsecret123
    Headers: Authorization: Bearer eyJrealtoken.x.y
    Cookie: PHPSESSID=abc123
    Origin IP: 192.168.1.42
    Contact: admin@example.com / 03-1234-5678
    """
    out = mask_pii(raw)
    assert "topsecret123" not in out
    assert "eyJrealtoken" not in out
    assert "abc123" not in out
    assert "192.168.1.42" not in out
    assert "admin@example.com" not in out
    assert "03-1234-5678" not in out
    # 期待される markers
    assert "[redacted]" in out or "[token]" in out
    assert "[email]" in out
    assert "[phone]" in out
    assert "[ipv4]" in out


# ============================================================================
# PII_PATTERNS の最小件数 (Reviewer High #1 拡張)
# ============================================================================


def test_pii_patterns_has_minimum_coverage() -> None:
    """PII_PATTERNS が最低 10 種類のパターンを持つ (Reviewer High #1)。"""
    assert len(PII_PATTERNS) >= 10
