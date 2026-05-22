"""Phase X リアクション永続化 endpoint のユニットテスト (Firestore mock)。

Tests cover:
    - GET 未設定時 reaction=None
    - GET 設定済 → reaction が読み出せる
    - PUT 新規 → set 呼ばれる + reaction 反映
    - PUT 不正絵文字 → 400
    - PUT 上書き (既存 doc) → created_at は再設定されない
    - DELETE → delete 呼ばれる (存在しなくても 200)
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# google.cloud.firestore モジュールをスタブ化 (実 SDK 未インストール環境でも動作)
# pytest collection 前に sys.modules へ注入
@pytest.fixture(autouse=True)
def _stub_firestore_module(monkeypatch: pytest.MonkeyPatch) -> None:
    if "google.cloud.firestore" not in sys.modules:
        stub = types.ModuleType("google.cloud.firestore")
        stub.SERVER_TIMESTAMP = object()  # sentinel  # type: ignore[attr-defined]
        stub.Client = MagicMock()  # type: ignore[attr-defined]
        sys.modules["google.cloud.firestore"] = stub


@pytest.fixture()
def mock_firestore(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """main._get_firestore_client() を MagicMock に差し替える。

    各 test は returned mock の collection().document() 経由で
    .get() / .set() / .delete() の呼び出しを assert できる。
    """
    import main

    fake_client = MagicMock()
    monkeypatch.setattr(main, "_firestore_client_cache", fake_client)
    return fake_client


@pytest.fixture()
def client() -> TestClient:
    import main

    return TestClient(main.app)


def _setup_doc(
    fake_client: MagicMock, exists: bool, data: dict[str, Any] | None = None
) -> MagicMock:
    """fake_client.collection().document() の get() を設定。"""
    fake_doc_ref = MagicMock()
    fake_snap = MagicMock()
    fake_snap.exists = exists
    fake_snap.to_dict.return_value = data or {}
    fake_doc_ref.get.return_value = fake_snap
    fake_client.collection.return_value.document.return_value = fake_doc_ref
    return fake_doc_ref


# ============================================================================
# GET /v1/speeches/{speech_id}/reaction
# ============================================================================


def test_get_reaction_not_set_returns_null(client: TestClient, mock_firestore: MagicMock) -> None:
    _setup_doc(mock_firestore, exists=False)

    res = client.get("/v1/speeches/sp-1/reaction", params={"user_id": "demo-25-29"})

    assert res.status_code == 200
    body = res.json()
    assert body == {
        "speech_id": "sp-1",
        "user_id": "demo-25-29",
        "reaction": None,
        "updated_at": None,
    }
    mock_firestore.collection.assert_called_with("reactions")
    mock_firestore.collection.return_value.document.assert_called_with("demo-25-29__sp-1")


def test_get_reaction_set_returns_value(client: TestClient, mock_firestore: MagicMock) -> None:
    _setup_doc(
        mock_firestore,
        exists=True,
        data={"reaction": "👍", "user_id": "demo-25-29", "speech_id": "sp-1"},
    )

    res = client.get("/v1/speeches/sp-1/reaction", params={"user_id": "demo-25-29"})

    assert res.status_code == 200
    assert res.json()["reaction"] == "👍"


# ============================================================================
# PUT /v1/speeches/{speech_id}/reaction
# ============================================================================


def test_put_reaction_new_calls_set_with_created_at(
    client: TestClient, mock_firestore: MagicMock
) -> None:
    fake_doc_ref = _setup_doc(mock_firestore, exists=False)

    res = client.put(
        "/v1/speeches/sp-1/reaction",
        params={"user_id": "demo-25-29"},
        json={"reaction": "🔥"},
    )

    assert res.status_code == 200
    assert res.json()["reaction"] == "🔥"

    # set が呼ばれ、新規なので created_at がセットされる
    assert fake_doc_ref.set.called
    payload, kwargs = fake_doc_ref.set.call_args
    payload_dict = payload[0]
    assert payload_dict["reaction"] == "🔥"
    assert payload_dict["user_id"] == "demo-25-29"
    assert payload_dict["speech_id"] == "sp-1"
    assert "created_at" in payload_dict
    assert "updated_at" in payload_dict
    assert kwargs.get("merge") is True


def test_put_reaction_update_existing_no_created_at(
    client: TestClient, mock_firestore: MagicMock
) -> None:
    fake_doc_ref = _setup_doc(
        mock_firestore,
        exists=True,
        data={"reaction": "🤔", "user_id": "demo-25-29", "speech_id": "sp-1"},
    )

    res = client.put(
        "/v1/speeches/sp-1/reaction",
        params={"user_id": "demo-25-29"},
        json={"reaction": "👍"},
    )

    assert res.status_code == 200
    payload_dict = fake_doc_ref.set.call_args[0][0]
    assert payload_dict["reaction"] == "👍"
    # 上書き時は created_at は再設定しない
    assert "created_at" not in payload_dict


def test_put_reaction_invalid_emoji_returns_400(
    client: TestClient, mock_firestore: MagicMock
) -> None:
    _setup_doc(mock_firestore, exists=False)

    res = client.put(
        "/v1/speeches/sp-1/reaction",
        params={"user_id": "demo-25-29"},
        json={"reaction": "💩"},
    )

    assert res.status_code == 400
    assert "must be one of" in res.json()["detail"]
    assert not mock_firestore.collection.return_value.document.return_value.set.called


# ============================================================================
# DELETE /v1/speeches/{speech_id}/reaction
# ============================================================================


def test_delete_reaction_calls_delete(client: TestClient, mock_firestore: MagicMock) -> None:
    fake_doc_ref = _setup_doc(mock_firestore, exists=True)

    res = client.delete("/v1/speeches/sp-1/reaction", params={"user_id": "demo-25-29"})

    assert res.status_code == 200
    body = res.json()
    assert body["reaction"] is None
    assert fake_doc_ref.delete.called


def test_delete_reaction_idempotent_when_missing(
    client: TestClient, mock_firestore: MagicMock
) -> None:
    fake_doc_ref = _setup_doc(mock_firestore, exists=False)

    res = client.delete("/v1/speeches/sp-1/reaction", params={"user_id": "demo-25-29"})

    # 存在しなくても 200 (delete() の冪等性)
    assert res.status_code == 200
    assert fake_doc_ref.delete.called
