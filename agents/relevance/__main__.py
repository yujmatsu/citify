"""RelevanceAgent CLI: 1 speech × 1 ペルソナのスコア算出。

使用例:
    # ペルソナ手動指定 (子育て + 住居、25-29、新宿区+国会登録)
    python -m agents.relevance \\
        --project citify-dev \\
        --speech-id 122105261X00620260305_128 \\
        --age-group 25-29 \\
        --interests 子育て,住居 \\
        --municipalities 13104,00000

    # A-5 翻訳と組み合わせ (translated_summary を pipeline で渡す想定、Phase F+ の統合実装で)
    # 現状は CLI からは raw speech のみ評価
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from .main import DEFAULT_LOCATION, DEFAULT_MODEL, RelevanceAgent
from .schema import ALL_INTERESTS, RelevanceInput, UserPersona

DEFAULT_BQ_TABLE = "citify-dev.citify_raw.kokkai_speeches"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.relevance",
        description="Citify 影響度 Agent (Gemini 2.5 Flash) CLI",
    )
    parser.add_argument("--project", required=True, help="GCP project ID")
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--model", default=DEFAULT_MODEL)

    # speech input
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", type=str, help="評価対象テキスト (直接指定)")
    src.add_argument("--speech-id", type=str, help="BQ から取得する speech_id")
    src.add_argument(
        "--bq-query",
        type=str,
        help="BQ から複数取得する SQL (各 row 評価、batch スコアリング)",
    )

    # persona
    parser.add_argument(
        "--age-group",
        choices=["18-24", "25-29", "30-34", "35+"],
        default="25-29",
    )
    parser.add_argument(
        "--interests",
        type=str,
        default="",
        help=f"カンマ区切り関心軸 ({','.join(ALL_INTERESTS)} のサブセット)",
    )
    parser.add_argument(
        "--municipalities",
        type=str,
        default="00000",
        help="カンマ区切り自治体コード 5 桁 (例: 13104,00000)",
    )
    parser.add_argument("--user-id", type=str, default="cli-anonymous")

    parser.add_argument("--bq-table", default=DEFAULT_BQ_TABLE)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _parse_interests(raw: str) -> list[str]:
    if not raw:
        return []
    items = [s.strip() for s in raw.split(",") if s.strip()]
    invalid = [i for i in items if i not in ALL_INTERESTS]
    if invalid:
        raise ValueError(f"無効な関心軸: {invalid}. 有効値: {list(ALL_INTERESTS)}")
    return items


def _fetch_from_bq(project_id: str, table: str, speech_id: str) -> RelevanceInput:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    sql = f"""
        SELECT id, speech, speaker_position, name_of_house, name_of_meeting, issue,
               meeting_date, municipality_code
        FROM `{table}`
        WHERE id = @speech_id
        LIMIT 1
    """  # noqa: S608
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
        raise ValueError(f"speech_id={speech_id!r} not found")
    row = rows[0]
    meeting_ctx = " ".join(
        filter(None, [row.name_of_house, row.name_of_meeting, row.issue, str(row.meeting_date)])
    )
    return RelevanceInput(
        speech_id=row.id,
        content_text=row.speech or "",
        speaker_position=row.speaker_position,
        meeting_context=meeting_ctx,
        municipality_code=row.municipality_code or "00000",
        user=UserPersona(age_group="25-29"),  # CLI で上書き
    )


def _fetch_batch_from_bq(project_id: str, sql: str) -> list[RelevanceInput]:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    rows = client.query(sql).result()
    inputs: list[RelevanceInput] = []
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
            RelevanceInput(
                speech_id=getattr(row, "id", "(unknown)"),
                content_text=getattr(row, "speech", "") or "",
                speaker_position=getattr(row, "speaker_position", None),
                meeting_context=meeting_ctx,
                municipality_code=getattr(row, "municipality_code", "00000") or "00000",
                user=UserPersona(age_group="25-29"),
            )
        )
    return inputs


def _print_output(speech_id: str, output: object) -> None:
    data = output.model_dump() if hasattr(output, "model_dump") else dict(output)  # type: ignore[attr-defined]
    visible = data["relevance_score"] >= 50
    marker = "★ 表示" if visible else "✗ 非表示 (50 未満)"
    print("─" * 60)
    print(f"speech_id: {speech_id}")
    print(f"score: {data['relevance_score']}/100  [{marker}]")
    print(
        f"  topic={data['score_topic']:2d}  age={data['score_age']:2d}  "
        f"geo={data['score_geographic']:2d}  urgency={data['score_urgency']:2d}"
    )
    matched = data.get("matched_interests") or []
    print(f"matched_interests: {', '.join(matched) if matched else '(なし)'}")
    print(f"reasoning: {data['reasoning']}")
    if data.get("contains_political_judgment"):
        print("⚠️ ethics: contains_political_judgment=True")
    print()
    print(json.dumps(data, ensure_ascii=False))


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    try:
        interests = _parse_interests(args.interests)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    municipalities = [m.strip() for m in args.municipalities.split(",") if m.strip()]
    persona = UserPersona(
        user_id=args.user_id,
        age_group=args.age_group,
        interests=interests,  # type: ignore[arg-type]
        municipality_codes=municipalities,
    )

    agent = RelevanceAgent(project_id=args.project, location=args.location, model=args.model)

    # 入力ソース分岐
    inputs: list[RelevanceInput] = []
    if args.text:
        inputs.append(
            RelevanceInput(
                speech_id="cli-text-input",
                content_text=args.text,
                user=persona,
            )
        )
    elif args.speech_id:
        inp = _fetch_from_bq(args.project, args.bq_table, args.speech_id)
        inp = inp.model_copy(update={"user": persona})
        inputs.append(inp)
    elif args.bq_query:
        inputs.extend(
            inp.model_copy(update={"user": persona})
            for inp in _fetch_batch_from_bq(args.project, args.bq_query)
        )

    if not inputs:
        print("ERROR: no inputs", file=sys.stderr)
        return 2

    for inp in inputs:
        try:
            output = agent.score(inp)
            _print_output(inp.speech_id, output)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR scoring {inp.speech_id}: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
