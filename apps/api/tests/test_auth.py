"""認証・認可 (_resolve_user) のテスト: demo mode (既定) と firebase mode。

firebase_admin は実インストール不要 — _verify_firebase_id_token を monkeypatch する。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException


def test_demo_mode_requires_matching_x_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main

    monkeypatch.setattr(api_main, "AUTH_MODE", "demo")
    # 一致 → OK (uid=user_id を返す)
    assert api_main._resolve_user("u1", None, "u1") == "u1"
    # 不一致 → 403
    with pytest.raises(HTTPException) as ei:
        api_main._resolve_user("u1", None, "attacker")
    assert ei.value.status_code == 403
    # 欠落 → 403
    with pytest.raises(HTTPException) as ei2:
        api_main._resolve_user("u1", None, None)
    assert ei2.value.status_code == 403


def test_firebase_mode_verifies_token_and_binds_uid(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main

    monkeypatch.setattr(api_main, "AUTH_MODE", "firebase")
    # トークン検証を差し替え: "good-token" → uid="u1"
    monkeypatch.setattr(
        api_main,
        "_verify_firebase_id_token",
        lambda tok: "u1" if tok == "good-token" else (_ for _ in ()).throw(ValueError("bad")),
    )

    # 正当トークン + path 一致 → uid 返却
    assert api_main._resolve_user("u1", "Bearer good-token", None) == "u1"


def test_firebase_mode_rejects_missing_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main

    monkeypatch.setattr(api_main, "AUTH_MODE", "firebase")
    with pytest.raises(HTTPException) as ei:
        api_main._resolve_user("u1", None, "u1")  # x-user-id は firebase mode で無視される
    assert ei.value.status_code == 401


def test_firebase_mode_rejects_invalid_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api import main as api_main

    monkeypatch.setattr(api_main, "AUTH_MODE", "firebase")
    monkeypatch.setattr(
        api_main,
        "_verify_firebase_id_token",
        lambda tok: (_ for _ in ()).throw(ValueError("invalid")),
    )
    with pytest.raises(HTTPException) as ei:
        api_main._resolve_user("u1", "Bearer garbage", None)
    assert ei.value.status_code == 401


def test_firebase_mode_rejects_uid_mismatch_idor(monkeypatch: pytest.MonkeyPatch) -> None:
    """本人確認済みでも path user_id と uid が違えば 403 (IDOR 防止の核心)。"""
    from apps.api import main as api_main

    monkeypatch.setattr(api_main, "AUTH_MODE", "firebase")
    monkeypatch.setattr(api_main, "_verify_firebase_id_token", lambda tok: "victim")
    with pytest.raises(HTTPException) as ei:
        # 攻撃者は自分の有効トークンで victim の path を叩く → uid("victim"? no) 実際は uid=victim
        # ここでは token→uid=victim だが path=other なので拒否されることを確認
        api_main._resolve_user("other-user", "Bearer attacker-valid-token", None)
    assert ei.value.status_code == 403
