"""relevance テスト用 conftest。

dev 環境 (WSL + sandbox) では google.genai パッケージの一部ファイルが読めず
ImportError になるため、本番コードを変更せずに sys.modules にスタブを注入する。
production (Cloud Build / Cloud Run) では実 SDK が使われる。
"""

from __future__ import annotations

import sys
import types as stdlib_types
from unittest.mock import MagicMock


def _ensure_genai_stub() -> None:
    """google.genai が import 不能なら最小限のスタブを sys.modules に登録。"""
    try:
        # 通常 import が通ればスタブ不要
        from google import genai  # noqa: F401
        from google.genai import types  # noqa: F401
    except ImportError:
        # スタブ注入 (dev sandbox)
        genai_stub = stdlib_types.ModuleType("google.genai")
        genai_stub.Client = MagicMock()  # type: ignore[attr-defined]
        sys.modules.setdefault("google.genai", genai_stub)

        types_stub = stdlib_types.ModuleType("google.genai.types")

        # GenerateContentConfig: 属性アクセス対応の namespace
        class _GenerateContentConfig:
            def __init__(self, **kwargs: object) -> None:
                for k, v in kwargs.items():
                    setattr(self, k, v)

        types_stub.GenerateContentConfig = _GenerateContentConfig  # type: ignore[attr-defined]

        # ThinkingConfig: optional に使われる
        class _ThinkingConfig:
            def __init__(self, **kwargs: object) -> None:
                for k, v in kwargs.items():
                    setattr(self, k, v)

        types_stub.ThinkingConfig = _ThinkingConfig  # type: ignore[attr-defined]
        sys.modules.setdefault("google.genai.types", types_stub)


_ensure_genai_stub()
