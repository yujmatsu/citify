"""TranslatorAgent CLI: BQ speech_id or 直接 text を翻訳。

使用例:
    # BQ から speech_id 指定で取得 → 翻訳
    python -m agents.translator \\
        --project citify-dev \\
        --speech-id 122104024X02020260428_006 \\
        --age-group 25-29

    # 直接 text 入力 (stdin or --text)
    echo "ただいまから本会議を開きます…" | python -m agents.translator \\
        --project citify-dev \\
        --age-group 18-24

    # JSON Lines バッチ (BQ から N 件取って 1 件ずつ翻訳)
    python -m agents.translator \\
        --project citify-dev \\
        --bq-query "SELECT * FROM citify-dev.citify_raw.kokkai_speeches LIMIT 3" \\
        --age-group 30-34
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .main import DEFAULT_LOCATION, DEFAULT_MODEL, TranslatorAgent
from .schema import TranslateInput

DEFAULT_BQ_TABLE = "citify-dev.citify_raw.kokkai_speeches"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.translator",
        description="Citify 翻訳 Agent (Gemini 2.5 Flash) CLI",
    )
    parser.add_argument("--project", required=True, help="GCP project ID")
    parser.add_argument("--location", default=DEFAULT_LOCATION, help="Vertex AI location")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    parser.add_argument(
        "--age-group",
        choices=["18-24", "25-29", "30-34", "35+"],
        default="25-29",
        help="ペルソナ年代区分",
    )

    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", type=str, help="翻訳対象テキスト (直接指定)")
    src.add_argument("--speech-id", type=str, help="BQ から取得する speech_id")
    src.add_argument(
        "--bq-query",
        type=str,
        help="BQ から複数取得する SQL (返り行ごとに 1 翻訳、JSON Lines 出力)",
    )

    parser.add_argument("--bq-table", default=DEFAULT_BQ_TABLE, help="--speech-id 時の参照テーブル")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="DEBUG ログ + Gemini レスポンス全文"
    )
    return parser


def _fetch_from_bq(project_id: str, table: str, speech_id: str) -> TranslateInput:
    """BQ から speech_id 指定で 1 行取得 → TranslateInput に変換。"""
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    sql = f"""
        SELECT id, speech, speaker, speaker_position, speaker_group,
               name_of_house, name_of_meeting, issue, meeting_date
        FROM `{table}`
        WHERE id = @speech_id
        LIMIT 1
    """  # noqa: S608 (table is caller-controlled)
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("speech_id", "STRING", speech_id),
            ]
        ),
    )
    rows = list(job)
    if not rows:
        raise ValueError(f"speech_id={speech_id!r} not found in {table}")
    row = rows[0]
    meeting_ctx = " ".join(
        filter(None, [row.name_of_house, row.name_of_meeting, row.issue, str(row.meeting_date)])
    )
    return TranslateInput(
        speech_id=row.id,
        content_text=row.speech,
        speaker=row.speaker,
        speaker_position=row.speaker_position,
        speaker_group=row.speaker_group,
        meeting_context=meeting_ctx,
        age_group="25-29",  # default、CLI で上書き
    )


def _fetch_batch_from_bq(project_id: str, sql: str) -> list[TranslateInput]:
    """任意の SQL でバッチ取得。"""
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    rows = client.query(sql).result()
    inputs: list[TranslateInput] = []
    for row in rows:
        meeting_ctx = " ".join(
            filter(
                None,
                [
                    getattr(row, "name_of_house", None),
                    getattr(row, "name_of_meeting", None),
                    getattr(row, "issue", None),
                    str(getattr(row, "meeting_date", "")),
                ],
            )
        )
        inputs.append(
            TranslateInput(
                speech_id=getattr(row, "id", "(unknown)"),
                content_text=getattr(row, "speech", ""),
                speaker=getattr(row, "speaker", None),
                speaker_position=getattr(row, "speaker_position", None),
                speaker_group=getattr(row, "speaker_group", None),
                meeting_context=meeting_ctx,
                age_group="25-29",
            )
        )
    return inputs


def _print_output(speech_id: str, output: object) -> None:
    """翻訳結果を人間にも読める形式で出力。"""
    data = output.model_dump() if hasattr(output, "model_dump") else dict(output)  # type: ignore[attr-defined]
    print("─" * 60)
    print(f"speech_id: {speech_id}")
    print(f"title: {data['title']}")
    for i, line in enumerate(data["summary"], 1):
        print(f"  L{i}: {line}")
    print(f"tone: {data['tone']}")
    if data["notes"]:
        print(f"notes: {data['notes']}")
    if data["contains_politician_names"] or data["contains_political_judgment"]:
        print(
            f"⚠️ ethics: politician_names={data['contains_politician_names']} "
            f"political_judgment={data['contains_political_judgment']}"
        )
    print()
    # 機械可読 JSON も末尾に
    print(json.dumps(data, ensure_ascii=False))


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    agent = TranslatorAgent(project_id=args.project, location=args.location, model=args.model)

    # 入力ソースの分岐
    inputs: list[TranslateInput] = []
    if args.text:
        inputs.append(
            TranslateInput(
                speech_id="cli-text-input",
                content_text=args.text,
                age_group=args.age_group,
            )
        )
    elif args.speech_id:
        inp = _fetch_from_bq(args.project, args.bq_table, args.speech_id)
        inp = inp.model_copy(update={"age_group": args.age_group})
        inputs.append(inp)
    elif args.bq_query:
        inputs.extend(
            inp.model_copy(update={"age_group": args.age_group})
            for inp in _fetch_batch_from_bq(args.project, args.bq_query)
        )

    if not inputs:
        print("ERROR: no inputs", file=sys.stderr)
        return 2

    for inp in inputs:
        try:
            output = agent.translate(inp)
            _print_output(inp.speech_id, output)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR translating {inp.speech_id}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
