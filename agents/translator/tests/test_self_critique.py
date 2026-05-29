"""TranslatorAgent.translate_with_critique() の integration tests (Plan D)。

テスト戦略:
    - CriticAgent は MagicMock で差し替え (critic.critique の戻り値を制御)
    - TranslatorAgent の Gemini client も mock
    - 検証ポイント: revise 有無 / initial_score 保持 / empty draft skip / DI 受け取り
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agents.critic.schema import CriticScores, CritiqueResult
from agents.translator.main import DEFAULT_CRITIQUE_THRESHOLD, TranslatorAgent
from agents.translator.schema import (
    TranslateInput,
    TranslatorOutput,
    TranslatorWithCritique,
)


def _make_input() -> TranslateInput:
    return TranslateInput(
        speech_id="critique-test-001",
        content_text="子育て世帯への補助金制度について議論しました。" * 5,
        speaker_position="議員",
        meeting_context="本会議 第10号",
        age_group="25-29",
    )


def _make_output(
    title: str = "子育て補助金制度の議論",
    summary: list[str] | None = None,
    notes: str = "",
) -> TranslatorOutput:
    return TranslatorOutput(
        title=title,
        summary=summary or ["1 行目要約", "2 行目要約", "3 行目要約"],
        tone="casual",
        contains_politician_names=False,
        contains_political_judgment=False,
        notes=notes,
    )


def _make_critique(
    overall: int = 80,
    ethics: int = 90,
    passed: bool = True,
    feedback: str = "良好",
) -> CritiqueResult:
    return CritiqueResult(
        scores=CriticScores(faithfulness=80, simplicity=80, tone=80, ethics=ethics),
        overall_score=overall,
        feedback=feedback,
        passed=passed,
    )


def _mock_genai_client_returning(output: TranslatorOutput) -> MagicMock:
    """generate_content の戻り値が response.parsed = output になる client mock。"""
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(parsed=output, text="")
    return client


# ============================================================================
# 1) 初回 draft が threshold 以上で passed=True → revision_count=0
# ============================================================================


def test_translate_with_critique_passes_first_returns_revision_count_0() -> None:
    """初回 draft で critic.passed=True なら revise なし、initial_score は overall と同じ。"""
    draft_output = _make_output()
    translator_client = _mock_genai_client_returning(draft_output)
    agent = TranslatorAgent(client=translator_client)

    critic = MagicMock()
    critic.critique.return_value = _make_critique(overall=85, ethics=90, passed=True)

    result = agent.translate_with_critique(_make_input(), critic=critic)

    assert isinstance(result, TranslatorWithCritique)
    assert result.translation == draft_output
    assert result.revision_count == 0
    assert result.initial_score == 85
    assert result.critique.overall_score == 85
    assert result.critique.passed is True
    # critic.critique は 1 度だけ呼ばれる (revise なし)
    assert critic.critique.call_count == 1
    # generate_content も translate() 1 回のみ (revise なし)
    assert translator_client.models.generate_content.call_count == 1


# ============================================================================
# 2) 初回 passed=False → revise → revision_count=1, initial_score 保持
# ============================================================================


def test_translate_with_critique_revises_when_below_threshold() -> None:
    """初回 score=50 で passed=False なら revise を 1 度実行、initial_score=50 を保持。"""
    draft_output = _make_output(title="低品質 draft")
    revised_output = _make_output(title="改善版")

    translator_client = MagicMock()
    # 1 回目 = draft, 2 回目 = revise 後
    translator_client.models.generate_content.side_effect = [
        SimpleNamespace(parsed=draft_output, text=""),
        SimpleNamespace(parsed=revised_output, text=""),
    ]
    agent = TranslatorAgent(client=translator_client)

    critic = MagicMock()
    critic.critique.side_effect = [
        _make_critique(overall=50, ethics=70, passed=False, feedback="平易さを改善せよ"),
        _make_critique(overall=85, ethics=90, passed=True, feedback="改善された"),
    ]

    result = agent.translate_with_critique(_make_input(), critic=critic)

    assert result.revision_count == 1
    assert result.initial_score == 50  # ← 改善幅 demo 用、保持
    assert result.translation == revised_output
    assert result.critique.overall_score == 85
    # critic は 2 回呼ばれる (初回 + revise 後)
    assert critic.critique.call_count == 2
    # generate_content も 2 回 (draft + revise)
    assert translator_client.models.generate_content.call_count == 2


# ============================================================================
# 3) ethics hard floor (revise しても passed=False のまま) でも cost cap で return
# ============================================================================


def test_translate_with_critique_caps_at_one_revision_even_if_still_failing() -> None:
    """revise 後も critic.passed=False でも 1 round で return (cost cap)。"""
    draft_output = _make_output(title="ダメ draft")
    revised_output = _make_output(title="まだダメな revise")

    translator_client = MagicMock()
    translator_client.models.generate_content.side_effect = [
        SimpleNamespace(parsed=draft_output, text=""),
        SimpleNamespace(parsed=revised_output, text=""),
    ]
    agent = TranslatorAgent(client=translator_client)

    critic = MagicMock()
    critic.critique.side_effect = [
        _make_critique(overall=40, ethics=50, passed=False),
        _make_critique(overall=55, ethics=55, passed=False),  # 改善したが threshold 未達
    ]

    result = agent.translate_with_critique(_make_input(), critic=critic)

    assert result.revision_count == 1
    assert result.initial_score == 40
    assert result.translation == revised_output
    assert result.critique.passed is False  # revise 後も False、それでも return (cost cap)
    assert critic.critique.call_count == 2


# ============================================================================
# 4) empty draft (translate() が empty を返した場合) は revise skip (Reviewer High #2)
# ============================================================================


def test_translate_with_critique_skips_revise_for_empty_draft() -> None:
    """translate() が empty() を返した場合は critic skip (CriticAgent 側で対応) + revise しない。"""
    # translator client 自体は呼ばれない (空入力で短絡)
    agent = TranslatorAgent(client=MagicMock())

    empty_input = TranslateInput(
        speech_id="empty-001",
        content_text="",  # 空入力で translate() が empty() を返す
        age_group="25-29",
    )

    critic = MagicMock()
    # critic は empty draft を見て skip CritiqueResult を返す (CriticAgent の実装に合わせる)
    critic.critique.return_value = CritiqueResult.empty_skip("empty_reason: 発言本文が空です")

    result = agent.translate_with_critique(empty_input, critic=critic)

    assert result.revision_count == 0  # revise しない
    assert result.initial_score == 0
    assert result.translation.notes.startswith("empty_reason:")
    assert result.critique.passed is False
    assert "critique_skipped" in result.critique.feedback


# ============================================================================
# 5) DI: critic が None を渡されないことの担保 (型エラー & 明示的引数)
# ============================================================================


def test_translate_with_critique_requires_critic_argument() -> None:
    """critic は positional/keyword 必須引数 (DI 強制、テスト可能性確保)。"""
    import inspect

    sig = inspect.signature(TranslatorAgent.translate_with_critique)
    assert "critic" in sig.parameters
    # critic に default 値がないこと
    assert sig.parameters["critic"].default is inspect.Parameter.empty


# ============================================================================
# 6) threshold custom 値を渡せる
# ============================================================================


def test_translate_with_critique_passes_threshold_to_critic() -> None:
    """threshold 引数が critic.critique に渡されること。"""
    draft_output = _make_output()
    agent = TranslatorAgent(client=_mock_genai_client_returning(draft_output))

    critic = MagicMock()
    critic.critique.return_value = _make_critique(overall=90, passed=True)

    agent.translate_with_critique(_make_input(), critic=critic, threshold=85)

    # critic.critique の threshold kwarg が 85 で渡される
    _, call_kwargs = critic.critique.call_args
    assert call_kwargs.get("threshold") == 85


# ============================================================================
# 7) default threshold = 70
# ============================================================================


def test_default_critique_threshold_is_70() -> None:
    """miniplan で合意した default threshold が module constant で 70 になっている。"""
    assert DEFAULT_CRITIQUE_THRESHOLD == 70


# ============================================================================
# 8) initial_score は revise 前の値を確実に保持 (改善幅 demo 用)
# ============================================================================


def test_translate_with_critique_preserves_initial_score_across_revise() -> None:
    """revise 後の overall_score と initial_score が独立して保持される (demo の改善幅可視化)。"""
    draft_output = _make_output()
    revised_output = _make_output(title="改善版")

    translator_client = MagicMock()
    translator_client.models.generate_content.side_effect = [
        SimpleNamespace(parsed=draft_output, text=""),
        SimpleNamespace(parsed=revised_output, text=""),
    ]
    agent = TranslatorAgent(client=translator_client)

    critic = MagicMock()
    critic.critique.side_effect = [
        _make_critique(overall=42, passed=False),
        _make_critique(overall=88, passed=True),
    ]

    result = agent.translate_with_critique(_make_input(), critic=critic)

    assert result.initial_score == 42
    assert result.critique.overall_score == 88
    # 改善幅 = +46 (demo で可視化可能)
    assert result.critique.overall_score - result.initial_score == 46
