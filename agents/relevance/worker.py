"""RelevanceAgent の Pub/Sub worker (A-6 + Phase Y multi-persona fan-out)。

`citify-speech-translated` subscription から TranslatedSpeech envelope を pull し、
RelevanceAgent.score_multi() で N ペルソナを 1 API 呼び出しで一括採点、
各ペルソナ分の ScoredSpeech を `citify-speech-scored` topic に publish する。

設計:
    - 1 envelope (TranslatedSpeech) → N ScoredSpeech (N = personas.json の件数)
    - 1 Gemini 呼び出し / 1 envelope (token は ペルソナ数に応じて増えるが API 呼び出しは 1 回)
    - 倫理: 関連性スコアは 0-100、reasoning は 200 字以内、政党推奨検出時は below_threshold
    - 個別 persona の倫理違反は当該 persona のみ below_threshold (他は通常公開)

ローカル動作確認:
    python -m agents.relevance.worker \\
        --project-id citify-dev \\
        --input-subscription citify-speech-translated-sub \\
        --output-topic citify-speech-scored \\
        --personas-file agents/relevance/personas.json \\
        --timeout-sec 60

旧 (single-persona、CLI 互換性のため残置):
    python -m agents.relevance.worker \\
        --project-id citify-dev \\
        --input-subscription citify-speech-translated-sub \\
        --output-topic citify-speech-scored \\
        --user-age-group 25-29 \\
        --user-interests 住居 雇用 税
"""

from __future__ import annotations

import argparse
import logging
import sys

from pkg.pubsub import MessageEnvelope, PubSubPublisher, PubSubSubscriber

from .main import DEFAULT_LOCATION, DEFAULT_MODEL, RelevanceAgent
from .personas import DEFAULT_PERSONAS_PATH, load_personas
from .schema import (
    ALL_INTERESTS,
    Interest,
    PersonaRelevanceOutput,
    RelevanceInput,
    RelevanceOutput,
    ScoredSpeech,
    UserPersona,
)

logger = logging.getLogger(__name__)

SOURCE = "relevance"

# TranslatedSpeech payload の必須キー
REQUIRED_KEYS = ("speech_id", "municipality_code", "translation", "content_text")


def _envelope_to_relevance_input(
    envelope: MessageEnvelope,
    user: UserPersona,
) -> RelevanceInput:
    """TranslatedSpeech 受信 envelope → RelevanceInput に変換。"""
    p = envelope.payload
    missing = [k for k in REQUIRED_KEYS if k not in p]
    if missing:
        raise ValueError(f"envelope.payload missing keys: {missing}")

    translation = p["translation"]  # dict (TranslatorOutput.model_dump 由来)
    summary = translation.get("summary") if isinstance(translation, dict) else None
    title = translation.get("title") if isinstance(translation, dict) else None

    meeting_ctx_parts = [
        p.get("name_of_meeting") or "",
        str(p.get("meeting_date") or ""),
    ]
    meeting_context = " ".join(s for s in meeting_ctx_parts if s).strip()

    return RelevanceInput(
        speech_id=p["speech_id"],
        content_text=p.get("content_text", ""),
        translated_summary=summary,
        title=title,
        speaker_position=p.get("speaker_position"),
        meeting_context=meeting_context,
        municipality_code=p.get("municipality_code", "00000"),
        user=user,
    )


def _build_scored_speech(
    envelope: MessageEnvelope,
    rel_input: RelevanceInput,
    score: RelevanceOutput,
) -> ScoredSpeech:
    """RelevanceOutput + 原典参照を ScoredSpeech にまとめる。"""
    p = envelope.payload
    translation = p.get("translation", {}) or {}
    return ScoredSpeech(
        speech_id=rel_input.speech_id,
        user_id=rel_input.user.user_id,
        municipality_code=rel_input.municipality_code,
        title=translation.get("title", ""),
        summary=translation.get("summary", []),
        detail_url=p.get("detail_url", ""),
        meeting_date=p.get("meeting_date") if isinstance(p.get("meeting_date"), str) else None,
        score=score,
        # distributor (A-7) 用メタ
        speaker_position=p.get("speaker_position"),
        name_of_meeting=p.get("name_of_meeting"),
        tone=translation.get("tone"),
    )


def make_handler(
    agent: RelevanceAgent,
    publisher: PubSubPublisher,
    output_topic: str,
    personas: list[UserPersona],
):
    """1 envelope を N ペルソナ分採点 → N 件 ScoredSpeech publish する handler を生成。"""

    def handler(envelope: MessageEnvelope) -> None:
        if envelope.payload_type != "TranslatedSpeech":
            logger.warning(
                "worker.skip_non_translated_speech payload_type=%s source=%s",
                envelope.payload_type,
                envelope.source,
            )
            return

        # 入力 envelope はペルソナ独立、user_id 情報は不要なので personas[0] を仮にセット
        rel_input = _envelope_to_relevance_input(envelope, personas[0])
        persona_outputs: list[PersonaRelevanceOutput] = agent.score_multi(rel_input, personas)

        for persona, p_out in zip(personas, persona_outputs, strict=True):
            score: RelevanceOutput = p_out.to_relevance_output()
            # ScoredSpeech は per-user の input を必要とするため再構築
            per_user_input = rel_input.model_copy(update={"user": persona})
            scored = _build_scored_speech(envelope, per_user_input, score)

            out_env = MessageEnvelope.wrap(SOURCE, scored)
            attrs = {
                "speech_id": rel_input.speech_id,
                "user_id": persona.user_id,
                "municipality_code": rel_input.municipality_code,
                "score": str(score.relevance_score),
            }
            publisher.publish_envelope(output_topic, out_env, attributes=attrs)
            logger.info(
                "worker.scored_published speech_id=%s user=%s score=%d matched=%s",
                rel_input.speech_id,
                persona.user_id,
                score.relevance_score,
                ",".join(score.matched_interests) or "(none)",
            )

    return handler


def run_worker(
    project_id: str,
    input_subscription: str,
    output_topic: str,
    personas: list[UserPersona],
    location: str = DEFAULT_LOCATION,
    model: str = DEFAULT_MODEL,
    timeout_sec: float | None = None,
) -> None:
    """worker 起動 (N ペルソナ multi fan-out)。"""
    agent = RelevanceAgent(project_id=project_id, location=location, model=model)
    publisher = PubSubPublisher(project_id=project_id)
    subscriber = PubSubSubscriber(project_id=project_id)

    handler = make_handler(agent, publisher, output_topic, personas)
    logger.info(
        "worker.start project=%s in_sub=%s out_topic=%s personas=%s timeout=%s",
        project_id,
        input_subscription,
        output_topic,
        [p.user_id for p in personas],
        timeout_sec,
    )
    subscriber.run(subscription=input_subscription, handler=handler, timeout_sec=timeout_sec)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.relevance.worker",
        description="Relevance Pub/Sub worker (A-6)",
    )
    parser.add_argument("--project-id", required=True, help="GCP project ID")
    parser.add_argument(
        "--input-subscription",
        default="citify-speech-translated-sub",
        help="入力 subscription 名",
    )
    parser.add_argument(
        "--output-topic",
        default="citify-speech-scored",
        help="出力 topic 名",
    )
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--model", default=DEFAULT_MODEL)

    # Multi-persona (Phase Y): personas.json を読む方式を推奨
    parser.add_argument(
        "--personas-file",
        type=str,
        default=None,
        help=f"ペルソナ JSON ファイル (default: {DEFAULT_PERSONAS_PATH})",
    )

    # Legacy: 単一 persona CLI 指定 (--personas-file が未指定の場合のみ有効)
    parser.add_argument("--user-id", default="anonymous", help="(legacy) 単一ペルソナ ID")
    parser.add_argument(
        "--user-age-group",
        choices=["18-24", "25-29", "30-39", "40-49", "50+"],
        default="25-29",
    )
    parser.add_argument(
        "--user-interests",
        nargs="*",
        default=[],
        choices=list(ALL_INTERESTS),
        help="(legacy) 単一ペルソナの関心軸",
    )
    parser.add_argument(
        "--user-municipality-codes",
        nargs="*",
        default=[],
        help="(legacy) 単一ペルソナの登録自治体コード",
    )

    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=None,
        help="N 秒後に停止 (None で永続実行)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    # Personas 決定: --personas-file 指定なら JSON、なければ legacy CLI single-persona
    if args.personas_file is not None:
        personas = load_personas(args.personas_file)
    elif args.user_id != "anonymous" or args.user_interests:
        # legacy single-persona path (テスト・ローカル向け)
        interests: list[Interest] = list(args.user_interests)
        personas = [
            UserPersona(
                user_id=args.user_id,
                age_group=args.user_age_group,
                interests=interests,
                municipality_codes=list(args.user_municipality_codes),
            )
        ]
    else:
        # default: パッケージ同梱の personas.json
        personas = load_personas()

    if not personas:
        raise SystemExit("no personas configured (check --personas-file or CLI flags)")

    run_worker(
        project_id=args.project_id,
        input_subscription=args.input_subscription,
        output_topic=args.output_topic,
        personas=personas,
        location=args.location,
        model=args.model,
        timeout_sec=args.timeout_sec,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
