"""自由記述から移住の前提 (関心軸/優先順位/家族構成/予算/背景) を抽出 (TASK-ONBOARDING / F)。

設計: docs/plans/2026-06-08-onboarding-priorities-design.md

- 軽量 single-agent (JSONモード) で構造化抽出。フォームを自動プリフィルし、ユーザーが必ず確認・編集
  (AIが決めない、human-in-the-loop)。
- 純関数 `_parse_extracted` (JSON parse + サニタイズ) はテスト対象。ADK 呼び出しはモック。
- 倫理: background_summary を find_forbidden_matches で検査し、違反時は空に。
"""

from __future__ import annotations

import json
import logging
import re

from agents._shared.forbidden import find_forbidden_matches
from agents.relevance.schema import ALL_INTERESTS

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
_HOUSEHOLDS = ("single", "couple", "family_kids", "other")
_INTEREST_SET = set(ALL_INTERESTS)


def _build_prompt(text: str) -> str:
    interests = "/".join(ALL_INTERESTS)
    return (
        "あなたは移住相談の聞き取り担当です。ユーザーの自由記述から、移住の前提を抽出し"
        "**JSON のみ**で返してください(説明文・コードフェンス禁止):\n"
        '{"interests":["関心軸"],"priorities":["特に重視する上位3(順位順)"],'
        '"household":"single|couple|family_kids|other|","budget_man":数値 or null,'
        '"background_summary":"背景を1文で(中立に)"}\n'
        f"interests/priorities は必ず次から選ぶ: {interests}。\n"
        "household は単身=single/夫婦=couple/子どもあり=family_kids/その他=other、不明は空。\n"
        "budget_man は住まいの予算上限(万円)の数値、言及なければ null。\n"
        "特定政党・候補者・政治的賛否・処方・投票推奨は一切含めない。\n\n"
        f"# ユーザーの記述\n{text}"
    )


def _parse_extracted(final_text: str) -> dict:
    """LLM 応答(JSON)を安全な構造に。未知の関心軸/家族構成はサニタイズ (純関数)。"""
    empty = {
        "interests": [],
        "priorities": [],
        "household": "",
        "budget_man": None,
        "background_summary": "",
    }
    if not final_text:
        return empty
    m = re.search(r"\{.*\}", final_text, re.DOTALL)
    if not m:
        return empty
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty

    def _clean_interests(raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for x in raw:
            s = str(x).strip()
            if s in _INTEREST_SET and s not in out:
                out.append(s)
        return out

    interests = _clean_interests(data.get("interests"))
    # priorities は interests の部分集合・最大3
    priorities = [p for p in _clean_interests(data.get("priorities")) if p in interests][:3]

    household = str(data.get("household") or "").strip()
    if household not in _HOUSEHOLDS:
        household = ""

    budget_raw = data.get("budget_man")
    budget_man: int | None = None
    if isinstance(budget_raw, int | float):
        budget_man = int(budget_raw) if budget_raw > 0 else None

    summary = str(data.get("background_summary") or "").strip()[:200]
    if summary and find_forbidden_matches(summary):
        summary = ""  # 倫理スキャン: 違反は破棄

    return {
        "interests": interests,
        "priorities": priorities,
        "household": household,
        "budget_man": budget_man,
        "background_summary": summary,
    }


async def extract_preferences(text: str, model: str = DEFAULT_MODEL) -> dict:
    """自由記述から前提を抽出。失敗時は空(フォーム手入力にフォールバック)。"""
    if not text or not text.strip():
        return _parse_extracted("")

    import uuid

    import google.genai.types as gat
    from google.adk import Agent, Runner
    from google.adk.sessions import InMemorySessionService

    try:
        agent = Agent(
            name="preference_extractor",
            model=model,
            instruction="移住の前提を JSON のみで抽出するアシスタント。",
            tools=[],
            generate_content_config=gat.GenerateContentConfig(
                response_mime_type="application/json"
            ),
        )
        runner = Runner(
            agent=agent, app_name="preferences", session_service=InMemorySessionService()
        )
        sid = uuid.uuid4().hex[:8]
        await runner.session_service.create_session(
            app_name="preferences", user_id="aux", session_id=sid
        )
        msg = gat.Content(role="user", parts=[gat.Part(text=_build_prompt(text))])
        final_text = ""
        async for event in runner.run_async(user_id="aux", session_id=sid, new_message=msg):
            if getattr(event, "is_final_response", lambda: False)() and event.content:
                final_text = event.content.parts[0].text or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("extract_preferences failed: %s", exc)
        return _parse_extracted("")

    return _parse_extracted(final_text)
