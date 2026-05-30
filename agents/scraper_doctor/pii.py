"""PII マスク (Plan F、Reviewer Critical 予防 + High #1 拡張)。

LLM に html_snippet / stack_trace を渡す前に必ず mask_pii() を通すこと。
secret token / cookie / personal email / 電話番号 / IP アドレスを構造的に排除。
"""

from __future__ import annotations

import re

# 順序が重要: より具体的なパターンを先に
PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Authorization Bearer / Cookie / session token (Reviewer High #1、最優先で除去)
    (
        re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
        "Authorization: Bearer [token]",
    ),
    (re.compile(r"Cookie:\s*[^\s\n]+", re.IGNORECASE), "Cookie: [redacted]"),
    (re.compile(r"session_id=[A-Za-z0-9._\-]+", re.IGNORECASE), "session_id=[token]"),
    # URL クエリ内の token / api_key / secret
    (
        re.compile(r"([?&])(api[_-]?key|token|secret|password)=[^&\s]+", re.IGNORECASE),
        r"\1\2=[redacted]",
    ),
    # Email
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[email]"),
    # 携帯 (Reviewer High #1、固定電話より先に判定)
    (re.compile(r"0[789]0-\d{4}-\d{4}"), "[phone]"),
    # 固定電話 (市外局番 1-4 桁、合計 10 桁)
    (re.compile(r"\b0\d{1,4}-\d{1,4}-\d{4}\b"), "[phone]"),
    # 〒郵便番号
    (re.compile(r"〒\s*\d{3}-\d{4}"), "[zip]"),
    (re.compile(r"\b\d{3}-\d{4}\b"), "[zip]"),
    # IPv4 (Reviewer High #1)
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ipv4]"),
]


def mask_pii(text: str | None) -> str:
    """text 内の PII を regex でマスクして返す。None は空文字列に。"""
    if not text:
        return ""
    out = text
    for pattern, repl in PII_PATTERNS:
        out = pattern.sub(repl, out)
    return out
