"""/related の source_uri → (speech_id, source) 解決 (_parse_rag_source_uri) のテスト。"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("uri", "expected"),
    [
        ("gs://citify-dev-rag-staging/kokkai/12232-press.txt", ("12232-press", "kokkai")),
        ("gs://b/kaigiroku_net/33100%3A177%3A4%3A0.txt", ("33100:177:4:0", "kaigiroku_net")),
        ("gs://b/file.txt", ("file", None)),  # source prefix 無し → source=None
        ("", (None, None)),
        ("gs://b/kokkai/no-ext", ("no-ext", "kokkai")),
    ],
)
def test_parse_rag_source_uri(uri: str, expected: tuple[str | None, str | None]) -> None:
    from apps.api.main import _parse_rag_source_uri

    assert _parse_rag_source_uri(uri) == expected
