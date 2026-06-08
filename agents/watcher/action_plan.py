"""移住アクションプラン生成 (TASK-ACTIONPLAN)。

設計: docs/plans/2026-06-08-relocation-action-plan-design.md

原則:
    - 結論は生成しない。Watcher の TownAnalysis を再利用 (4つ目の結論を作らない)。
    - 唯一の新規生成は visit_checklist (街固有の現地確認項目)。
    - mode=stay (推し街=home) は据え置きモード (窓口非表示・訪問→自街再点検)。

純関数 (select_recommended / build_reasons / construct_official_links / assemble_action_plan)
はテスト対象。generate_visit_checklist は ADK 呼び出しでモック。

TownAnalysis フィールド対応 (再利用、レビュー#1):
    decision_summary  ← verdict.headline
    reasons           ← 推し街 assessment.strengths ＋ verdict.reasoning
    open_questions    ← analysis.open_questions
    mode              ← 推し街 assessment.role == "home" → "stay"
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from agents._shared.forbidden import find_forbidden_matches
from agents.watcher.schema import ActionPlan, OfficialLink, TownAnalysis, TownAssessment

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"

# 公式リンクが seed に無い時のフォールバック (信頼ポータル)。
# レビュー#2/N1: ディープリンクは前提にせず portal top ＋市名ラベルで安全に誘導。
PORTAL_NAME = "全国移住ナビ（ニッポン移住・交流ナビ）"
PORTAL_URL = "https://www.iju-join.jp/"

_SEED_PATH = Path(__file__).resolve().parents[2] / "infra" / "seed" / "relocation_links.csv"
_LINKS_CACHE: dict[str, tuple[str, str]] | None = None
MAX_REASONS = 6


def load_relocation_links(path: Path | None = None) -> dict[str, tuple[str, str]]:
    """infra/seed/relocation_links.csv を読み {code: (url, label)} を返す (キャッシュ・graceful)。"""
    global _LINKS_CACHE
    if path is None and _LINKS_CACHE is not None:
        return _LINKS_CACHE
    target = path or _SEED_PATH
    out: dict[str, tuple[str, str]] = {}
    try:
        with target.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                code = (row.get("municipality_code") or "").strip().zfill(5)
                url = (row.get("official_url") or "").strip()
                if code and url:
                    out[code] = (url, (row.get("label") or "").strip() or f"{code} 公式サイト")
    except FileNotFoundError:
        logger.warning("relocation_links seed not found: %s", target)
    except Exception as exc:  # noqa: BLE001
        logger.warning("relocation_links load failed: %s", exc)
    if path is None:
        _LINKS_CACHE = out
    return out


def select_recommended(analysis: TownAnalysis) -> tuple[TownAssessment, str] | None:
    """推し街 assessment と mode を決める。verdict.recommended_code 優先、無ければ最高 fit_score。

    Returns: (assessment, mode["relocate"|"stay"]) or None (評価が皆無)。
    """
    assessments = analysis.town_assessments
    if not assessments:
        return None
    rec: TownAssessment | None = None
    code = analysis.verdict.recommended_code
    if code:
        rec = next((a for a in assessments if a.municipality_code == code), None)
    if rec is None:
        rec = max(assessments, key=lambda a: a.fit_score)
    mode = "stay" if rec.role == "home" else "relocate"
    return rec, mode


def build_reasons(analysis: TownAnalysis, rec: TownAssessment) -> list[str]:
    """なぜこの街か (再利用)。verdict.reasoning を先頭に、推し街の強みを続ける。"""
    reasons: list[str] = []
    reasoning = (analysis.verdict.reasoning or "").strip()
    if reasoning:
        reasons.append(reasoning)
    reasons.extend(s for s in rec.strengths if s)
    return reasons[:MAX_REASONS]


def construct_official_links(
    code: str,
    name: str,
    mode: str,
    links_lookup: dict[str, tuple[str, str]] | None = None,
) -> list[OfficialLink]:
    """公式リンク。stay は空。seed があれば公式URL、無ければ信頼ポータルへフォールバック。"""
    if mode == "stay":
        return []
    lookup = links_lookup if links_lookup is not None else load_relocation_links()
    if code in lookup:
        url, label = lookup[code]
        return [OfficialLink(label=label, url=url)]
    return [OfficialLink(label=f"{PORTAL_NAME}で{name}を探す", url=PORTAL_URL)]


def assemble_action_plan(
    analysis: TownAnalysis,
    town_names: dict[str, str] | None,
    visit_checklist: list[str],
    run_id: str,
    generated_at: str,
    links_lookup: dict[str, tuple[str, str]] | None = None,
) -> ActionPlan | None:
    """TownAnalysis ＋ 生成済 visit_checklist から ActionPlan を組み立てる (純関数)。"""
    sel = select_recommended(analysis)
    if sel is None:
        return None
    rec, mode = sel
    name = (town_names or {}).get(rec.municipality_code) or rec.municipality_code
    summary = analysis.verdict.headline or rec.headline
    return ActionPlan(
        mode=mode,  # type: ignore[arg-type]
        recommended_code=rec.municipality_code,
        recommended_name=name,
        role=rec.role,
        decision_summary=summary,
        reasons=build_reasons(analysis, rec),
        open_questions=list(analysis.open_questions),
        visit_checklist=visit_checklist,
        official_links=construct_official_links(rec.municipality_code, name, mode, links_lookup),
        run_id=run_id,
        generated_at=generated_at,
    )


class _VisitChecklist(BaseModel):
    """generate_visit_checklist の response_schema (JSON モード強制用)。"""

    items: list[str] = Field(default_factory=list)


def _build_checklist_prompt(rec: TownAssessment, name: str, mode: str) -> str:
    ctx = (
        f"街: {name}\n"
        f"強み: {', '.join(rec.strengths) or 'なし'}\n"
        f"懸念: {', '.join(rec.concerns) or 'なし'}\n"
        f"人口見通し: {rec.population_outlook or '不明'}"
    )
    if mode == "stay":
        task = f"{name}に住み続ける前提で、移住者目線で『自分の街を再点検する項目』を4〜6個。"
    else:
        task = f"{name}に移住する前に『現地で自分の目で確かめるべき項目』を4〜6個。"
    return (
        "あなたは移住検討者に寄り添う相談員です。下記の街の特性に基づき、"
        f"{task} 各項目は**この街固有の特性に紐づく具体的な確認行動**にすること"
        "（『家賃を確認』のような汎用項目は禁止。例: 昼夜間人口比が低い→朝の通勤時間帯の駅の混雑を見る）。"
        "特定政党・候補者・政治的賛否・処方/投票推奨は含めない。"
        f'JSON のみで返す: {{"items": ["...", "..."]}}\n\n# 街の情報\n{ctx}'
    )


async def generate_visit_checklist(
    rec: TownAssessment,
    name: str,
    mode: str,
    model: str = DEFAULT_MODEL,
) -> list[str]:
    """現地訪問チェックリストを軽量 single-agent (JSONモード) で生成。失敗時は [] (graceful)。

    倫理: 生成項目を find_forbidden_matches で除去 (処方/投票推奨/政治主体)。
    """
    import uuid

    import google.genai.types as gat
    from google.adk import Agent, Runner
    from google.adk.sessions import InMemorySessionService

    try:
        agent = Agent(
            name="action_plan_checklist",
            model=model,
            instruction="現地確認チェックリストを JSON で返すアシスタント。",
            tools=[],
            generate_content_config=gat.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_VisitChecklist,
            ),
        )
        ss = InMemorySessionService()
        sid = uuid.uuid4().hex[:8]
        await ss.create_session(app_name="action_plan", user_id="aux", session_id=sid)
        runner = Runner(agent=agent, app_name="action_plan", session_service=ss)
        msg = gat.Content(
            role="user", parts=[gat.Part(text=_build_checklist_prompt(rec, name, mode))]
        )
        final_text = ""
        async for event in runner.run_async(user_id="aux", session_id=sid, new_message=msg):
            if getattr(event, "is_final_response", lambda: False)() and event.content:
                final_text = event.content.parts[0].text or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("generate_visit_checklist failed: %s", exc)
        return []

    return _filter_forbidden(_parse_checklist(final_text))


def _filter_forbidden(items: list[str]) -> list[str]:
    """倫理スキャン: 禁止語(処方/投票推奨/政治主体)を含む項目を除去 (純関数、テスト対象)。"""
    return [it for it in items if it and not find_forbidden_matches(it)]


def _parse_checklist(final_text: str) -> list[str]:
    """LLM 応答 (JSON) から items を抽出 (graceful)。"""
    import json
    import re

    if not final_text:
        return []
    m = re.search(r"\{.*\}", final_text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [str(x).strip() for x in items if str(x).strip()]
