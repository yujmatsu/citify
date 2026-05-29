"""ADK Agent orchestration demo (Plan C 完了の証跡)。

press_rss 風の fixture を以下の 3 段でチェーン実行し、各 stage の出力を表示:
    Translator ADK → Relevance ADK (5 personas) → Distributor ADK

このスクリプトは Plan C (ADK 化) の **デモ用 artifact** で、ハッカソン審査員に
「マルチエージェントが orchestration されて動いている」絵を見せるために使う。

Usage:
    # Mock mode (デフォルト、クレデンシャル不要、決定論的)
    python -m agents.demo_adk_chain

    # Live mode (実 Gemini Flash 呼び出し、GCP credentials 必要)
    python -m agents.demo_adk_chain --live --project-id citify-dev
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from unittest.mock import MagicMock

from agents.distributor.adk_agent import ADKDistributorAgent
from agents.distributor.schema import FeedCandidate
from agents.relevance.adk_agent import ADKRelevanceAgent
from agents.relevance.main import RelevanceAgent
from agents.relevance.schema import (
    PersonaRelevanceOutput,
    RelevanceInput,
    UserPersona,
)
from agents.translator.adk_agent import ADKTranslatorAgent
from agents.translator.main import TranslatorAgent
from agents.translator.schema import TranslateInput, TranslatorOutput

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# Fixture data (press_rss 風の 1 発言、新宿区の家賃補助プレス)
# ----------------------------------------------------------------------------


def make_fixture_speech() -> TranslateInput:
    """新宿区プレスリリース風の fixture speech。"""
    return TranslateInput(
        speech_id="13104:press-demo:2026-05-29:0",
        content_text=(
            "新宿区は本日、令和8年度から若年世帯向け家賃補助制度を新設すると発表しました。"
            "対象は29歳以下の単身者および35歳以下の子育て世帯で、月額最大3万円を最長2年間支給。"
            "区民の定着促進と子育て世帯の流入を狙う。総額1.5億円の予算を計上。"
        ),
        speaker=None,
        speaker_position="区長",
        speaker_group=None,
        meeting_context="新宿区プレスリリース 2026-05-29",
        age_group="25-29",
    )


def make_demo_personas() -> list[UserPersona]:
    """デモ用 5 ペルソナ。"""
    return [
        UserPersona(
            user_id="demo-18-24",
            age_group="18-24",
            interests=["住居", "雇用"],  # type: ignore[list-item]
            municipality_codes=["13104"],
        ),
        UserPersona(
            user_id="demo-25-29",
            age_group="25-29",
            interests=["住居", "結婚", "子育て"],  # type: ignore[list-item]
            municipality_codes=["13104"],
        ),
        UserPersona(
            user_id="demo-30-39",
            age_group="30-39",
            interests=["子育て", "住居", "教育"],  # type: ignore[list-item]
            municipality_codes=["13104"],
        ),
        UserPersona(
            user_id="demo-40-49",
            age_group="40-49",
            interests=["教育", "医療"],  # type: ignore[list-item]
            municipality_codes=["13104"],
        ),
        UserPersona(
            user_id="demo-50+",
            age_group="50+",
            interests=["医療", "防災"],  # type: ignore[list-item]
            municipality_codes=["13104"],
        ),
    ]


# ----------------------------------------------------------------------------
# Mock factories (--live なしの場合に使う、LLM 不要で決定論的)
# ----------------------------------------------------------------------------


def make_mock_translator() -> TranslatorAgent:
    """LLM を呼ばない fake Translator (デモ用 fixture 出力を返す)。"""
    mock = MagicMock(spec=TranslatorAgent)
    mock.translate.return_value = TranslatorOutput(
        title="新宿区、若者向け家賃補助スタート",
        summary=[
            "新宿区が若い人向けに家賃補助を始めるよ。",
            "対象は29歳以下の独身か、35歳以下の子育て世帯。",
            "毎月最大3万円、最長2年もらえる。",
        ],
        tone="casual",
        contains_politician_names=False,
        contains_political_judgment=False,
        notes="",
    )
    mock.prompt_version = "demo-v1"
    mock.model = "gemini-2.5-flash"
    return mock


def make_mock_relevance() -> RelevanceAgent:
    """LLM を呼ばない fake Relevance (ペルソナ別スコアを fixture で返す)。"""
    persona_scores = {
        "demo-18-24": (85, ["住居"]),
        "demo-25-29": (95, ["住居", "結婚"]),
        "demo-30-39": (78, ["住居", "子育て"]),
        "demo-40-49": (35, []),
        "demo-50+": (25, []),
    }

    def fake_score_multi(
        _input: RelevanceInput, personas: list[UserPersona]
    ) -> list[PersonaRelevanceOutput]:
        results = []
        for p in personas:
            score, matched = persona_scores.get(p.user_id, (50, []))
            results.append(
                PersonaRelevanceOutput(
                    user_id=p.user_id,
                    relevance_score=score,
                    score_topic=min(score // 4, 25),
                    score_age=min(score // 4, 25),
                    score_geographic=25,  # 新宿区民なので全 persona 高
                    score_urgency=min(score // 4, 25),
                    matched_interests=matched,  # type: ignore[arg-type]
                    reasoning=f"{p.age_group} の {','.join(matched) or '関心なし'} 関心に対する評価",
                    contains_political_judgment=False,
                )
            )
        return results

    mock = MagicMock(spec=RelevanceAgent)
    mock.score_multi.side_effect = fake_score_multi
    mock.prompt_version = "demo-v1"
    mock.model = "gemini-2.5-flash"
    return mock


# ----------------------------------------------------------------------------
# Chain execution
# ----------------------------------------------------------------------------


def run_chain(
    adk_translator: ADKTranslatorAgent,
    adk_relevance: ADKRelevanceAgent,
    adk_distributor: ADKDistributorAgent,
    speech: TranslateInput,
    personas: list[UserPersona],
) -> dict[str, object]:
    """3 段チェーン実行。各 stage の出力を dict で返す。"""

    # ----- Stage 1: Translator -----
    print("\n=== 🟦 Stage 1: ADK Translator ===")
    print(f"Input speech_id: {speech.speech_id}")
    print(f"Content (preview): {speech.content_text[:50]}...")

    translation = adk_translator.translate_speech(speech)

    print("Output:")
    print(json.dumps(translation.model_dump(), ensure_ascii=False, indent=2))

    # ----- Stage 2: Relevance (5 personas) -----
    print("\n=== 🟧 Stage 2: ADK Relevance (5 personas) ===")

    # Translator 出力を Relevance 入力に変換
    rel_input = RelevanceInput(
        speech_id=speech.speech_id,
        content_text=speech.content_text,
        translated_summary=translation.summary,
        title=translation.title,
        speaker_position=speech.speaker_position,
        meeting_context=speech.meeting_context,
        municipality_code="13104",  # 新宿区
        user=personas[0],  # ダミー (multi では personas で上書き)
    )
    persona_results = adk_relevance.score_speech_multi_persona(rel_input, personas)

    print(f"Scored {len(persona_results)} personas:")
    for r in persona_results:
        print(
            f"  - {r.user_id}: score={r.relevance_score} "
            f"matched={r.matched_interests} ({r.reasoning})"
        )

    # ----- Stage 3: Distributor (1 persona 分のフィード生成) -----
    # 各 persona について FeedCandidate を作って generate_feed
    print("\n=== 🟩 Stage 3: ADK Distributor (per-persona feed) ===")

    feeds_by_user: dict[str, list[dict[str, object]]] = {}
    for persona, rel in zip(personas, persona_results, strict=True):
        if rel.relevance_score < 50:
            print(f"  - {persona.user_id}: score {rel.relevance_score} < 50, フィード非掲載")
            feeds_by_user[persona.user_id] = []
            continue

        # 1 自治体・1 speech だけだが、Distributor の挙動を見るため候補リストを作る
        candidate = FeedCandidate(
            speech_id=speech.speech_id,
            title=translation.title,
            summary=translation.summary,
            tone=translation.tone,
            relevance_score=rel.relevance_score,
            score_topic=rel.score_topic,
            score_age=rel.score_age,
            score_geographic=rel.score_geographic,
            score_urgency=rel.score_urgency,
            matched_interests=rel.matched_interests,
            reasoning=rel.reasoning,
            speaker_position=speech.speaker_position,
            municipality_code="13104",
            meeting_date=date(2026, 5, 29),
            meeting_url="https://www.city.shinjuku.lg.jp/press/2026-05-29.html",
            name_of_meeting="新宿区プレスリリース",
        )
        feed = adk_distributor.generate_feed([candidate])
        for item in feed:
            print(
                f"  - {persona.user_id}: rank={item.final_rank} "
                f"adjusted={item.adjusted_score:.1f} reason='{item.display_reason}'"
            )
        feeds_by_user[persona.user_id] = [it.model_dump() for it in feed]

    print("\n=== ✅ Chain complete ===")
    return {
        "translation": translation.model_dump(),
        "persona_scores": [r.model_dump() for r in persona_results],
        "feeds_by_user": feeds_by_user,
    }


# ----------------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agents.demo_adk_chain",
        description="ADK Agent orchestration demo (Translator → Relevance → Distributor)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="実 Gemini を呼ぶ (GCP credentials 必要、Gemini Flash 課金あり)",
    )
    parser.add_argument(
        "--project-id",
        default="citify-dev",
        help="GCP project ID (--live 時のみ使用)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="DEBUG ログを出力",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    mode = "LIVE" if args.live else "MOCK"
    print("=" * 60)
    print(f"  ADK Chain Demo — mode={mode}")
    print("=" * 60)

    if args.live:
        adk_translator = ADKTranslatorAgent(project_id=args.project_id)
        adk_relevance = ADKRelevanceAgent(project_id=args.project_id)
    else:
        adk_translator = ADKTranslatorAgent(translator=make_mock_translator())
        adk_relevance = ADKRelevanceAgent(relevance=make_mock_relevance())

    adk_distributor = ADKDistributorAgent(min_relevance=50, feed_size=10)

    # Agent 構成を可視化 (審査員向け orchestration の絵)
    print("\n=== Agent Orchestration ===")
    print(f"  🟦 {adk_translator.as_agent(name='translator').name}")
    print("      → as_tool: translate_speech")
    print(f"  🟧 {adk_relevance.as_agent(name='relevance').name}")
    print("      → as_tools: score_speech_single, score_speech_multi_persona")
    print(f"  🟩 {adk_distributor.as_agent(name='distributor').name}")
    print("      → as_tool: generate_feed")

    speech = make_fixture_speech()
    personas = make_demo_personas()

    try:
        run_chain(adk_translator, adk_relevance, adk_distributor, speech, personas)
    except Exception as exc:  # noqa: BLE001
        logger.exception("demo_adk_chain failed: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
