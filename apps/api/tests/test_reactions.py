"""Phase X リアクション永続化 + Phase X+1 集計 endpoint のユニットテスト。

Tests cover:
    GET reaction:
      - 未設定 → null
      - 設定済 → reaction が読み出せる
    PUT reaction (with counts batch):
      - 新規 → set 呼ばれる + counts.{new}+=1 + total+=1
      - 上書き (異なる絵文字) → counts.{prev}-=1, counts.{new}+=1, total 変わらず
      - 上書き (同じ絵文字) → batch.set は reaction 1 件のみ (counts 触らない)
      - 不正絵文字 → 400
    DELETE reaction (with counts batch):
      - 存在 → reaction delete + counts.{prev}-=1, total-=1
      - 不在 → reaction delete のみ、counts 触らない (idempotent)
    GET reactions/summary:
      - document なし → 全絵文字 0 件 + total=0
      - document あり → そのまま返す + 欠落 emoji は 0 埋め
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


# google.cloud.firestore モジュールをスタブ化 (実 SDK 未インストール環境でも動作)
@pytest.fixture(autouse=True)
def _stub_firestore_module() -> None:
    if "google.cloud.firestore" not in sys.modules:
        stub = types.ModuleType("google.cloud.firestore")
        stub.SERVER_TIMESTAMP = object()  # type: ignore[attr-defined]
        stub.Client = MagicMock()  # type: ignore[attr-defined]

        class _Increment:
            def __init__(self, value: int) -> None:
                self.value = value

            def __eq__(self, other: object) -> bool:
                return isinstance(other, _Increment) and self.value == other.value

            def __repr__(self) -> str:
                return f"Increment({self.value})"

        stub.Increment = _Increment  # type: ignore[attr-defined]
        sys.modules["google.cloud.firestore"] = stub


class _FakeFirestore:
    """test 用 Firestore client mock。

    - reactions / reaction_counts を別 dict で保持
    - get / set / delete をシミュレート
    - batch() を返し、batch.set / batch.delete / batch.commit を記録
    """

    def __init__(self) -> None:
        # collection_name → doc_id → data
        self.docs: dict[str, dict[str, dict[str, Any]]] = {
            "reactions": {},
            "reaction_counts": {},
        }
        # batch 操作履歴 (test 検証用)
        self.batch_ops: list[tuple[str, str, str, dict[str, Any] | None]] = []
        # 直近の batch インスタンス (commit assert 用)
        self.last_batch: MagicMock | None = None

    # ----- public mock API -----

    def collection(self, name: str) -> Any:
        return _FakeCollection(self, name)

    def batch(self) -> Any:
        b = _FakeBatch(self)
        self.last_batch = b  # type: ignore[assignment]
        return b


class _FakeCollection:
    def __init__(self, store: _FakeFirestore, name: str) -> None:
        self.store = store
        self.name = name

    def document(self, doc_id: str) -> Any:
        return _FakeDocRef(self.store, self.name, doc_id)


class _FakeDocRef:
    def __init__(self, store: _FakeFirestore, collection: str, doc_id: str) -> None:
        self.store = store
        self.collection = collection
        self.doc_id = doc_id

    def get(self) -> Any:
        data = self.store.docs[self.collection].get(self.doc_id)
        snap = MagicMock()
        snap.exists = data is not None
        snap.to_dict.return_value = data or {}
        return snap

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        existing = self.store.docs[self.collection].get(self.doc_id, {}) if merge else {}
        merged = {**existing, **payload}
        self.store.docs[self.collection][self.doc_id] = merged

    def delete(self) -> None:
        self.store.docs[self.collection].pop(self.doc_id, None)


class _FakeBatch:
    def __init__(self, store: _FakeFirestore) -> None:
        self.store = store
        self.ops: list[tuple[str, _FakeDocRef, dict[str, Any] | None]] = []
        self.commit = MagicMock(side_effect=self._commit)

    def set(self, ref: _FakeDocRef, payload: dict[str, Any], merge: bool = False) -> None:
        self.ops.append(("set", ref, payload))
        if not merge:
            self.store.docs[ref.collection][ref.doc_id] = {}
        existing = self.store.docs[ref.collection].setdefault(ref.doc_id, {})
        for key, value in payload.items():
            if "." in key:
                # nested field path: e.g. "counts.👍"
                top, _, leaf = key.partition(".")
                bucket = existing.setdefault(top, {})
                bucket[leaf] = _value_or_increment(value, bucket.get(leaf, 0))
            else:
                existing[key] = _value_or_increment(value, existing.get(key, 0))

    def delete(self, ref: _FakeDocRef) -> None:
        self.ops.append(("delete", ref, None))
        self.store.docs[ref.collection].pop(ref.doc_id, None)

    def _commit(self) -> None:
        self.store.batch_ops.extend(
            (op, ref.collection, ref.doc_id, payload) for op, ref, payload in self.ops
        )


def _value_or_increment(value: Any, current: int) -> Any:
    """Increment は値を返す、それ以外は値そのもの (set 時に上書き)。"""
    from google.cloud.firestore import Increment  # type: ignore[attr-defined]

    if isinstance(value, Increment):
        return current + value.value if isinstance(current, int) else value.value
    return value


@pytest.fixture()
def mock_firestore(monkeypatch: pytest.MonkeyPatch) -> _FakeFirestore:
    import main

    fake = _FakeFirestore()
    monkeypatch.setattr(main, "_firestore_client_cache", fake)
    return fake


@pytest.fixture()
def client() -> TestClient:
    import main

    return TestClient(main.app)


# ============================================================================
# GET /v1/speeches/{speech_id}/reaction
# ============================================================================


def test_get_reaction_not_set_returns_null(
    client: TestClient, mock_firestore: _FakeFirestore
) -> None:
    res = client.get("/v1/speeches/sp-1/reaction", params={"user_id": "demo-25-29"})

    assert res.status_code == 200
    body = res.json()
    assert body == {
        "speech_id": "sp-1",
        "user_id": "demo-25-29",
        "reaction": None,
        "updated_at": None,
    }


def test_get_reaction_set_returns_value(client: TestClient, mock_firestore: _FakeFirestore) -> None:
    mock_firestore.docs["reactions"]["demo-25-29__sp-1"] = {
        "reaction": "👍",
        "user_id": "demo-25-29",
        "speech_id": "sp-1",
    }

    res = client.get("/v1/speeches/sp-1/reaction", params={"user_id": "demo-25-29"})

    assert res.status_code == 200
    assert res.json()["reaction"] == "👍"


# ============================================================================
# PUT /v1/speeches/{speech_id}/reaction
# ============================================================================


def test_put_reaction_new_increments_counts_and_total(
    client: TestClient, mock_firestore: _FakeFirestore
) -> None:
    """新規 PUT → reaction doc 作成 + counts.{new}+=1 + total+=1。"""
    res = client.put(
        "/v1/speeches/sp-1/reaction",
        params={"user_id": "demo-25-29"},
        json={"reaction": "🔥"},
    )

    assert res.status_code == 200
    assert res.json()["reaction"] == "🔥"

    # reactions に書かれた
    reaction = mock_firestore.docs["reactions"]["demo-25-29__sp-1"]
    assert reaction["reaction"] == "🔥"
    assert "created_at" in reaction

    # reaction_counts に counts.🔥 = 1, total = 1
    counts_doc = mock_firestore.docs["reaction_counts"]["sp-1"]
    assert counts_doc["counts"]["🔥"] == 1
    assert counts_doc["total"] == 1


def test_put_reaction_overwrite_with_different_emoji(
    client: TestClient, mock_firestore: _FakeFirestore
) -> None:
    """既存 🤔 → PUT 👍 で counts.🤔-=1, counts.👍+=1, total 変わらず。"""
    # 既存状態: 🤔 が 1 件登録済
    mock_firestore.docs["reactions"]["demo-25-29__sp-1"] = {
        "reaction": "🤔",
        "user_id": "demo-25-29",
        "speech_id": "sp-1",
    }
    mock_firestore.docs["reaction_counts"]["sp-1"] = {
        "speech_id": "sp-1",
        "counts": {"🤔": 1},
        "total": 1,
    }

    res = client.put(
        "/v1/speeches/sp-1/reaction",
        params={"user_id": "demo-25-29"},
        json={"reaction": "👍"},
    )

    assert res.status_code == 200

    counts = mock_firestore.docs["reaction_counts"]["sp-1"]["counts"]
    assert counts["🤔"] == 0  # 減算
    assert counts["👍"] == 1  # 新規追加
    # total は変わらない (1 のまま)
    assert mock_firestore.docs["reaction_counts"]["sp-1"]["total"] == 1


def test_put_reaction_same_emoji_is_noop_for_counts(
    client: TestClient, mock_firestore: _FakeFirestore
) -> None:
    """既存と同じ絵文字を再 PUT → counts は変えない (no-op)。"""
    mock_firestore.docs["reactions"]["demo-25-29__sp-1"] = {
        "reaction": "👍",
        "user_id": "demo-25-29",
        "speech_id": "sp-1",
    }
    mock_firestore.docs["reaction_counts"]["sp-1"] = {
        "speech_id": "sp-1",
        "counts": {"👍": 1},
        "total": 1,
    }

    res = client.put(
        "/v1/speeches/sp-1/reaction",
        params={"user_id": "demo-25-29"},
        json={"reaction": "👍"},
    )

    assert res.status_code == 200
    counts = mock_firestore.docs["reaction_counts"]["sp-1"]["counts"]
    assert counts["👍"] == 1  # 変わらず


def test_put_reaction_invalid_emoji_returns_400(
    client: TestClient, mock_firestore: _FakeFirestore
) -> None:
    res = client.put(
        "/v1/speeches/sp-1/reaction",
        params={"user_id": "demo-25-29"},
        json={"reaction": "💩"},
    )

    assert res.status_code == 400
    assert "must be one of" in res.json()["detail"]
    assert "demo-25-29__sp-1" not in mock_firestore.docs["reactions"]


# ============================================================================
# DELETE /v1/speeches/{speech_id}/reaction
# ============================================================================


def test_delete_reaction_decrements_counts(
    client: TestClient, mock_firestore: _FakeFirestore
) -> None:
    """既存 👍 を DELETE → reaction 削除 + counts.👍-=1, total-=1。"""
    mock_firestore.docs["reactions"]["demo-25-29__sp-1"] = {
        "reaction": "👍",
        "user_id": "demo-25-29",
        "speech_id": "sp-1",
    }
    mock_firestore.docs["reaction_counts"]["sp-1"] = {
        "speech_id": "sp-1",
        "counts": {"👍": 3},
        "total": 3,
    }

    res = client.delete("/v1/speeches/sp-1/reaction", params={"user_id": "demo-25-29"})

    assert res.status_code == 200
    assert "demo-25-29__sp-1" not in mock_firestore.docs["reactions"]
    counts_doc = mock_firestore.docs["reaction_counts"]["sp-1"]
    assert counts_doc["counts"]["👍"] == 2
    assert counts_doc["total"] == 2


def test_delete_reaction_idempotent_when_missing(
    client: TestClient, mock_firestore: _FakeFirestore
) -> None:
    """既存リアクションなし → 200 で counts も触らない。"""
    res = client.delete("/v1/speeches/sp-1/reaction", params={"user_id": "demo-25-29"})

    assert res.status_code == 200
    assert "sp-1" not in mock_firestore.docs["reaction_counts"]


# ============================================================================
# GET /v1/speeches/{speech_id}/reactions/summary (Phase X+1)
# ============================================================================


def test_summary_no_document_returns_zeros(
    client: TestClient, mock_firestore: _FakeFirestore
) -> None:
    """集計 document が無い speech → 全 4 種 0 件 + total=0。"""
    res = client.get("/v1/speeches/sp-1/reactions/summary")

    assert res.status_code == 200
    body = res.json()
    assert body["speech_id"] == "sp-1"
    assert body["total"] == 0
    assert body["counts"] == {"👍": 0, "🤔": 0, "😢": 0, "🔥": 0}


def test_summary_returns_existing_counts_with_zero_fill(
    client: TestClient, mock_firestore: _FakeFirestore
) -> None:
    """document あり → 値を返す + 欠落 emoji は 0 埋め。"""
    mock_firestore.docs["reaction_counts"]["sp-1"] = {
        "speech_id": "sp-1",
        "counts": {"👍": 12, "🔥": 7},  # 🤔 / 😢 は無い
        "total": 19,
    }

    res = client.get("/v1/speeches/sp-1/reactions/summary")

    assert res.status_code == 200
    body = res.json()
    assert body["counts"]["👍"] == 12
    assert body["counts"]["🤔"] == 0
    assert body["counts"]["😢"] == 0
    assert body["counts"]["🔥"] == 7
    assert body["total"] == 19
