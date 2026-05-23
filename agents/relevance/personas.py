"""personas.json を UserPersona に読み込むユーティリティ (Phase Y)。"""

from __future__ import annotations

import json
from pathlib import Path

from .schema import UserPersona

DEFAULT_PERSONAS_PATH = Path(__file__).parent / "personas.json"


def load_personas(path: str | Path | None = None) -> list[UserPersona]:
    """JSON ファイルから UserPersona のリストを返す。

    Args:
        path: personas.json のパス (None で同ディレクトリの default)

    Returns:
        UserPersona のリスト (定義順)
    """
    p = Path(path) if path else DEFAULT_PERSONAS_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    personas_raw = data.get("personas", [])
    return [
        UserPersona(
            user_id=item["user_id"],
            age_group=item["age_group"],
            interests=item.get("interests", []),
            municipality_codes=item.get("municipality_codes", []),
        )
        for item in personas_raw
    ]
