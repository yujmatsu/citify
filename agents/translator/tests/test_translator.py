"""TranslatorAgent のユニットテスト (Gemini を mock、実 API 不要)。"""

from __future__ import annotations

import pytest

from agents.translator.main import TranslatorAgent
from agents.translator.schema import TranslateInput, TranslatorOutput


class _MockGenAIModels:
    """google.genai.Client.models の mock。テストで返す TranslatorOutput を指定可能。"""

    def __init__(self, responses: list[TranslatorOutput]) -> None:
        self.responses = list(responses)
        self.call_count = 0
        self.last_call_args: dict = {}

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: object,
    ) -> object:
        self.last_call_args = {"model": model, "contents": contents, "config": config}
        idx = min(self.call_count, len(self.responses) - 1)
        self.call_count += 1
        parsed = self.responses[idx]

        class _MockResponse:
            def __init__(self, parsed: TranslatorOutput) -> None:
                self.parsed = parsed
                self.text = parsed.model_dump_json()

        return _MockResponse(parsed)


class _MockGenAIClient:
    """google.genai.Client の mock。"""

    def __init__(self, responses: list[TranslatorOutput]) -> None:
        self.models = _MockGenAIModels(responses)


def _make_good_output() -> TranslatorOutput:
    return TranslatorOutput(
        title="子育て支援の予算強化",
        summary=[
            "国は若い世代の所得を増やし、児童手当を拡充する方針を示した。",
            "妊娠期から育児期まで切れ目ない支援を行う計画もある。",
            "保育士の処遇改善や柔軟な働き方の推進も含まれる。",
        ],
        tone="casual",
        contains_politician_names=False,
        contains_political_judgment=False,
        notes="",
    )


def _make_input() -> TranslateInput:
    return TranslateInput(
        speech_id="test-123",
        content_text=(
            "このため、こども未来戦略の加速化プランに基づきまして、賃上げなど"
            "若い世代の所得を増やす取組や、児童手当などの抜本的な拡充を実施いたします。"
        ),
        speaker="石破茂",
        speaker_position="内閣総理大臣",
        speaker_group="自由民主党",
        meeting_context="衆議院 本会議 第16号 2026-05-18",
        age_group="25-29",
    )


# ============================================================================
# 正常系
# ============================================================================


def test_translate_returns_parsed_output_on_first_try():
    """Gemini が clean な出力を返したら 1 回で成功。"""
    output = _make_good_output()
    client = _MockGenAIClient([output])
    agent = TranslatorAgent(project_id="test", client=client)

    result = agent.translate(_make_input())

    assert result == output
    assert client.models.call_count == 1


def test_translate_passes_system_prompt_and_response_schema():
    """call_args に system_instruction + response_schema が含まれる。"""
    client = _MockGenAIClient([_make_good_output()])
    agent = TranslatorAgent(project_id="test", client=client)

    agent.translate(_make_input())

    call = client.models.last_call_args
    assert call["model"] == "gemini-2.5-flash"
    # system_instruction には倫理ルールが含まれる
    config = call["config"]
    sys_inst = getattr(config, "system_instruction", "")
    assert "倫理" in sys_inst or "固有名詞" in sys_inst
    # contents には発言本文 + 年代が含まれる
    assert "児童手当" in call["contents"]
    assert "25-29" in call["contents"]


def test_translate_uses_age_group_in_prompt():
    """年代を変えると prompt の tone hint が変わる。"""
    client = _MockGenAIClient([_make_good_output()])
    agent = TranslatorAgent(project_id="test", client=client)

    inp = _make_input().model_copy(update={"age_group": "35+"})
    agent.translate(inp)

    assert "35+" in client.models.last_call_args["contents"]


# ============================================================================
# 倫理ガードレール
# ============================================================================


def test_speaker_name_leak_triggers_retry():
    """summary に発言者名 '石破茂' が混入したらリトライ、2 回目で OK。"""
    bad = TranslatorOutput(
        title="石破茂が方針を示す",  # 固有名詞混入
        summary=[
            "国は若い世代の所得を増やす。",
            "児童手当を拡充する。",
            "切れ目ない支援を行う。",
        ],
        tone="neutral",
        contains_politician_names=False,  # LLM 自己申告は False (実際は混入)
        contains_political_judgment=False,
        notes="",
    )
    good = _make_good_output()
    client = _MockGenAIClient([bad, good])
    agent = TranslatorAgent(project_id="test", client=client)

    result = agent.translate(_make_input())

    assert client.models.call_count == 2
    assert "石破" not in result.title


def test_party_name_leak_triggers_retry():
    """summary に政党名が混入したらリトライ。"""
    bad = TranslatorOutput(
        title="自由民主党が方針を示す",
        summary=[
            "国は若い世代の所得を増やす。",
            "児童手当を拡充する。",
            "切れ目ない支援を行う。",
        ],
        tone="neutral",
        contains_politician_names=False,
        contains_political_judgment=False,
        notes="",
    )
    good = _make_good_output()
    client = _MockGenAIClient([bad, good])
    agent = TranslatorAgent(project_id="test", client=client)

    result = agent.translate(_make_input())

    assert client.models.call_count == 2
    assert "自由民主党" not in result.title


def test_llm_self_reported_politician_names_triggers_retry():
    """LLM が contains_politician_names=True と申告したらリトライ。"""
    bad = TranslatorOutput(
        title="予算強化方針",
        summary=["a" * 30, "b" * 30, "c" * 30],
        tone="neutral",
        contains_politician_names=True,
        contains_political_judgment=False,
        notes="",
    )
    good = _make_good_output()
    client = _MockGenAIClient([bad, good])
    agent = TranslatorAgent(project_id="test", client=client)

    agent.translate(_make_input())

    assert client.models.call_count == 2


def test_forbidden_pattern_triggers_retry():
    """禁止語 '投票推奨' 等が含まれたらリトライ。"""
    bad = TranslatorOutput(
        title="投票を推奨します",
        summary=["a" * 30, "b" * 30, "c" * 30],
        tone="neutral",
        contains_politician_names=False,
        contains_political_judgment=False,
        notes="",
    )
    good = _make_good_output()
    client = _MockGenAIClient([bad, good])
    agent = TranslatorAgent(project_id="test", client=client)

    agent.translate(_make_input())

    assert client.models.call_count == 2


def test_three_retries_then_empty():
    """3 回連続で倫理違反したら empty 返却。"""
    bad = TranslatorOutput(
        title="石破茂",
        summary=["石破茂が発言", "b" * 30, "c" * 30],
        tone="neutral",
        contains_politician_names=False,
        contains_political_judgment=False,
        notes="",
    )
    client = _MockGenAIClient([bad, bad, bad])
    agent = TranslatorAgent(project_id="test", client=client)

    result = agent.translate(_make_input())

    assert client.models.call_count == 3
    assert "倫理ガードレール" in result.summary[0] or "翻訳できませんでした" in result.title


# ============================================================================
# 早期 return
# ============================================================================


def test_empty_input_returns_empty_immediately():
    """空 text なら Gemini 呼ばずに empty 返却。"""
    client = _MockGenAIClient([_make_good_output()])
    agent = TranslatorAgent(project_id="test", client=client)

    inp = _make_input().model_copy(update={"content_text": "   "})
    result = agent.translate(inp)

    assert client.models.call_count == 0
    assert "空" in result.summary[0]


# ============================================================================
# Schema バリデーション
# ============================================================================


def test_summary_must_be_exactly_three_lines():
    """summary が 3 行でないと Pydantic ValidationError。"""
    with pytest.raises(Exception):  # noqa: B017
        TranslatorOutput(
            title="x",
            summary=["a", "b"],  # 2 行のみ
            tone="neutral",
            contains_politician_names=False,
            contains_political_judgment=False,
        )


def test_title_max_length_40():
    """title が 40 字超で ValidationError。"""
    with pytest.raises(Exception):  # noqa: B017
        TranslatorOutput(
            title="x" * 41,
            summary=["a", "b", "c"],
            tone="neutral",
            contains_politician_names=False,
            contains_political_judgment=False,
        )
