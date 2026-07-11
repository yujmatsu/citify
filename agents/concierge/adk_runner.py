"""AdkConciergeRunner: 本物の ADK 親子 (translator/relevance sub_agents) 実行体。

`ConciergeAgent.arespond()` から使われる非同期 Runner。`GenaiConciergeRunner` と
**同じ戻り契約** `{"reply", "tool_calls", "candidates"}` を返すので、ConciergeAgent の
正規化・倫理ゲート (`_finalize`) をそのまま共有できる。

設計 (agents/watcher/main.py の specialist 実行と同型):
    ADKConciergeAgent.as_agent() で親→sub_agents 階層を組み → google.adk.Runner +
    InMemorySessionService で run_async → function_call を tool_calls に、
    search_municipalities の function_response を candidates に、最終テキストを reply に。

注意:
    - google.adk / google.genai は **遅延 import** (dev サンドボックスでは実 SDK が
      import 不可のため、モジュール読み込み時に import しない)。
    - この経路は CITIFY_CONCIERGE_ADK=1 のときのみ使用。実行時例外は API 層が
      sync GenaiConciergeRunner 経路に fallback する (現行デモを壊さない)。
    - 実 ADK Runner の I/O は本番 smoke で検証 (watcher と同じ規約)。unit test は
      google.adk を fake して event ストリームを差し込む。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .schema import ConciergeRequest

logger = logging.getLogger(__name__)

DEFAULT_LOCATION = "us-central1"
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TOOL_CALLS = 8  # 暴走防止 (concierge は 4 tool × 数反復想定)


def _ensure_vertex_env(project_id: str | None, location: str) -> None:
    """ADK の google_llm backend を Vertex/ADC 経由にする env を設定 (watcher と同型)。"""
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
    if project_id:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project_id)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", location)


class AdkConciergeRunner:
    """ADK 親子階層を実行する非同期 Runner (GenaiConciergeRunner と互換の dict を返す)。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        adk_concierge: Any | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.model = model
        self._adk_concierge = adk_concierge

    def _concierge(self) -> Any:
        if self._adk_concierge is None:
            from agents.concierge.adk_agent import ADKConciergeAgent

            self._adk_concierge = ADKConciergeAgent(project_id=self.project_id, model=self.model)
        return self._adk_concierge

    async def run(self, request: ConciergeRequest, persona_desc: str) -> dict[str, Any]:
        """ADK 親子で 1 ターン実行し {"reply","tool_calls","candidates"} を返す。"""
        import google.genai.types as gat
        from google.adk import Runner
        from google.adk.sessions import InMemorySessionService

        from .prompts.system import build_user_prompt

        _ensure_vertex_env(self.project_id, self.location)
        agent = self._concierge().as_agent()
        app = "concierge"
        uid = request.persona.user_id
        ss = InMemorySessionService()
        await ss.create_session(app_name=app, user_id=uid, session_id=uid)
        runner = Runner(agent=agent, app_name=app, session_service=ss)

        prompt = build_user_prompt(request.message, persona_desc)
        msg = gat.Content(role="user", parts=[gat.Part(text=prompt)])

        reply = ""
        tool_calls: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        capped = False
        async for event in runner.run_async(user_id=uid, session_id=uid, new_message=msg):
            for part in getattr(getattr(event, "content", None), "parts", []) or []:
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    tool_calls.append({"name": fc.name, "args": dict(fc.args or {})})
                    if len(tool_calls) > MAX_TOOL_CALLS:
                        logger.warning("adk_concierge.max_tool_calls uid=%s", uid)
                        capped = True
                        break
                candidates.extend(_extract_candidates(part))
            is_final = getattr(event, "is_final_response", lambda: False)()
            if is_final and getattr(event, "content", None) and event.content.parts:
                reply = getattr(event.content.parts[0], "text", "") or reply
            if capped:
                break

        return {"reply": reply, "tool_calls": tool_calls, "candidates": candidates}


def _extract_candidates(part: Any) -> list[dict[str, Any]]:
    """search_municipalities の function_response から候補 dict を best-effort 抽出 (完全 guard)。

    GenaiConciergeRunner と同じく search_municipalities のみを候補源にする。ADK の
    function_response.response の包み方はバージョン差がある (`{"result": [...]}` /
    `{"candidates": [...]}` / 生 list など) ため、**`municipality_code` を持つ dict を
    再帰的に拾う**堅牢な抽出にする (どの形状でも取れ、取れなくても空 list=非後退)。
    """
    try:
        fr = getattr(part, "function_response", None)
        if fr is None or getattr(fr, "name", None) != "search_municipalities":
            return []
        found: list[dict[str, Any]] = []

        def _walk(obj: Any) -> None:
            if isinstance(obj, dict):
                if "municipality_code" in obj:
                    found.append(obj)
                else:
                    for v in obj.values():
                        _walk(v)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    _walk(v)

        _walk(getattr(fr, "response", None))
        return found
    except Exception:  # noqa: BLE001
        return []
