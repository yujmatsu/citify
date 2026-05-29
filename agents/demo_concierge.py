"""Concierge Agent 3 persona demo (Plan E Phase 5)。

街診断 Migration Concierge を 3 つのペルソナで実行し、各々の応答を表示する
ハッカソン審査員向け demo スクリプト。

Persona ラインナップ:
    1. **無難ベースライン**: 26 歳、リモートワーク、子育て予定
        → デモオープニング用、UX 確認

    2. **痛みのある persona (メイン)**: 介護で実家に戻る 34 歳、東京の家賃が苦しい
        → ハッカソン審査員向けの本命シナリオ、Citify のビジョン
           「自分の街、自分の世代の話」に対する答えを最も雄弁に語る

    3. **具体的課題持ち**: 30 歳ワーママ、待機児童 2 年待ちで詰んだ
        → Concierge の constraint 解釈精度を見せる、E の最強訴求力

Usage:
    # Mock mode (デフォルト、クレデンシャル不要、決定論的)
    python -m agents.demo_concierge

    # Live mode (実 Gemini Flash 呼び出し、GCP credentials 必要)
    python -m agents.demo_concierge --live --project-id citify-dev

    # 1 persona だけ指定
    python -m agents.demo_concierge --persona 2
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from unittest.mock import MagicMock

from agents.concierge.main import ConciergeAgent
from agents.concierge.schema import (
    ConciergeRequest,
    ConciergeResponse,
    MunicipalityCandidate,
    UserPersonaInput,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------
# 3 persona fixtures
# ----------------------------------------------------------------------------


def make_personas() -> list[tuple[str, ConciergeRequest]]:
    """3 つの persona と相談内容。タプル (短い名前, ConciergeRequest)。"""
    return [
        (
            "🟢 無難ベースライン (26 歳 子育て予定)",
            ConciergeRequest(
                message=(
                    "26 歳、リモートワーク、子育て予定です。"
                    "家賃 5,000 万円以下、保育園が充実した街を教えてください。"
                ),
                persona=UserPersonaInput(
                    user_id="demo-25-29",
                    age_group="25-29",
                    interests=["住居", "子育て"],
                    municipality_codes=["13104"],  # 新宿区
                    free_form_context="リモートワーク中心、引っ越し検討中",
                ),
            ),
        ),
        (
            "🔴 痛みのある persona (介護 34 歳、メイン demo)",
            ConciergeRequest(
                message=(
                    "東京の家賃が苦しすぎます。介護のため大分市の実家に戻る予定の 34 歳です。"
                    "実家から通える範囲で、医療機関が多い、転職もできそうな街を教えて。"
                ),
                persona=UserPersonaInput(
                    user_id="demo-30-39",
                    age_group="30-39",
                    interests=["住居", "雇用", "医療"],
                    municipality_codes=["13104", "44201"],  # 新宿区 + 大分市
                    free_form_context="介護で実家近郊への U ターン検討、医療機関の多さ重視",
                ),
            ),
        ),
        (
            "🟡 具体課題持ち (ワーママ 30 歳)",
            ConciergeRequest(
                message=(
                    "30 歳のワーママです。今住んでる街は保育園待機児童が 2 年待ちで詰んでます。"
                    "確実に保育園に入れる、保育施設が多い街を教えて。"
                ),
                persona=UserPersonaInput(
                    user_id="demo-30-39",
                    age_group="30-39",
                    interests=["子育て", "雇用"],
                    municipality_codes=["13104"],
                    free_form_context="保育園待機児童 2 年待ち、保育園定員に確実に空きがある街希望",
                ),
            ),
        ),
    ]


# ----------------------------------------------------------------------------
# Mock runner (LLM 不要、決定論的 fixture 出力)
# ----------------------------------------------------------------------------


def make_mock_runner(persona_idx: int) -> MagicMock:
    """LLM を呼ばない fake Runner。各 persona に固有の応答を返す。"""

    fake_replies = [
        # Persona 1: 無難ベースライン
        (
            "26 歳でリモートワーク、子育て予定でいらっしゃるのですね。\n\n"
            "ご希望の条件 (家賃 5,000 万円以下、保育園充実) で、以下の街がおすすめです:\n\n"
            "### おすすめの街 TOP3\n"
            "- **川崎市 (神奈川県)**: 中古マンション 4,100 万円 / 保育施設 998 件 / 2050 年人口推計 +0.2%\n"
            "- **大阪市 (大阪府)**: 中古マンション 2,600 万円 / 保育施設 2,071 件\n"
            "- **福岡市 (福岡県)**: 中古マンション 2,000 万円 / 保育施設 787 件 / 人口推計 -2.6% (緩やか)"
        ),
        # Persona 2: 痛みのある persona
        (
            "東京での暮らしが苦しい中、ご家族のために大分市の実家近郊での U ターンを検討されているのですね。"
            "介護と仕事の両立、応援したいです。\n\n"
            "**大分市と周辺の状況**\n"
            "- 大分市自体は医療機関 622 件、家賃中央値 1,500 万円。実家からの通勤も無理なくできる規模です。\n"
            "- 中古マンション中央値が東京の 1/3-1/4 と、住居コストが大幅に下がります。\n\n"
            "### 大分市内 / 隣接の候補\n"
            "- **大分市**: 人口 47.5 万人、医療機関 622 件、保育施設 174 件\n"
            "- **別府市**: 観光都市、医療機関充実、家賃低め"
        ),
        # Persona 3: 具体課題持ち
        (
            "保育園待機児童 2 年待ち、本当に大変な状況ですね。\n\n"
            "保育施設が多い街を、人口あたりの保育施設密度で見ると以下が有力です:\n\n"
            "### 保育園充実度が高い街 TOP3\n"
            "- **大阪市 (大阪府)**: 保育施設 2,071 件 / 人口 275 万人 (人口万人あたり 7.5 件)\n"
            "- **川崎市 (神奈川県)**: 保育施設 998 件 / 人口 154 万人 (6.5 件)\n"
            "- **福岡市 (福岡県)**: 保育施設 787 件 / 人口 161 万人 (4.9 件)\n\n"
            "ただし「待機児童 0」かどうかは自治体ホームページの最新発表をご確認ください。"
        ),
    ]

    fake_candidates_per_persona = [
        # Persona 1
        [
            MunicipalityCandidate(
                municipality_code="14130",
                name="川崎市",
                prefecture="神奈川県",
                match_score=90.0,
                population_total=1538262,
                youth_share_pct=16.72,
                used_apartment_median_price_man_yen=4100.0,
                childcare_facility_count=998,
                medical_facility_count=4119,
                population_change_2025_2050_pct=0.16,
                matched_interests=["住居", "子育て"],
                summary_text="人口 1,538,262 人 / 中古マンション 4,100 万円 / 保育施設 998 件",
            ),
            MunicipalityCandidate(
                municipality_code="27100",
                name="大阪市",
                prefecture="大阪府",
                match_score=80.0,
                population_total=2752412,
                used_apartment_median_price_man_yen=2600.0,
                childcare_facility_count=2071,
                medical_facility_count=8341,
                population_change_2025_2050_pct=-14.54,
                matched_interests=["住居", "子育て"],
                summary_text="人口 2,752,412 人 / 保育施設 2,071 件 / 医療機関 8,341 件",
            ),
        ],
        # Persona 2
        [
            MunicipalityCandidate(
                municipality_code="44201",
                name="大分市",
                prefecture="大分県",
                match_score=85.0,
                population_total=475614,
                youth_share_pct=14.5,
                used_apartment_median_price_man_yen=1500.0,
                childcare_facility_count=174,
                medical_facility_count=622,
                population_change_2025_2050_pct=-16.78,
                matched_interests=["住居", "医療"],
                summary_text="人口 475,614 人 / 医療機関 622 件 / 家賃 1,500 万円",
            ),
        ],
        # Persona 3
        [
            MunicipalityCandidate(
                municipality_code="27100",
                name="大阪市",
                prefecture="大阪府",
                match_score=92.0,
                population_total=2752412,
                childcare_facility_count=2071,
                matched_interests=["子育て"],
                summary_text="人口 2,752,412 人 / 保育施設 2,071 件 (万人あたり 7.5 件)",
            ),
            MunicipalityCandidate(
                municipality_code="14130",
                name="川崎市",
                prefecture="神奈川県",
                match_score=85.0,
                population_total=1538262,
                childcare_facility_count=998,
                matched_interests=["子育て"],
                summary_text="人口 1,538,262 人 / 保育施設 998 件 (6.5 件)",
            ),
        ],
    ]

    idx = max(0, min(persona_idx, 2))
    mock_response: dict = {
        "reply": fake_replies[idx],
        "tool_calls": [
            {
                "name": "search_municipalities",
                "args": {
                    "age_group": ["25-29", "30-39", "30-39"][idx],
                    "interests": [
                        ["住居", "子育て"],
                        ["住居", "雇用", "医療"],
                        ["子育て", "雇用"],
                    ][idx],
                    "constraints": [
                        {"max_avg_rent_man": 5000},
                        {"min_medical_count": 100},
                        {"min_childcare_count": 300},
                    ][idx],
                },
                "output": fake_candidates_per_persona[idx],
                "duration_ms": [2514, 3018, 2745][idx],
            }
        ],
        "candidates": fake_candidates_per_persona[idx],
    }

    runner = MagicMock()
    runner.run.return_value = mock_response
    return runner


# ----------------------------------------------------------------------------
# Live runner (real google.genai 経由)
# ----------------------------------------------------------------------------


def make_live_concierge(project_id: str) -> ConciergeAgent:
    """本物の GenaiConciergeRunner を持つ ConciergeAgent を構築。"""
    from agents.concierge.runner import GenaiConciergeRunner

    runner = GenaiConciergeRunner(project_id=project_id)
    return ConciergeAgent(project_id=project_id, runner=runner)


# ----------------------------------------------------------------------------
# Display: ConciergeResponse を CLI に整形
# ----------------------------------------------------------------------------


def display_response(name: str, request: ConciergeRequest, response: ConciergeResponse) -> None:
    """1 persona の応答を CLI に整形表示。"""
    print()
    print("=" * 70)
    print(f"  {name}")
    print("=" * 70)
    print(f"📝 相談内容: {request.message}")
    print(
        f"👤 ペルソナ: age={request.persona.age_group} "
        f"interests={request.persona.interests} "
        f"context={request.persona.free_form_context!r}"
    )
    print()
    print("🤖 Concierge 応答:")
    for line in response.reply.split("\n"):
        print(f"   {line}")
    print()

    if response.candidates:
        print(f"🏘️  自治体候補 ({len(response.candidates)} 件):")
        for c in response.candidates:
            tags = ",".join(c.matched_interests) if c.matched_interests else "-"
            print(f"   - {c.name} ({c.prefecture}): match={c.match_score:.0f}/100 [{tags}]")
            print(f"       {c.summary_text}")
        print()

    if response.tool_calls:
        print(f"🔧 Tool 呼び出し ({len(response.tool_calls)} 回):")
        for tc in response.tool_calls:
            duration_s = tc.duration_ms / 1000.0
            args_brief = json.dumps(tc.args, ensure_ascii=False)[:100]
            print(f"   - {tc.name}() {duration_s:.2f}s args={args_brief}")
        print()

    if response.ethical_violations:
        print(f"⚠️  倫理 violation: {response.ethical_violations}")


# ----------------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agents.demo_concierge",
        description=(
            "Migration Concierge Agent 3 persona demo (Plan E Phase 5)。"
            "ハッカソン審査員向けの 3 シナリオ実演。"
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="実 Gemini を呼ぶ (GCP credentials 必要、各 persona ~$0.005)",
    )
    parser.add_argument(
        "--project-id",
        default="citify-dev",
        help="GCP project ID (--live 時のみ使用)",
    )
    parser.add_argument(
        "--persona",
        type=int,
        default=None,
        choices=[1, 2, 3],
        help="特定 persona だけ実行 (1=ベース / 2=痛みあり / 3=ワーママ)。未指定なら 3 つ実行",
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

    mode = "LIVE (real Gemini)" if args.live else "MOCK (deterministic)"
    print("=" * 70)
    print(f"  Concierge 3 Persona Demo — mode={mode}")
    print("=" * 70)

    personas = make_personas()
    if args.persona is not None:
        personas = [personas[args.persona - 1]]

    for i, (name, request) in enumerate(personas):
        # persona index (0-2) を計算 (--persona 指定時は元 index を保持)
        original_idx = personas.index((name, request)) if args.persona is None else args.persona - 1

        if args.live:
            agent = make_live_concierge(project_id=args.project_id)
        else:
            runner = make_mock_runner(persona_idx=original_idx)
            agent = ConciergeAgent(runner=runner)

        try:
            response = agent.respond(request)
        except Exception as exc:  # noqa: BLE001
            logger.exception("demo_concierge failed for persona %d: %s", i + 1, exc)
            print(f"❌ persona {i + 1} で失敗: {exc}")
            continue

        display_response(name, request, response)

    print()
    print("=" * 70)
    print("  ✅ Demo complete")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
