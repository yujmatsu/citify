"""TranslatorAgent の Pub/Sub worker (A-5)。

`citify-speech-translate` subscription から speech envelope を pull し、
TranslatorAgent.translate() を呼んで結果を `citify-speech-translated` topic に publish する。

Cloud Run Worker 想定 (Pub/Sub の streaming pull、scale-to-zero 対応):
    - --no-allow-unauthenticated で deploy
    - service-account = citify-api-runtime
    - min-instances=0, max-instances=1 (翻訳は逐次でも十分なペース)
    - timeout=600 (1 メッセージ最大 ~30 秒、ack_deadline=60 秒)

ローカル動作確認:
    python -m agents.translator.worker \\
        --project-id citify-dev \\
        --input-subscription citify-speech-translate-sub \\
        --output-topic citify-speech-translated \\
        --timeout-sec 60   # 60 秒で停止 (本番では指定しない)
"""

from __future__ import annotations

import argparse
import logging
import sys

from pkg.municipality_map import resolve_municipality_code
from pkg.pubsub import MessageEnvelope, PubSubPublisher, PubSubSubscriber

from .main import DEFAULT_LOCATION, DEFAULT_MODEL, TranslatorAgent
from .schema import TranslatedSpeech, TranslateInput, TranslatorOutput

logger = logging.getLogger(__name__)

# Speech envelope の必須キー (kaigiroku Speech model_dump 由来)
REQUIRED_KEYS = ("tenant_id", "council_id", "speaker", "content_text", "detail_url")
SOURCE = "translator"


def _envelope_to_translate_input(envelope: MessageEnvelope) -> TranslateInput:
    """受信した envelope.payload (Speech.model_dump) を TranslateInput に変換。

    Speech (scraper) → TranslateInput (translator) のフィールドマッピング:
        - speech_id ← council_id + ":" + schedule_id + ":" + speech_order (合成 ID)
        - content_text ← content_text
        - speaker_position ← speaker_position
        - speaker ← speaker
        - meeting_context ← name_of_meeting + meeting_date
    """
    p = envelope.payload
    missing = [k for k in REQUIRED_KEYS if k not in p]
    if missing:
        raise ValueError(f"envelope.payload missing keys: {missing}")

    council_id = p.get("council_id", "")
    schedule_id = p.get("schedule_id") or ""
    speech_order = p.get("speech_order", 0)
    speech_id = f"{p.get('tenant_id', '?')}:{council_id}:{schedule_id}:{speech_order}"

    meeting_ctx_parts = [
        p.get("name_of_meeting") or "",
        str(p.get("meeting_date") or ""),
    ]
    meeting_context = " ".join(s for s in meeting_ctx_parts if s).strip()

    return TranslateInput(
        speech_id=speech_id,
        content_text=p.get("content_text", ""),
        speaker=p.get("speaker"),
        speaker_position=p.get("speaker_position"),
        speaker_group=None,  # kaigiroku は政党情報を持たない
        meeting_context=meeting_context,
        age_group="25-29",  # default、worker レベルでは固定 (将来 attributes 経由で渡す)
    )


def _build_translated_speech(
    envelope: MessageEnvelope,
    translate_input: TranslateInput,
    translation: TranslatorOutput,
) -> TranslatedSpeech:
    """原典 Speech メタ + 翻訳結果を 1 つの TranslatedSpeech にまとめる。"""
    p = envelope.payload
    municipality_code = resolve_municipality_code(envelope.source, p.get("tenant_id"))

    # meeting_date は str (ISO) で来るので date に変換 (Pydantic 自動)
    return TranslatedSpeech(
        speech_id=translate_input.speech_id,
        tenant_id=p.get("tenant_id", ""),
        council_id=p.get("council_id", ""),
        schedule_id=p.get("schedule_id"),
        municipality_code=municipality_code,
        meeting_date=p.get("meeting_date"),
        name_of_meeting=p.get("name_of_meeting") or "",
        speaker_position=p.get("speaker_position"),
        detail_url=p.get("detail_url") or "",
        content_text=p.get("content_text", ""),
        translation=translation,
    )


def make_handler(
    agent: TranslatorAgent,
    publisher: PubSubPublisher,
    output_topic: str,
):
    """1 envelope を翻訳 → publish する handler を生成。"""

    def handler(envelope: MessageEnvelope) -> None:
        if envelope.payload_type != "Speech":
            logger.warning(
                "worker.skip_non_speech payload_type=%s source=%s",
                envelope.payload_type,
                envelope.source,
            )
            return

        translate_input = _envelope_to_translate_input(envelope)
        if not translate_input.content_text.strip():
            logger.warning("worker.skip_empty_content speech_id=%s", translate_input.speech_id)
            return

        translation: TranslatorOutput = agent.translate(translate_input)

        # 原典 speech メタ + 翻訳結果を combined payload に
        translated = _build_translated_speech(envelope, translate_input, translation)
        out_env = MessageEnvelope.wrap(SOURCE, translated)
        attrs = {
            "speech_id": translate_input.speech_id,
            "upstream_source": envelope.source,
            "municipality_code": translated.municipality_code,
        }
        publisher.publish_envelope(output_topic, out_env, attributes=attrs)
        logger.info(
            "worker.translated_published speech_id=%s muni=%s title=%r",
            translate_input.speech_id,
            translated.municipality_code,
            translation.title[:30],
        )

    return handler


def run_worker(
    project_id: str,
    input_subscription: str,
    output_topic: str,
    location: str = DEFAULT_LOCATION,
    model: str = DEFAULT_MODEL,
    timeout_sec: float | None = None,
) -> None:
    """worker 起動 (Cloud Run / ローカル両対応)。"""
    agent = TranslatorAgent(project_id=project_id, location=location, model=model)
    publisher = PubSubPublisher(project_id=project_id)
    subscriber = PubSubSubscriber(project_id=project_id)

    handler = make_handler(agent, publisher, output_topic)
    logger.info(
        "worker.start project=%s in_sub=%s out_topic=%s timeout=%s",
        project_id,
        input_subscription,
        output_topic,
        timeout_sec,
    )
    subscriber.run(subscription=input_subscription, handler=handler, timeout_sec=timeout_sec)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.translator.worker",
        description="Translator Pub/Sub worker (A-5)",
    )
    parser.add_argument("--project-id", required=True, help="GCP project ID")
    parser.add_argument(
        "--input-subscription",
        default="citify-speech-translate-sub",
        help="入力 subscription 名",
    )
    parser.add_argument(
        "--output-topic",
        default="citify-speech-translated",
        help="出力 topic 名",
    )
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=None,
        help="N 秒後に停止 (None で永続実行、Cloud Run では未指定)",
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
    run_worker(
        project_id=args.project_id,
        input_subscription=args.input_subscription,
        output_topic=args.output_topic,
        location=args.location,
        model=args.model,
        timeout_sec=args.timeout_sec,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
