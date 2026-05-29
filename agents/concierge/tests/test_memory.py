"""ConversationMemory (memory.py) のユニットテスト (Plan L+LL Phase 1)。

テスト戦略:
    - Firestore client を MagicMock で注入 (DI)
    - embed_fn を fake 関数で注入 (Vertex AI 不要)
    - cosine_similarity と extract_interests は純関数なので直接テスト
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from agents.concierge.memory import (
    DEFAULT_RECALL_SCAN_LIMIT,
    FIRESTORE_COLLECTION_HISTORY,
    ConversationMemory,
    HistoryRecord,
    cosine_similarity,
    extract_interests,
)
from agents.concierge.schema import MunicipalityCandidate

# ============================================================================
# extract_interests (rule-based 抽出)
# ============================================================================


def test_extract_interests_住居() -> None:
    """住居キーワードで「住居」hit。"""
    assert "住居" in extract_interests("家賃が高くて困っています")
    assert "住居" in extract_interests("中古マンションを探しています")


def test_extract_interests_子育て() -> None:
    """子育てキーワードで「子育て」hit。"""
    assert "子育て" in extract_interests("保育園の待機児童 2 年待ち")


def test_extract_interests_移住() -> None:
    """移住キーワードで「移住」hit。"""
    assert "移住" in extract_interests("実家にUターン予定です")


def test_extract_interests_multiple() -> None:
    """複数の interest を同時に hit。"""
    text = "保育園が充実で家賃も安い街、医療機関も多いところ"
    found = extract_interests(text)
    assert "住居" in found
    assert "子育て" in found
    assert "医療" in found


def test_extract_interests_no_match() -> None:
    """関係ない text なら空 list。"""
    assert extract_interests("今日の天気は晴れです") == []


def test_extract_interests_no_duplicates() -> None:
    """同じ interest を 2 度返さない (extract 内 dedup)。"""
    found = extract_interests("家賃 家賃 マンション マンション")
    assert found.count("住居") == 1


# ============================================================================
# cosine_similarity (純関数)
# ============================================================================


def test_cosine_similarity_identical() -> None:
    """同一 vector → 1.0。"""
    v = [0.1, 0.2, 0.3]
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-9


def test_cosine_similarity_orthogonal() -> None:
    """直交 vector → 0.0。"""
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert abs(cosine_similarity(a, b)) < 1e-9


def test_cosine_similarity_zero_vector() -> None:
    """zero vector があれば 0.0 (graceful)。"""
    assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_cosine_similarity_different_lengths() -> None:
    """長さ違いは 0.0 (graceful)。"""
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0]) == 0.0


def test_cosine_similarity_empty() -> None:
    assert cosine_similarity([], []) == 0.0


# ============================================================================
# HistoryRecord.to_dict / from_doc
# ============================================================================


def test_history_record_round_trip() -> None:
    """to_dict → from_doc で同じ instance に戻る。"""
    ts = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    record = HistoryRecord(
        doc_id="user1__2026-05-29",
        user_id="user1",
        timestamp=ts,
        message="家賃の安い街教えて",
        reply="家賃 5000 万円以下の街リスト...",
        short_summary="家賃 5000 万円以下の街リスト...",
        candidates_codes=["13104", "14130"],
        matched_interests=["住居"],
        embedding=[0.1] * 768,
    )
    data = record.to_dict()
    restored = HistoryRecord.from_doc(record.doc_id, data)
    assert restored.user_id == record.user_id
    assert restored.message == record.message
    assert restored.matched_interests == record.matched_interests
    assert restored.candidates_codes == record.candidates_codes
    assert len(restored.embedding) == 768


# ============================================================================
# ConversationMemory.save_turn
# ============================================================================


def _make_mock_firestore() -> tuple[MagicMock, MagicMock]:
    """Firestore client mock と doc mock を返す。"""
    mock_doc_ref = MagicMock()
    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_doc_ref

    mock_client = MagicMock()
    mock_client.collection.return_value = mock_collection

    return mock_client, mock_doc_ref


def test_save_turn_writes_to_firestore() -> None:
    """save_turn() で Firestore に doc が書かれる。"""
    mock_client, mock_doc_ref = _make_mock_firestore()
    fake_embed = MagicMock(return_value=[0.1] * 768)

    memory = ConversationMemory(firestore_client=mock_client, embed_fn=fake_embed)
    doc_id = memory.save_turn(
        user_id="user1",
        message="保育園充実な街は?",
        reply="新宿区がおすすめ...",
        candidates=[
            MunicipalityCandidate(
                municipality_code="13104",
                name="新宿区",
                prefecture="東京都",
                match_score=90.0,
            )
        ],
    )

    assert doc_id.startswith("user1__")
    # Firestore collection / document / set が呼ばれている
    mock_client.collection.assert_called_with(FIRESTORE_COLLECTION_HISTORY)
    mock_doc_ref.set.assert_called_once()
    saved_data = mock_doc_ref.set.call_args.args[0]
    assert saved_data["user_id"] == "user1"
    assert saved_data["message"] == "保育園充実な街は?"
    assert saved_data["short_summary"] == "新宿区がおすすめ..."
    assert saved_data["candidates_codes"] == ["13104"]
    assert "子育て" in saved_data["matched_interests"]  # rule-based 抽出


def test_save_turn_extracts_interests_via_rule_based() -> None:
    """save_turn() で rule-based に interest が抽出される。"""
    mock_client, mock_doc_ref = _make_mock_firestore()
    fake_embed = MagicMock(return_value=[0.1] * 768)

    memory = ConversationMemory(firestore_client=mock_client, embed_fn=fake_embed)
    memory.save_turn(
        user_id="user1",
        message="家賃が高すぎる、転職もしたい",
        reply="リモートワーク歓迎の街を提案します",
    )
    saved_data = mock_doc_ref.set.call_args.args[0]
    # 家賃→住居 / 転職→雇用 が hit
    assert "住居" in saved_data["matched_interests"]
    assert "雇用" in saved_data["matched_interests"]


def test_save_turn_handles_embed_failure_gracefully() -> None:
    """Embedding 失敗時も embedding=[] で保存続行。"""
    mock_client, mock_doc_ref = _make_mock_firestore()
    fake_embed = MagicMock(side_effect=RuntimeError("Vertex AI timeout"))

    memory = ConversationMemory(firestore_client=mock_client, embed_fn=fake_embed)
    doc_id = memory.save_turn(user_id="user1", message="test", reply="reply")
    assert doc_id  # 失敗せず doc_id 返却
    saved_data = mock_doc_ref.set.call_args.args[0]
    assert saved_data["embedding"] == []


def test_save_turn_truncates_long_text() -> None:
    """message/reply が長すぎる場合は 2000 chars に truncate。"""
    mock_client, mock_doc_ref = _make_mock_firestore()
    fake_embed = MagicMock(return_value=[0.1] * 768)

    memory = ConversationMemory(firestore_client=mock_client, embed_fn=fake_embed)
    long_text = "x" * 5000
    memory.save_turn(user_id="user1", message=long_text, reply=long_text)
    saved_data = mock_doc_ref.set.call_args.args[0]
    assert len(saved_data["message"]) <= 2000
    assert len(saved_data["reply"]) <= 2000


# ============================================================================
# ConversationMemory.recall_recent
# ============================================================================


def _make_mock_doc(doc_id: str, data: dict) -> MagicMock:
    """Firestore doc snapshot の mock。"""
    doc = MagicMock()
    doc.id = doc_id
    doc.to_dict.return_value = data
    return doc


def test_recall_recent_returns_records_in_order() -> None:
    """Firestore query 結果を HistoryRecord list で返す。"""
    ts1 = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    ts2 = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    mock_docs = [
        _make_mock_doc(
            "user1__2026-05-29",
            {
                "user_id": "user1",
                "timestamp": ts1,
                "message": "新着",
                "reply": "新着 reply",
                "short_summary": "新着 reply",
                "matched_interests": ["住居"],
                "embedding": [0.1] * 768,
                "candidates_codes": [],
            },
        ),
        _make_mock_doc(
            "user1__2026-05-28",
            {
                "user_id": "user1",
                "timestamp": ts2,
                "message": "古い",
                "reply": "古い reply",
                "short_summary": "古い reply",
                "matched_interests": ["子育て"],
                "embedding": [0.2] * 768,
                "candidates_codes": [],
            },
        ),
    ]

    mock_query = MagicMock()
    mock_query.stream.return_value = iter(mock_docs)
    mock_query.limit.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.where.return_value = mock_query

    mock_collection = MagicMock()
    mock_collection.where.return_value = mock_query

    mock_client = MagicMock()
    mock_client.collection.return_value = mock_collection

    memory = ConversationMemory(firestore_client=mock_client, embed_fn=MagicMock())
    records = memory.recall_recent(user_id="user1", limit=10)

    assert len(records) == 2
    assert all(isinstance(r, HistoryRecord) for r in records)
    assert records[0].message == "新着"
    assert records[1].message == "古い"


def test_recall_recent_bq_failure_returns_empty() -> None:
    """Firestore 失敗時は空 list で graceful。"""
    mock_client = MagicMock()
    mock_client.collection.side_effect = RuntimeError("Firestore down")

    memory = ConversationMemory(firestore_client=mock_client, embed_fn=MagicMock())
    records = memory.recall_recent(user_id="user1")
    assert records == []


# ============================================================================
# ConversationMemory.recall_similar
# ============================================================================


def test_recall_similar_sorts_by_cosine_similarity() -> None:
    """query embedding と各 record の cosine similarity 降順で返す。"""
    ts = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)

    # 3 records、それぞれ異なる embedding を持つ
    records_data = [
        ("doc_a", [1.0] + [0.0] * 767),  # query と完全一致
        ("doc_b", [0.0, 1.0] + [0.0] * 766),  # query と直交
        ("doc_c", [0.5, 0.5] + [0.0] * 766),  # query と中間
    ]
    mock_docs = [
        _make_mock_doc(
            doc_id,
            {
                "user_id": "user1",
                "timestamp": ts,
                "message": f"msg-{doc_id}",
                "reply": "r",
                "short_summary": "r",
                "matched_interests": [],
                "embedding": emb,
                "candidates_codes": [],
            },
        )
        for doc_id, emb in records_data
    ]

    mock_query = MagicMock()
    mock_query.stream.return_value = iter(mock_docs)
    mock_query.limit.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.where.return_value = mock_query

    mock_collection = MagicMock()
    mock_collection.where.return_value = mock_query

    mock_client = MagicMock()
    mock_client.collection.return_value = mock_collection

    # query embedding は doc_a と完全一致する vector
    query_embedding = [1.0] + [0.0] * 767
    fake_embed = MagicMock(return_value=query_embedding)

    memory = ConversationMemory(firestore_client=mock_client, embed_fn=fake_embed)
    result = memory.recall_similar(user_id="user1", query="test", limit=3)

    assert len(result) == 3
    # similarity 降順: doc_a (1.0) > doc_c (0.707...) > doc_b (0.0)
    assert result[0].doc_id == "doc_a"
    assert result[0].similarity_score is not None
    assert abs(result[0].similarity_score - 1.0) < 1e-9
    assert result[1].doc_id == "doc_c"
    assert result[2].doc_id == "doc_b"


def test_recall_similar_uses_scan_limit() -> None:
    """recall_scan_limit で fetch する直近 turn 数を制限。"""
    mock_query = MagicMock()
    mock_query.stream.return_value = iter([])
    mock_query.limit.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.where.return_value = mock_query

    mock_collection = MagicMock()
    mock_collection.where.return_value = mock_query

    mock_client = MagicMock()
    mock_client.collection.return_value = mock_collection

    memory = ConversationMemory(
        firestore_client=mock_client,
        embed_fn=MagicMock(),
        recall_scan_limit=30,
    )
    memory.recall_recent(user_id="user1", limit=memory.recall_scan_limit)
    # query.limit() が 30 で呼ばれたか
    mock_query.limit.assert_called_with(30)


def test_recall_similar_returns_empty_when_no_records() -> None:
    """過去 record なしなら空 list。"""
    mock_query = MagicMock()
    mock_query.stream.return_value = iter([])
    mock_query.limit.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.where.return_value = mock_query

    mock_collection = MagicMock()
    mock_collection.where.return_value = mock_query

    mock_client = MagicMock()
    mock_client.collection.return_value = mock_collection

    memory = ConversationMemory(firestore_client=mock_client, embed_fn=MagicMock())
    result = memory.recall_similar(user_id="user1", query="test", limit=3)
    assert result == []


# ============================================================================
# get_past_interests (LL: 過去関心の集計)
# ============================================================================


def test_get_past_interests_aggregates_frequency_descending() -> None:
    """過去対話の matched_interests を頻度降順で集約。"""
    ts = datetime(2026, 5, 29, 12, 0, tzinfo=UTC)
    mock_docs = [
        _make_mock_doc(
            f"doc-{i}",
            {
                "user_id": "user1",
                "timestamp": ts,
                "message": "",
                "reply": "",
                "short_summary": "",
                "matched_interests": interests,
                "embedding": [],
                "candidates_codes": [],
            },
        )
        for i, interests in enumerate(
            [
                ["住居", "子育て"],
                ["住居"],
                ["住居", "医療"],
                ["子育て"],
            ]
        )
    ]

    mock_query = MagicMock()
    mock_query.stream.return_value = iter(mock_docs)
    mock_query.limit.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.where.return_value = mock_query

    mock_collection = MagicMock()
    mock_collection.where.return_value = mock_query

    mock_client = MagicMock()
    mock_client.collection.return_value = mock_collection

    memory = ConversationMemory(firestore_client=mock_client, embed_fn=MagicMock())
    interests = memory.get_past_interests("user1", limit=10)

    # 住居 (3 回) → 子育て (2 回) → 医療 (1 回)
    assert interests[0] == "住居"
    assert interests[1] == "子育て"
    assert "医療" in interests


# ============================================================================
# ConversationMemory constants & defaults
# ============================================================================


def test_default_scan_limit_is_50() -> None:
    """Reviewer 指摘の scale 制約。"""
    assert DEFAULT_RECALL_SCAN_LIMIT == 50


def test_collection_name_is_concierge_history() -> None:
    assert FIRESTORE_COLLECTION_HISTORY == "concierge_history"


# ============================================================================
# pytest fixture helpers
# ============================================================================


def test_memory_default_construction_without_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """firestore_client=None で構築、_client() 経由で lazy init される。"""
    # google.cloud.firestore.Client を mock
    mock_firestore_module = MagicMock()
    mock_firestore_module.Client.return_value = MagicMock()

    import sys

    monkeypatch.setitem(sys.modules, "google.cloud", MagicMock(firestore=mock_firestore_module))
    monkeypatch.setitem(sys.modules, "google.cloud.firestore", mock_firestore_module)

    memory = ConversationMemory(embed_fn=MagicMock())
    client = memory._client()
    assert client is not None
