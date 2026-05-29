"""GenaiConciergeRunner のユニットテスト (Plan E Phase 3)。

テスト戦略:
    - google.genai.Client を MagicMock で注入
    - response.candidates[0].content.parts に function_call / text を仕込んで
      iterative loop の挙動を検証
    - tool 実体 (BQ query) は bq_client の DI で mock 化、tools.py の path を再利用

genai が import される箇所:
    - _build_tools_param() (lazy import inside method)
    - run() の冒頭 (Content/Part 構築のため lazy import)
    → test では genai を実際 import せず、SimpleNamespace で代用するパターンも可だが
       google.adk と違って genai は sandbox/CI でも壊れず import 可能なので、
       直接 import + mock client で簡素化。
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from agents.concierge.runner import GenaiConciergeRunner
from agents.concierge.schema import (
    ConciergeRequest,
    MunicipalityCandidate,
    UserPersonaInput,
)

# ============================================================================
# autouse fixture: google.genai を fake module で置換
# 本番では google.genai を import するが、test sandbox / CI で import 失敗を回避
# (Plan C の test_adk_agent.py と同じパターン)
# ============================================================================


@pytest.fixture(autouse=True)
def _fake_google_genai(monkeypatch: pytest.MonkeyPatch) -> None:
    """google.genai.types を fake モジュールに差し替え。

    GenaiConciergeRunner.run() / _build_tools_param() で
    `from google.genai import types` する箇所が、本物の types ではなく
    SimpleNamespace を取得するようにする。
    """

    # 各 type class を MagicMock で代用 (Pydantic 検証は通さない、
    # generate_content() 自体は test 側で MagicMock 注入するので OK)
    fake_types = SimpleNamespace(
        Tool=MagicMock(name="Tool"),
        FunctionDeclaration=MagicMock(name="FunctionDeclaration"),
        Content=MagicMock(name="Content"),
        Part=MagicMock(name="Part"),
        FunctionResponse=MagicMock(name="FunctionResponse"),
        GenerateContentConfig=MagicMock(name="GenerateContentConfig"),
    )
    fake_genai = SimpleNamespace(types=fake_types)

    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)


def _make_request(message: str = "26 歳、リモートワーク、子育て予定です") -> ConciergeRequest:
    return ConciergeRequest(
        message=message,
        persona=UserPersonaInput(
            user_id="demo-25-29",
            age_group="25-29",
            interests=["住居", "子育て"],
            municipality_codes=["13104"],
            free_form_context="リモートワーク中心",
        ),
    )


def _make_fake_function_call(name: str, args: dict[str, Any]) -> Any:
    """genai response.candidates[0].content.parts に入れる function_call mock。"""
    fc = MagicMock()
    fc.name = name
    fc.args = args
    return fc


def _make_fake_response(
    function_calls: list[Any] | None = None,
    text: str = "",
) -> Any:
    """genai client.models.generate_content() の戻り値 mock。"""
    parts = []
    if function_calls:
        for fc in function_calls:
            part = MagicMock()
            part.function_call = fc
            part.text = None
            parts.append(part)
    if text:
        part = MagicMock()
        part.function_call = None
        part.text = text
        parts.append(part)

    content = MagicMock()
    content.parts = parts

    candidate = MagicMock()
    candidate.content = content

    response = MagicMock()
    response.candidates = [candidate]
    response.text = text
    return response


def _make_search_candidates(n: int = 2) -> list[MunicipalityCandidate]:
    """search_municipalities が返す candidates の mock data。"""
    return [
        MunicipalityCandidate(
            municipality_code=f"1310{i}",
            name=f"区{i}",
            prefecture="東京都",
            match_score=90.0 - i * 5,
            population_total=300000 - i * 10000,
            matched_interests=["住居", "子育て"],
        )
        for i in range(n)
    ]


# ============================================================================
# Group 1: 終端パターン (text only、tool call なし)
# ============================================================================


def test_run_returns_reply_when_response_has_text_only() -> None:
    """初回応答が text のみなら、tool 呼ばずに reply を返す。"""
    client = MagicMock()
    client.models.generate_content.return_value = _make_fake_response(
        function_calls=None,
        text="新宿区がおすすめです。家賃中央値 6,000 万円、保育施設 80 件。",
    )

    runner = GenaiConciergeRunner(client=client)
    result = runner.run(_make_request(), persona_desc="25-29 / 住居,子育て")

    assert "新宿区がおすすめ" in result["reply"]
    assert result["tool_calls"] == []
    assert result["candidates"] == []
    assert client.models.generate_content.call_count == 1


def test_run_returns_empty_reply_when_response_has_no_parts() -> None:
    """LLM が完全に空応答でも graceful (空 reply で終了)。"""
    client = MagicMock()
    client.models.generate_content.return_value = _make_fake_response(function_calls=None, text="")

    runner = GenaiConciergeRunner(client=client)
    result = runner.run(_make_request(), persona_desc="X")

    assert result["reply"] == ""
    assert result["tool_calls"] == []


# ============================================================================
# Group 2: 1 tool call → text 終端
# ============================================================================


def test_run_executes_search_tool_then_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """search_municipalities を呼び、次の応答 (text) を最終 reply として返す。"""
    # tools.search_municipalities を monkeypatch で mock
    fake_candidates = _make_search_candidates(n=3)
    monkeypatch.setattr(
        "agents.concierge.runner.concierge_tools.search_municipalities",
        lambda args, bq_client=None: fake_candidates,
    )

    # 1 回目: function_call (search_municipalities)、2 回目: 最終 text
    client = MagicMock()
    client.models.generate_content.side_effect = [
        _make_fake_response(
            function_calls=[
                _make_fake_function_call(
                    "search_municipalities",
                    {"age_group": "25-29", "interests": ["住居", "子育て"], "limit": 3},
                )
            ],
        ),
        _make_fake_response(text="3 つの候補が見つかりました: 区0, 区1, 区2 です。"),
    ]

    runner = GenaiConciergeRunner(client=client)
    result = runner.run(_make_request(), persona_desc="25-29")

    assert "3 つの候補" in result["reply"]
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "search_municipalities"
    assert result["tool_calls"][0]["args"]["age_group"] == "25-29"

    # candidates が抽出されている (search_municipalities の output から)
    assert len(result["candidates"]) == 3
    assert result["candidates"][0]["municipality_code"] == "13100"
    assert result["candidates"][0]["match_score"] == 90.0

    assert client.models.generate_content.call_count == 2


def test_run_extracts_candidates_only_from_search_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_city_dashboard 等の tool 出力は candidates に含まれない。"""
    from agents.concierge.schema import CityDashboardSummary

    monkeypatch.setattr(
        "agents.concierge.runner.concierge_tools.fetch_city_dashboard",
        lambda args, bq_client=None: CityDashboardSummary(
            municipality_code="13104",
            name="新宿区",
            prefecture="東京都",
            stats={"population_total": 350000},
        ),
    )

    client = MagicMock()
    client.models.generate_content.side_effect = [
        _make_fake_response(
            function_calls=[
                _make_fake_function_call(
                    "fetch_city_dashboard",
                    {"municipality_code": "13104", "user_id": "demo-25-29"},
                )
            ],
        ),
        _make_fake_response(text="新宿区は人口 35 万人。"),
    ]

    runner = GenaiConciergeRunner(client=client)
    result = runner.run(_make_request(), persona_desc="X")

    assert len(result["tool_calls"]) == 1
    assert result["candidates"] == []  # dashboard は candidates に含まれない


# ============================================================================
# Group 3: 連続 tool calls
# ============================================================================


def test_run_handles_two_iterations_of_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """search → fetch_city_dashboard の連続 tool call を捌く。"""
    fake_candidates = _make_search_candidates(n=2)
    monkeypatch.setattr(
        "agents.concierge.runner.concierge_tools.search_municipalities",
        lambda args, bq_client=None: fake_candidates,
    )

    from agents.concierge.schema import CityDashboardSummary

    monkeypatch.setattr(
        "agents.concierge.runner.concierge_tools.fetch_city_dashboard",
        lambda args, bq_client=None: CityDashboardSummary(
            municipality_code="13100",
            name="区0",
            prefecture="東京都",
            stats={},
        ),
    )

    client = MagicMock()
    client.models.generate_content.side_effect = [
        _make_fake_response(
            function_calls=[
                _make_fake_function_call(
                    "search_municipalities",
                    {"age_group": "25-29", "interests": ["住居"]},
                )
            ],
        ),
        _make_fake_response(
            function_calls=[
                _make_fake_function_call(
                    "fetch_city_dashboard",
                    {"municipality_code": "13100", "user_id": "demo-25-29"},
                )
            ],
        ),
        _make_fake_response(text="最終応答: 区0 を詳しく見ました。"),
    ]

    runner = GenaiConciergeRunner(client=client)
    result = runner.run(_make_request(), persona_desc="X")

    assert "区0 を詳しく" in result["reply"]
    assert len(result["tool_calls"]) == 2
    tool_names = [tc["name"] for tc in result["tool_calls"]]
    assert tool_names == ["search_municipalities", "fetch_city_dashboard"]
    assert len(result["candidates"]) == 2  # search の結果のみ


# ============================================================================
# Group 4: tool 実行エラー時の graceful fallback
# ============================================================================


def test_run_handles_tool_execution_failure_gracefully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tool 実行で例外が出ても、loop は止まらず error 結果を LLM に渡す。"""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("BQ down")

    monkeypatch.setattr("agents.concierge.runner.concierge_tools.search_municipalities", boom)

    client = MagicMock()
    client.models.generate_content.side_effect = [
        _make_fake_response(
            function_calls=[
                _make_fake_function_call(
                    "search_municipalities", {"age_group": "25-29", "interests": ["住居"]}
                )
            ],
        ),
        _make_fake_response(text="申し訳ありません、検索でエラーが発生しました。"),
    ]

    runner = GenaiConciergeRunner(client=client)
    result = runner.run(_make_request(), persona_desc="X")

    # 例外は捕捉されて output に "error" を含む dict として記録
    assert len(result["tool_calls"]) == 1
    tc = result["tool_calls"][0]
    assert tc["name"] == "search_municipalities"
    assert isinstance(tc["output"], dict)
    assert "error" in tc["output"]
    assert "BQ down" in tc["output"]["error"]


def test_run_handles_unknown_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM が存在しない tool 名を叩いても loop は止まらず error 記録のみ。"""
    client = MagicMock()
    client.models.generate_content.side_effect = [
        _make_fake_response(
            function_calls=[_make_fake_function_call("nonexistent_tool", {})],
        ),
        _make_fake_response(text="完了"),
    ]

    runner = GenaiConciergeRunner(client=client)
    result = runner.run(_make_request(), persona_desc="X")

    assert result["reply"] == "完了"
    assert len(result["tool_calls"]) == 1
    assert "error" in result["tool_calls"][0]["output"]
    assert "Unknown tool" in result["tool_calls"][0]["output"]["error"]


# ============================================================================
# Group 5: max_iterations gating
# ============================================================================


def test_run_returns_safe_message_on_max_iterations(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM が無限 tool call を続けても max_iterations で安全に終了。"""
    fake_candidates = _make_search_candidates(n=1)
    monkeypatch.setattr(
        "agents.concierge.runner.concierge_tools.search_municipalities",
        lambda args, bq_client=None: fake_candidates,
    )

    client = MagicMock()
    # 毎回 search_municipalities を呼び続ける (text 返さない無限 loop シミュレート)
    client.models.generate_content.return_value = _make_fake_response(
        function_calls=[
            _make_fake_function_call(
                "search_municipalities", {"age_group": "25-29", "interests": ["住居"]}
            )
        ],
    )

    runner = GenaiConciergeRunner(max_iterations=3, client=client)
    result = runner.run(_make_request(), persona_desc="X")

    # 3 回 tool 実行 + max_iterations 到達 で安全 reply
    assert client.models.generate_content.call_count == 3
    assert len(result["tool_calls"]) == 3
    assert "もう少し条件" in result["reply"] or "絞り込みきれ" in result["reply"]


# ============================================================================
# Group 6: helper methods
# ============================================================================


def test_serialize_for_genai_handles_pydantic_list() -> None:
    """list of Pydantic BaseModel → list of dict."""
    candidates = _make_search_candidates(n=2)
    serialized = GenaiConciergeRunner._serialize_for_genai(candidates)

    assert isinstance(serialized, list)
    assert len(serialized) == 2
    assert serialized[0]["municipality_code"] == "13100"
    assert isinstance(serialized[0], dict)


def test_serialize_for_genai_handles_single_pydantic() -> None:
    """Pydantic instance → dict."""
    c = _make_search_candidates(n=1)[0]
    serialized = GenaiConciergeRunner._serialize_for_genai(c)
    assert isinstance(serialized, dict)
    assert serialized["municipality_code"] == "13100"


def test_serialize_for_genai_handles_dict() -> None:
    """dict はそのまま返す。"""
    d = {"a": 1, "b": "two"}
    assert GenaiConciergeRunner._serialize_for_genai(d) == d


def test_serialize_for_genai_fallback_to_str() -> None:
    """その他は str() に。"""
    assert GenaiConciergeRunner._serialize_for_genai(42) == "42"
