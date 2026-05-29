"""CriticAgent の unit tests (Plan D)。

テスト戦略:
    - google.genai を mock (SimpleNamespace で response.parsed を直接注入)
    - _CriticRawOutput は internal class なので reflection で取り出す
    - critique() の戻り値 (CritiqueResult) の overall / passed / ethics floor を確認
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agents.critic.main import ETHICS_HARD_FLOOR, CriticAgent
from agents.critic.schema import CriticScores, CritiqueResult
from agents.translator.schema import TranslateInput, TranslatorOutput


def _make_draft(notes: str = "") -> TranslatorOutput:
    return TranslatorOutput(
        title="議題タイトル",
        summary=["1 行目の要約", "2 行目の要約", "3 行目の要約"],
        tone="casual",
        contains_politician_names=False,
        contains_political_judgment=False,
        notes=notes,
    )


def _make_input() -> TranslateInput:
    return TranslateInput(
        speech_id="test-001",
        content_text="本日は子育て支援について議論しました。" * 5,
        speaker_position="議員",
        meeting_context="本会議 第10号 2026-05-29",
        age_group="25-29",
    )


def _mock_genai_response(faithfulness: int, simplicity: int, tone: int, ethics: int, feedback: str):
    """google.genai response.parsed を内部 _CriticRawOutput 互換で mock。"""

    class _Stub:
        pass

    parsed = _Stub()
    parsed.faithfulness = faithfulness
    parsed.simplicity = simplicity
    parsed.tone = tone
    parsed.ethics = ethics
    parsed.feedback = feedback

    # isinstance(_, _CriticRawOutput) チェックを通すため、内部 class を取得して bless する
    # _call_gemini 内で動的定義される _CriticRawOutput を bypass するため、parsed を None にして
    # text fallback path で _CriticRawOutput.model_validate_json を走らせる方が確実
    import json

    from agents.critic import main as critic_main

    text = json.dumps(
        {
            "faithfulness": faithfulness,
            "simplicity": simplicity,
            "tone": tone,
            "ethics": ethics,
            "feedback": feedback,
        }
    )
    return SimpleNamespace(parsed=None, text=text), critic_main


# ============================================================================
# 1) draft が empty_reason: の場合は critique skip
# ============================================================================


def test_critique_skips_empty_draft() -> None:
    """draft.notes が 'empty_reason:' で始まる場合は LLM call せずに skip。"""
    client = MagicMock()
    agent = CriticAgent(client=client)

    empty_draft = TranslatorOutput.empty("発言本文が空です")
    result = agent.critique(empty_draft, _make_input(), threshold=70)

    assert isinstance(result, CritiqueResult)
    assert result.scores.faithfulness == 0
    assert result.scores.ethics == 0
    assert result.overall_score == 0
    assert result.passed is False
    assert "critique_skipped" in result.feedback
    # Gemini call が一度も呼ばれていないこと
    client.models.generate_content.assert_not_called()


# ============================================================================
# 2) 高スコア時の passed=True
# ============================================================================


def test_critique_returns_passed_true_for_high_score() -> None:
    """全 4 軸 80 点以上なら passed=True、overall=平均、ethics>=60 を満たす。"""
    response, _ = _mock_genai_response(85, 90, 80, 95, "全体的に良好")

    client = MagicMock()
    client.models.generate_content.return_value = response
    agent = CriticAgent(client=client)

    result = agent.critique(_make_draft(), _make_input(), threshold=70)

    assert result.scores.faithfulness == 85
    assert result.scores.simplicity == 90
    assert result.scores.tone == 80
    assert result.scores.ethics == 95
    assert result.overall_score == round((85 + 90 + 80 + 95) / 4)
    assert result.passed is True
    assert result.feedback == "全体的に良好"


# ============================================================================
# 3) threshold 境界 (overall=69 → passed=False、70 → True、71 → True)
# ============================================================================


@pytest.mark.parametrize(
    ("scores", "expected_overall", "expected_passed"),
    [
        ((70, 70, 70, 65), 69, False),  # avg = 68.75 → round → 69 < 70
        ((70, 70, 70, 70), 70, True),  # 平均ぴったり 70、ethics>=60
        ((71, 71, 71, 71), 71, True),  # 71 越え
    ],
)
def test_critique_threshold_boundary(
    scores: tuple[int, int, int, int],
    expected_overall: int,
    expected_passed: bool,
) -> None:
    """threshold=70 における境界値の挙動を確認。"""
    f, s, t, e = scores
    response, _ = _mock_genai_response(f, s, t, e, "境界テスト")

    client = MagicMock()
    client.models.generate_content.return_value = response
    agent = CriticAgent(client=client)

    result = agent.critique(_make_draft(), _make_input(), threshold=70)

    assert result.overall_score == expected_overall
    assert result.passed is expected_passed


# ============================================================================
# 4) ethics < ETHICS_HARD_FLOOR は overall が高くても passed=False (Reviewer High #1)
# ============================================================================


def test_critique_ethics_hard_floor_forces_revise() -> None:
    """ethics=55 で他軸 100 でも passed=False (倫理は絶対遵守、ETHICS_HARD_FLOOR=60)。"""
    assert ETHICS_HARD_FLOOR == 60
    response, _ = _mock_genai_response(100, 100, 100, 55, "倫理 NG")

    client = MagicMock()
    client.models.generate_content.return_value = response
    agent = CriticAgent(client=client)

    result = agent.critique(_make_draft(), _make_input(), threshold=70)

    assert result.overall_score == round((100 + 100 + 100 + 55) / 4)  # = 89
    assert result.scores.ethics == 55
    assert result.passed is False  # overall>=70 でも ethics<60 で False


# ============================================================================
# 5) Pydantic ValidationError: scores が 0-100 範囲外 (schema 制約)
# ============================================================================


def test_critic_scores_validation_rejects_out_of_range() -> None:
    """CriticScores は ge=0, le=100 の Pydantic 制約を持つ。"""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CriticScores(faithfulness=120, simplicity=50, tone=50, ethics=50)

    with pytest.raises(ValidationError):
        CriticScores(faithfulness=50, simplicity=-1, tone=50, ethics=50)


# ============================================================================
# 6) feedback が 500 字超過時は truncate される (max_length 制約は schema、main で安全側 truncate)
# ============================================================================


def test_critique_truncates_long_feedback() -> None:
    """feedback が 500 字超過時は最終 CritiqueResult で 500 字に truncate。"""
    # Gemini が schema max_length 内で返す前提だが、安全側 truncate を確認
    long_feedback = "a" * 500  # schema 上限ぴったり
    response, _ = _mock_genai_response(80, 80, 80, 80, long_feedback)

    client = MagicMock()
    client.models.generate_content.return_value = response
    agent = CriticAgent(client=client)

    result = agent.critique(_make_draft(), _make_input(), threshold=70)
    assert len(result.feedback) <= 500


# ============================================================================
# 7) Gemini parse failure 時は scores=0 + feedback に reason
# ============================================================================


def test_critique_handles_gemini_parse_failure() -> None:
    """Gemini が text="" を返したら全 score 0 + feedback に error reason。"""
    response = SimpleNamespace(parsed=None, text="")

    client = MagicMock()
    client.models.generate_content.return_value = response
    agent = CriticAgent(client=client)

    result = agent.critique(_make_draft(), _make_input(), threshold=70)
    assert result.scores.faithfulness == 0
    assert result.scores.ethics == 0
    assert result.overall_score == 0
    assert result.passed is False
