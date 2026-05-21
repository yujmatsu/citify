"""DistributorAgent CLI: BQ から N 件取得 → A-6 スコアリング → A-7 ランキング → For You フィード生成。

使用例:
    # 直近 30 日の speech 10 件から子育て関心ユーザー向け feed top-5 生成
    python -m agents.distributor \\
        --project citify-dev --location asia-northeast1 \\
        --age-group 25-29 \\
        --interests 子育て,住居,教育 \\
        --municipalities 13104,00000 \\
        --limit 10 --feed-size 5

    # 任意 SQL でカスタム候補プール
    python -m agents.distributor \\
        --project citify-dev --location asia-northeast1 \\
        --bq-query "SELECT * FROM \\`citify-dev.citify_raw.kokkai_speeches\\` WHERE meeting_date >= '2026-04-01'" \\
        --age-group 30-34 --interests 教育,子育て --municipalities 00000 \\
        --feed-size 10
"""

from __future__ import annotations

import argparse
import logging
import sys

from agents.relevance import RelevanceAgent, RelevanceInput, UserPersona
from agents.relevance.schema import ALL_INTERESTS

from .main import (
    DEFAULT_DIVERSITY_WEIGHT,
    DEFAULT_FEED_SIZE,
    DEFAULT_MIN_RELEVANCE,
    DistributorAgent,
)
from .schema import FeedCandidate

DEFAULT_BQ_TABLE = "citify-dev.citify_raw.kokkai_speeches"
DEFAULT_LOCATION = "asia-northeast1"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agents.distributor",
        description="Citify 配信 Agent (A-7): BQ → A-6 score → A-7 ranking で feed 生成",
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--location", default=DEFAULT_LOCATION)

    # 候補ソース
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--bq-query", type=str, help="任意 SQL で候補取得")
    src.add_argument(
        "--limit",
        type=int,
        default=10,
        help="default: 直近 90 日から N 件取得 (--bq-query 未指定時)",
    )

    # ペルソナ
    parser.add_argument("--age-group", choices=["18-24", "25-29", "30-34", "35+"], default="25-29")
    parser.add_argument(
        "--interests",
        type=str,
        default="子育て,住居",
        help=f"カンマ区切り ({','.join(ALL_INTERESTS)})",
    )
    parser.add_argument(
        "--municipalities", type=str, default="00000", help="カンマ区切り自治体コード"
    )
    parser.add_argument("--user-id", default="cli-anonymous")

    # ランキングパラメタ
    parser.add_argument("--feed-size", type=int, default=DEFAULT_FEED_SIZE)
    parser.add_argument("--min-relevance", type=int, default=DEFAULT_MIN_RELEVANCE)
    parser.add_argument("--diversity-weight", type=float, default=DEFAULT_DIVERSITY_WEIGHT)

    parser.add_argument("--bq-table", default=DEFAULT_BQ_TABLE)
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _fetch_candidates_meta(project_id: str, sql: str) -> list[dict]:
    from google.cloud import bigquery

    client = bigquery.Client(project=project_id)
    rows = client.query(sql).result()
    out = []
    for row in rows:
        out.append(
            {
                "id": row.id,
                "speech": row.speech or "",
                "speaker_position": getattr(row, "speaker_position", None),
                "name_of_house": getattr(row, "name_of_house", None),
                "name_of_meeting": getattr(row, "name_of_meeting", None),
                "issue": getattr(row, "issue", None),
                "meeting_date": getattr(row, "meeting_date", None),
                "meeting_url": getattr(row, "meeting_url", None),
                "municipality_code": getattr(row, "municipality_code", "00000") or "00000",
            }
        )
    return out


def _print_feed(items: list, user: UserPersona) -> None:
    print("\n" + "=" * 70)
    print(f"For You feed ({user.user_id}, {user.age_group}, 関心軸: {','.join(user.interests)})")
    print("=" * 70)
    if not items:
        print("(該当する記事がありません)")
        return
    for item in items:
        print(f"\n#{item.final_rank}  score={item.relevance_score}  adj={item.adjusted_score:.1f}")
        print(f"   {item.display_reason}")
        if item.title:
            print(f"   📰 {item.title}")
        if item.summary:
            for line in item.summary:
                print(f"      {line}")
        meta_bits = []
        if item.speaker_position:
            meta_bits.append(item.speaker_position)
        if item.name_of_meeting:
            meta_bits.append(item.name_of_meeting)
        if item.meeting_date:
            meta_bits.append(item.meeting_date.isoformat())
        if meta_bits:
            print(f"   ({' | '.join(meta_bits)})")
        if item.freshness_boost != 0 or item.diversity_penalty > 0:
            print(
                f"   [debug] freshness={item.freshness_boost:+d} "
                f"diversity_penalty={item.diversity_penalty:.1f}"
            )


def main() -> int:
    args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )

    # ペルソナ構築
    interests = [s.strip() for s in args.interests.split(",") if s.strip()]
    invalid = [i for i in interests if i not in ALL_INTERESTS]
    if invalid:
        print(f"ERROR: 無効な関心軸: {invalid}", file=sys.stderr)
        return 2
    municipalities = [m.strip() for m in args.municipalities.split(",") if m.strip()]
    user = UserPersona(
        user_id=args.user_id,
        age_group=args.age_group,
        interests=interests,  # type: ignore[arg-type]
        municipality_codes=municipalities,
    )

    # 1. 候補 speech を BQ から取得
    if args.bq_query:
        sql = args.bq_query
    else:
        sql = f"""
            SELECT id, speech, speaker_position, name_of_house, name_of_meeting,
                   issue, meeting_date, meeting_url, municipality_code
            FROM `{args.bq_table}`
            WHERE speech IS NOT NULL
            ORDER BY meeting_date DESC
            LIMIT {args.limit}
        """  # noqa: S608
    print("# Fetching candidates from BQ...", file=sys.stderr)
    meta_rows = _fetch_candidates_meta(args.project, sql)
    print(f"# Got {len(meta_rows)} candidates", file=sys.stderr)

    # 2. 各候補に A-6 スコアリング (これが一番重い、N 個 LLM 呼び出し)
    relevance_agent = RelevanceAgent(project_id=args.project, location=args.location)
    candidates: list[FeedCandidate] = []
    for i, row in enumerate(meta_rows, 1):
        if i % 5 == 1:
            print(f"# Scoring {i}/{len(meta_rows)}...", file=sys.stderr)
        meeting_ctx = " ".join(
            filter(None, [row["name_of_house"], row["name_of_meeting"], row["issue"]])
        )
        inp = RelevanceInput(
            speech_id=row["id"],
            content_text=row["speech"],
            speaker_position=row["speaker_position"],
            meeting_context=meeting_ctx,
            municipality_code=row["municipality_code"],
            user=user,
        )
        try:
            score = relevance_agent.score(inp)
        except Exception as exc:  # noqa: BLE001
            print(f"# WARN: scoring failed for {row['id']}: {exc}", file=sys.stderr)
            continue
        candidates.append(
            FeedCandidate(
                speech_id=row["id"],
                relevance_score=score.relevance_score,
                score_topic=score.score_topic,
                score_age=score.score_age,
                score_geographic=score.score_geographic,
                score_urgency=score.score_urgency,
                matched_interests=list(score.matched_interests),
                reasoning=score.reasoning,
                speaker_position=row["speaker_position"],
                municipality_code=row["municipality_code"],
                meeting_date=row["meeting_date"],
                meeting_url=row["meeting_url"],
                name_of_meeting=row["name_of_meeting"],
            )
        )

    # 3. A-7 ランキング
    distributor = DistributorAgent(
        min_relevance=args.min_relevance,
        feed_size=args.feed_size,
        diversity_weight=args.diversity_weight,
    )
    feed = distributor.generate_feed(candidates)
    print(
        f"# Ranked: {len(candidates)} candidates → {len(feed)} feed items",
        file=sys.stderr,
    )

    _print_feed(feed, user)
    return 0


if __name__ == "__main__":
    sys.exit(main())
