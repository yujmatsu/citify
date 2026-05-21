"""RelevanceAgent の Pub/Sub worker (A-6)。

`citify-speech-translated` subscription から TranslatedSpeech envelope を pull し、
RelevanceAgent.score() を呼んで ScoredSpeech を `citify-speech-scored` topic に publish する。

設計:
    - 1 envelope (TranslatedSpeech) → 1 ScoredSpeech (今のところ user は env/CLI 渡しの 1 件)
    - 将来 user DB ができたら 1 envelope → N ScoredSpeech に fan-out 拡張
    - 倫理: 関連性スコアは 0-100、reasoning は 200 字以内、政党推奨検出時は below_threshold

ローカル動作確認:
    python -m agents.relevance.worker \\
        --project-id citify-dev \\
        --input-subscription citify-speech-translated-sub \\
        --output-topic citify-speech-scored \\
        --user-age-group 25-29 \\
        --user-interests 住居 雇用 税 \\
        --user-municipality-codes 33000 00000 \\
        --timeout-sec 60
"""

from __future__ import annotations

import argparse
import logging
import sys

from pkg.pubsub import MessageEnvelope, PubSubPublisher, PubSubSubscriber

from .main import DEFAULT_LOCATION, DEFAULT_MODEL, RelevanceAgent
from .schema import (
    ALL_INTERESTS,
    Interest,
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
    )


def make_handler(
    agent: RelevanceAgent,
    publisher: PubSubPublisher,
    output_topic: str,
    user: UserPersona,
):
    """1 envelope を採点 → ScoredSpeech publish する handler を生成。"""

    def handler(envelope: MessageEnvelope) -> None:
        if envelope.payload_type != "TranslatedSpeech":
            logger.warning(
                "worker.skip_non_translated_speech payload_type=%s source=%s",
                envelope.payload_type,
                envelope.source,
            )
            return

        rel_input = _envelope_to_relevance_input(envelope, user)
        score: RelevanceOutput = agent.score(rel_input)
        scored = _build_scored_speech(envelope, rel_input, score)

        out_env = MessageEnvelope.wrap(SOURCE, scored)
        attrs = {
            "speech_id": rel_input.speech_id,
            "user_id": user.user_id,
            "municipality_code": rel_input.municipality_code,
            "score": str(score.relevance_score),
        }
        publisher.publish_envelope(output_topic, out_env, attributes=attrs)
        logger.info(
            "worker.scored_published speech_id=%s user=%s score=%d matched=%s",
            rel_input.speech_id,
            user.user_id,
            score.relevance_score,
            ",".join(score.matched_interests) or "(none)",
        )

    return handler


def run_worker(
    project_id: str,
    input_subscription: str,
    output_topic: str,
    user: UserPersona,
    location: str = DEFAULT_LOCATION,
    model: str = DEFAULT_MODEL,
    timeout_sec: float | None = None,
) -> None:
    """worker 起動。"""
    agent = RelevanceAgent(project_id=project_id, location=location, model=model)
    publisher = PubSubPublisher(project_id=project_id)
    subscriber = PubSubSubscriber(project_id=project_id)

    handler = make_handler(agent, publisher, output_topic, user)
    logger.info(
        "worker.start project=%s in_sub=%s out_topic=%s user=%s timeout=%s",
        project_id,
        input_subscription,
        output_topic,
        user.user_id,
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

    # User persona (将来 user DB / Firestore に切り替え)
    parser.add_argument("--user-id", default="anonymous", help="ペルソナ ID")
    parser.add_argument(
        "--user-age-group",
        choices=["18-24", "25-29", "30-34", "35+"],
        default="25-29",
    )
    parser.add_argument(
        "--user-interests",
        nargs="*",
        default=[],
        choices=list(ALL_INTERESTS),
        help="関心軸 (10 軸から選択、複数可)",
    )
    parser.add_argument(
        "--user-municipality-codes",
        nargs="*",
        default=[],
        help="登録自治体コード (5 桁、複数可)",
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

    interests: list[Interest] = list(args.user_interests)
    user = UserPersona(
        user_id=args.user_id,
        age_group=args.user_age_group,
        interests=interests,
        municipality_codes=list(args.user_municipality_codes),
    )

    run_worker(
        project_id=args.project_id,
        input_subscription=args.input_subscription,
        output_topic=args.output_topic,
        user=user,
        location=args.location,
        model=args.model,
        timeout_sec=args.timeout_sec,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
