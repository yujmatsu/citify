"""ConciergeAgent (main.py) のユニットテスト (Plan E Phase 2)。

テスト戦略:
    - Runner (ADK Runner) を mock 注入、固定 dict を返させる
    - 倫理 post-validation の挙動を検証
    - 例外時の graceful fallback 検証
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agents.concierge.main import ConciergeAgent
from agents.concierge.schema import (
    ConciergeRequest,
    ConciergeResponse,
    MunicipalityCandidate,
    ToolCallLog,
    UserPersonaInput,
)


def _make_request(message: str = "26歳、リモートワーク、子育て予定です") -> ConciergeRequest:
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


def _make_candidate(code: str = "13104", score: float = 90.0) -> MunicipalityCandidate:
    return MunicipalityCandidate(
        municipality_code=code,
        name="新宿区",
        prefecture="東京都",
        match_score=score,
        population_total=350000,
        matched_interests=["住居", "子育て"],
    )


# ============================================================================
# respond() 正常系
# ============================================================================


def test_respond_returns_concierge_response_with_reply() -> None:
    """Runner が返した reply / tool_calls / candidates を ConciergeResponse に整形。"""
    runner = MagicMock()
    runner.run.return_value = {
        "reply": "新宿区がおすすめです。家賃中央値 6,000 万円、保育施設 80 件。",
        "tool_calls": [
            {
                "name": "search_municipalities",
                "args": {"age_group": "25-29", "interests": ["住居", "子育て"]},
                "output": {"candidates": [{"code": "13104"}]},
                "duration_ms": 150,
            }
        ],
        "candidates": [_make_candidate()],
    }

    agent = ConciergeAgent(runner=runner)
    response = agent.respond(_make_request())

    assert isinstance(response, ConciergeResponse)
    assert "新宿区がおすすめ" in response.reply
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "search_municipalities"
    assert response.tool_calls[0].duration_ms == 150
    assert len(response.candidates) == 1
    assert response.candidates[0].municipality_code == "13104"
    assert response.ethical_violations == []


def test_respond_passes_persona_desc_to_runner() -> None:
    """Runner.run() に persona の自然言語要約が渡る。"""
    runner = MagicMock()
    runner.run.return_value = {"reply": "ok", "tool_calls": [], "candidates": []}

    agent = ConciergeAgent(runner=runner)
    agent.respond(_make_request())

    call_kwargs = runner.run.call_args.kwargs
    assert "persona_desc" in call_kwargs
    persona_desc = call_kwargs["persona_desc"]
    assert "25-29" in persona_desc
    assert "住居" in persona_desc and "子育て" in persona_desc
    assert "13104" in persona_desc
    assert "リモートワーク中心" in persona_desc  # free_form_context が含まれる


def test_respond_normalizes_tool_calls_from_various_formats() -> None:
    """tool_calls が dict / ToolCallLog 混在でも正規化される。"""
    runner = MagicMock()
    runner.run.return_value = {
        "reply": "complete",
        "tool_calls": [
            {"name": "tool_a", "args": {"k": "v"}, "output": "abc", "duration_ms": 10},
            ToolCallLog(name="tool_b", args={}, output_preview="xyz"),
        ],
        "candidates": [],
    }

    agent = ConciergeAgent(runner=runner)
    response = agent.respond(_make_request())

    assert len(response.tool_calls) == 2
    assert {tc.name for tc in response.tool_calls} == {"tool_a", "tool_b"}


def test_respond_truncates_long_tool_output_preview() -> None:
    """tool_call output が長い場合 300 文字に truncate される。"""
    long_text = "a" * 1000
    runner = MagicMock()
    runner.run.return_value = {
        "reply": "ok",
        "tool_calls": [
            {"name": "t", "args": {}, "output": long_text, "duration_ms": 0},
        ],
        "candidates": [],
    }

    agent = ConciergeAgent(runner=runner)
    response = agent.respond(_make_request())

    assert len(response.tool_calls[0].output_preview) <= 300


def test_respond_serializes_dict_output_as_json() -> None:
    """tool output が dict なら JSON string で preview に。"""
    runner = MagicMock()
    runner.run.return_value = {
        "reply": "ok",
        "tool_calls": [
            {
                "name": "search",
                "args": {},
                "output": {"candidates": [{"code": "13104", "name": "新宿区"}]},
                "duration_ms": 0,
            }
        ],
        "candidates": [],
    }

    agent = ConciergeAgent(runner=runner)
    response = agent.respond(_make_request())

    preview = response.tool_calls[0].output_preview
    assert "13104" in preview
    assert "新宿区" in preview


def test_respond_parses_candidates_from_dict_or_model() -> None:
    """candidates が dict / MunicipalityCandidate 混在でも parse される。"""
    runner = MagicMock()
    runner.run.return_value = {
        "reply": "ok",
        "tool_calls": [],
        "candidates": [
            _make_candidate(code="13104", score=95.0),
            {
                "municipality_code": "13123",
                "name": "江戸川区",
                "prefecture": "東京都",
                "match_score": 88.0,
            },
        ],
    }

    agent = ConciergeAgent(runner=runner)
    response = agent.respond(_make_request())

    assert len(response.candidates) == 2
    assert response.candidates[0].municipality_code == "13104"
    assert response.candidates[1].municipality_code == "13123"
    assert response.candidates[1].match_score == 88.0


# ============================================================================
# 倫理 post-validation
# ============================================================================


def test_respond_detects_ethical_violation_in_reply() -> None:
    """reply に禁止語が含まれていたら ethical_violations に記録 + 安全な reply に差し替え。"""
    runner = MagicMock()
    runner.run.return_value = {
        "reply": "○○区は絶対に賛成すべきです",  # 「絶対に.{0,3}賛成」に hit
        "tool_calls": [],
        "candidates": [],
    }

    agent = ConciergeAgent(runner=runner)
    response = agent.respond(_make_request())

    assert response.ethical_violations  # 1 つ以上の違反
    assert "倫理ガイドラインに抵触" in response.reply or "別の角度" in response.reply


def test_respond_passes_clean_reply_unchanged() -> None:
    """倫理違反なしなら reply はそのまま返る。"""
    runner = MagicMock()
    clean_reply = "新宿区は人口 35 万人、子育て施設も充実しています。"
    runner.run.return_value = {"reply": clean_reply, "tool_calls": [], "candidates": []}

    agent = ConciergeAgent(runner=runner)
    response = agent.respond(_make_request())

    assert response.reply == clean_reply
    assert response.ethical_violations == []


# ============================================================================
# 例外 / fallback
# ============================================================================


def test_respond_runner_exception_returns_graceful_fallback() -> None:
    """Runner.run() が例外を投げたら、システムエラー reply + violation=['runner_exception']。"""
    runner = MagicMock()
    runner.run.side_effect = RuntimeError("Gemini timeout")

    agent = ConciergeAgent(runner=runner)
    response = agent.respond(_make_request())

    assert "システムエラー" in response.reply
    assert "runner_exception" in response.ethical_violations
    assert response.candidates == []


def test_respond_runner_returns_non_dict_falls_back_to_empty() -> None:
    """Runner が予期せぬ型 (e.g. None / string) を返しても落ちない。"""
    runner = MagicMock()
    runner.run.return_value = None

    agent = ConciergeAgent(runner=runner)
    response = agent.respond(_make_request())

    # reply は空、tool_calls / candidates も空、ethical_violations は空 (reply 自体が空なので)
    assert response.reply == ""
    assert response.tool_calls == []
    assert response.candidates == []


def test_respond_no_runner_injected_raises_not_implemented(monkeypatch: pytest.MonkeyPatch) -> None:
    """runner 未注入かつ _build_runner も未実装なら NotImplementedError をキャッチして fallback。"""
    agent = ConciergeAgent()  # runner=None
    # _build_runner は NotImplementedError を raise する → runner_failed として graceful fallback
    response = agent.respond(_make_request())

    assert "システムエラー" in response.reply
    assert "runner_exception" in response.ethical_violations


# ============================================================================
# persona_desc format
# ============================================================================


def test_format_persona_includes_all_fields() -> None:
    """ConciergeAgent._format_persona が全 persona フィールドを含める。"""
    agent = ConciergeAgent(
        runner=MagicMock(return_value={"reply": "", "tool_calls": [], "candidates": []})
    )
    req = _make_request()
    desc = agent._format_persona(req)

    assert "25-29" in desc
    assert "住居" in desc
    assert "子育て" in desc
    assert "13104" in desc
    assert "リモートワーク中心" in desc


def test_format_persona_handles_empty_optional_fields() -> None:
    """interest / 登録自治体 / free_form 未指定でも素直に組み立てる。"""
    agent = ConciergeAgent(
        runner=MagicMock(return_value={"reply": "", "tool_calls": [], "candidates": []})
    )
    req = ConciergeRequest(
        message="hello",
        persona=UserPersonaInput(user_id="anon"),  # 全 default
    )
    desc = agent._format_persona(req)

    assert "未指定" in desc  # interests
    assert "未登録" in desc  # municipality_codes
