"""RAG パッケージのユニットテスト (BQ / GCS / Vertex AI を mock、実 API 不要)。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from apps.api.rag.corpus import (
    KOKKAI_CORPUS_DISPLAY_NAME,
    RetrievedContext,
    create_corpus,
    get_corpus_by_display_name,
    list_corpora,
    retrieval_query,
)
from apps.api.rag.export import (
    SpeechExportRow,
    _upload_speech,
    format_speech_for_rag,
)


def _make_row(speech_id: str = "id-1") -> SpeechExportRow:
    return SpeechExportRow(
        id=speech_id,
        speaker="石破茂",
        speaker_group="自由民主党",
        speaker_position="内閣総理大臣",
        name_of_house="衆議院",
        name_of_meeting="本会議",
        issue="第16号",
        meeting_date=date(2026, 5, 18),
        speech_url="https://kokkai.ndl.go.jp/txt/sample/1",
        meeting_url="https://kokkai.ndl.go.jp/#/detail?minId=sample",
        speech="ただいまから本会議を開きます。本日は少子化対策について審議いたします。",
    )


# ============================================================================
# export.py
# ============================================================================


def test_format_speech_for_rag_includes_metadata_header():
    """RAG 用 text に metadata header + 本文が含まれる。"""
    row = _make_row()
    text = format_speech_for_rag(row)

    assert "Speaker: 石破茂 (自由民主党, 内閣総理大臣)" in text
    assert "House: 衆議院" in text
    assert "Meeting: 本会議 第16号" in text
    assert "Date: 2026-05-18" in text
    assert "URL: https://kokkai.ndl.go.jp/txt/sample/1" in text
    # header と本文が空行で区切られる
    assert "\n\nただいまから本会議を開きます" in text


def test_format_speech_for_rag_handles_missing_fields():
    """speaker_group / speaker_position / urls が None でも壊れない。"""
    row = SpeechExportRow(
        id="id-2",
        speaker="議長",
        speaker_group=None,
        speaker_position=None,
        name_of_house=None,
        name_of_meeting=None,
        issue=None,
        meeting_date=None,
        speech_url=None,
        meeting_url=None,
        speech="本日の議事は…",
    )
    text = format_speech_for_rag(row)

    assert "Speaker: 議長" in text  # parens なし
    assert "House: (不明)" in text
    assert "Meeting: (会議不明)" in text
    assert "Date: (日付不明)" in text
    assert "URL:" not in text
    assert "本日の議事は…" in text


def test_upload_speech_writes_to_correct_blob_path():
    """blob name が `{prefix}/{speech_id}.txt` 形式。"""
    captured: dict[str, Any] = {}

    class _MockBlob:
        def upload_from_string(self, data: str, content_type: str) -> None:
            captured["data"] = data
            captured["content_type"] = content_type

    class _MockBucket:
        def blob(self, name: str) -> _MockBlob:
            captured["blob_name"] = name
            return _MockBlob()

    row = _make_row("id-xyz")
    blob_name = _upload_speech(_MockBucket(), prefix="kokkai", row=row)

    assert blob_name == "kokkai/id-xyz.txt"
    assert captured["blob_name"] == "kokkai/id-xyz.txt"
    assert captured["content_type"] == "text/plain; charset=utf-8"
    assert "石破茂" in captured["data"]


def test_format_speech_for_rag_includes_source_and_municipality():
    """多ソース対応: Source / Municipality メタデータが header に入る。"""
    from dataclasses import replace

    row = replace(_make_row(), source="kaigiroku_net", municipality_code="33100")
    text = format_speech_for_rag(row)
    assert "Source: kaigiroku_net" in text
    assert "Municipality: 33100" in text


def test_query_distinct_speeches_applies_source_label_override():
    """source 列を持たないソースでも source_label/municipality_code で定数上書きできる。"""
    from apps.api.rag.export import _query_distinct_speeches

    class _MockJob:
        def __iter__(self):
            # source / municipality_code 列が無い行 (dict) をシミュレート
            yield {
                "id": "m-1",
                "speaker": "市長",
                "speaker_group": None,
                "speaker_position": None,
                "name_of_house": None,
                "name_of_meeting": "定例会",
                "issue": None,
                "meeting_date": date(2026, 6, 1),
                "speech_url": None,
                "meeting_url": None,
                "speech": "本市の子育て支援について",
            }

    class _MockBQ:
        def query(self, sql: str) -> _MockJob:  # noqa: ARG002
            return _MockJob()

    rows = list(
        _query_distinct_speeches(
            _MockBQ(),
            "citify-dev.citify_curated.speech_texts",
            source_label="kaigiroku_net",
            municipality_code="33100",
        )
    )
    assert len(rows) == 1
    assert rows[0].source == "kaigiroku_net"
    assert rows[0].municipality_code == "33100"


# ============================================================================
# corpus.py
# ============================================================================


class _MockCorpus:
    def __init__(self, name: str, display_name: str) -> None:
        self.name = name
        self.display_name = display_name


class _MockRagModule:
    """vertexai.rag モジュールの最小 mock。"""

    def __init__(self) -> None:
        self.corpora: list[_MockCorpus] = []
        self.created_args: dict[str, Any] = {}
        self.import_args: dict[str, Any] = {}
        self.query_args: dict[str, Any] = {}

    # EmbeddingModelConfig / TransformationConfig / ChunkingConfig / RagResource /
    # RagRetrievalConfig は単に引数を保持するだけの dummy object
    def _passthrough(self, **kwargs: Any) -> dict[str, Any]:
        return kwargs

    # SDK >= 1.85 の新 API (Rag prefix + 入れ子構造)
    RagEmbeddingModelConfig = staticmethod(lambda **kw: kw)  # noqa: N815
    VertexPredictionEndpoint = staticmethod(lambda **kw: kw)  # noqa: N815
    RagVectorDbConfig = staticmethod(lambda **kw: kw)  # noqa: N815
    TransformationConfig = staticmethod(lambda **kw: kw)  # noqa: N815
    ChunkingConfig = staticmethod(lambda **kw: kw)  # noqa: N815
    RagResource = staticmethod(lambda **kw: kw)  # noqa: N815
    RagRetrievalConfig = staticmethod(lambda **kw: kw)  # noqa: N815

    def create_corpus(
        self, *, display_name: str, description: str, backend_config: Any = None
    ) -> _MockCorpus:
        self.created_args = {
            "display_name": display_name,
            "description": description,
            "backend_config": backend_config,
        }
        corpus = _MockCorpus(
            name=f"projects/test/ragCorpora/{len(self.corpora) + 1}", display_name=display_name
        )
        self.corpora.append(corpus)
        return corpus

    def list_corpora(self) -> list[_MockCorpus]:
        return list(self.corpora)

    def import_files(
        self, *, corpus_name: str, paths: list[str], transformation_config: Any
    ) -> Any:
        self.import_args = {
            "corpus_name": corpus_name,
            "paths": paths,
            "transformation_config": transformation_config,
        }

        class _MockResponse:
            imported_rag_files_count = 1428
            failed_rag_files_count = 0

        return _MockResponse()

    def retrieval_query(
        self, *, rag_resources: list[Any], text: str, rag_retrieval_config: Any
    ) -> Any:
        self.query_args = {
            "rag_resources": rag_resources,
            "text": text,
            "rag_retrieval_config": rag_retrieval_config,
        }

        class _Ctx:
            def __init__(self, text: str, source_uri: str, distance: float) -> None:
                self.text = text
                self.source_uri = source_uri
                self.distance = distance

        class _Contexts:
            contexts = [
                _Ctx("子育て支援について議論", "gs://b/kokkai/id-1.txt", 0.12),
                _Ctx("保育所の整備", "gs://b/kokkai/id-2.txt", 0.18),
            ]

        class _Resp:
            contexts = _Contexts()

        return _Resp()


def test_create_corpus_calls_rag_module_correctly():
    mock = _MockRagModule()
    create_corpus(
        project_id="test-proj",
        display_name="my-corpus",
        rag_module=mock,
    )
    assert mock.created_args["display_name"] == "my-corpus"
    # serverless (default) は backend_config を省略する (corpus.py の現行既定)
    assert mock.created_args["backend_config"] is None


def test_create_corpus_spanner_mode_sets_embedding_backend() -> None:
    """use_serverless=False (Spanner legacy) は backend_config に embedding model を設定。"""
    mock = _MockRagModule()
    create_corpus(
        project_id="test-proj",
        display_name="my-corpus",
        rag_module=mock,
        use_serverless=False,
    )
    assert "text-multilingual-embedding-002" in str(mock.created_args["backend_config"])


def test_get_corpus_by_display_name_returns_match():
    mock = _MockRagModule()
    create_corpus(project_id="p", display_name="aaa", rag_module=mock)
    create_corpus(project_id="p", display_name=KOKKAI_CORPUS_DISPLAY_NAME, rag_module=mock)
    create_corpus(project_id="p", display_name="zzz", rag_module=mock)

    found = get_corpus_by_display_name("p", rag_module=mock)
    assert found is not None
    assert found.display_name == KOKKAI_CORPUS_DISPLAY_NAME


def test_get_corpus_by_display_name_returns_none_when_absent():
    mock = _MockRagModule()
    create_corpus(project_id="p", display_name="other", rag_module=mock)
    found = get_corpus_by_display_name("p", rag_module=mock)
    assert found is None


def test_list_corpora_returns_all():
    mock = _MockRagModule()
    create_corpus(project_id="p", display_name="a", rag_module=mock)
    create_corpus(project_id="p", display_name="b", rag_module=mock)
    corpora = list_corpora("p", rag_module=mock)
    assert len(corpora) == 2


def test_retrieval_query_returns_contexts():
    mock = _MockRagModule()
    contexts = retrieval_query(
        corpus_name="projects/test/ragCorpora/1",
        text="子育て支援",
        top_k=5,
        rag_module=mock,
    )

    assert len(contexts) == 2
    assert isinstance(contexts[0], RetrievedContext)
    assert contexts[0].text == "子育て支援について議論"
    assert contexts[0].source_uri == "gs://b/kokkai/id-1.txt"
    assert contexts[0].distance == pytest.approx(0.12)
    assert mock.query_args["text"] == "子育て支援"
