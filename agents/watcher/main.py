"""WatcherAgent: ADK Runner ベースの自律型マイ街エージェント (TASK-WATCHER Slice 1)。

設計:
    - google.adk.Runner で「LLM が自分でツールを選ぶ」自律ループを回す (スパイク OK 済)
    - google.adk は lazy import (開発環境では import 不可のため)。run() 内で import
    - 純粋ロジック (JSON パース / 倫理検証 / run-log 構築) は ADK I/O から分離し unit test 可能に
    - 自律性そのものの検証は実環境 smoke (run_smoke) が担う

責務分離:
    - parse_analysis / apply_ethics / _build_run_log : 純粋関数 (テスト対象)
    - WatcherAgent.run : ADK Runner I/O (実環境 smoke で検証)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agents._shared.forbidden import find_forbidden_matches

from .prompts.system import WATCHER_SYSTEM_PROMPT, build_watch_user_prompt
from .schema import (
    AgentRunLog,
    ToolCall,
    TownAnalysis,
    WatcherResult,
    WatchInput,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
MAX_TOOL_CALLS = 12  # 暴走/コスト防止の上限 (watch街5 × 2-3ツール想定)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


# ============================================================================
# 純粋ロジック (ADK 非依存・テスト対象)
# ============================================================================


def parse_analysis(final_text: str) -> TownAnalysis | None:
    """エージェント最終応答 (JSON) を TownAnalysis にパース。

    前後に説明文が混じっても最外 JSON ブロックを抽出。パース失敗・空内容は None (graceful)。
    """
    if not final_text:
        return None
    m = _JSON_BLOCK.search(final_text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("watcher.parse_failed err=%s", exc)
        return None
    if not isinstance(data, dict) or "verdict" not in data:
        return None
    try:
        analysis = TownAnalysis.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.analysis_invalid err=%s", exc)
        return None
    # verdict が空 (比較材料なし) なら None 扱い
    if not analysis.verdict.headline and not analysis.town_assessments:
        return None
    return analysis


def apply_ethics(analysis: TownAnalysis | None) -> TownAnalysis | None:
    """倫理ゲート: 政党/政治家/賛否を含む内容は出さない (PROJECT.md §5)。

    verdict 本文 or いずれかの街評価が forbidden に当たる、もしくは LLM が
    contains_political_judgment=True と自己申告した場合は analysis 全体を None に倒す
    (一部だけ消すと比較が壊れるため、安全側に倒す)。
    """
    if analysis is None:
        return None
    verdict_text = f"{analysis.verdict.headline} {analysis.verdict.reasoning}"
    texts = [verdict_text] + [
        f"{a.headline} {' '.join(a.strengths)} {' '.join(a.concerns)} "
        f"{a.population_outlook} {a.recent_signal}"
        for a in analysis.town_assessments
    ]
    matches = find_forbidden_matches(" ".join(texts))
    if matches or analysis.verdict.contains_political_judgment:
        logger.info("watcher.ethics_dropped matches=%s", matches)
        return None
    return analysis


def _build_run_log(
    run_id: str,
    user_id: str,
    towns: list[str],
    tool_calls: list[ToolCall],
    n_discoveries: int,
    status: str = "ok",
    note: str = "",
    token_cost: int | None = None,
) -> AgentRunLog:
    return AgentRunLog(
        run_id=run_id,
        user_id=user_id,
        towns_checked=towns,
        tool_calls=tool_calls,
        n_discoveries=n_discoveries,
        token_cost=token_cost,
        status=status,  # type: ignore[arg-type]
        note=note,
    )


# ============================================================================
# WatcherAgent (ADK Runner I/O)
# ============================================================================


class WatcherAgent:
    """ADK Runner で自律ループを回すマイ街エージェント。

    Args:
        project_id: GCP project (Vertex)
        model: Gemini モデル
        location: Vertex location
    """

    def __init__(
        self,
        project_id: str | None = None,
        model: str = DEFAULT_MODEL,
        location: str = DEFAULT_LOCATION,
        repo: Any | None = None,
    ) -> None:
        self.project_id = project_id
        self.model = model
        self.location = location
        self.repo = repo  # WatcherRepository | None。None なら永続化 skip (Slice1 互換)

    def _build_agent(self) -> Any:
        """ADK Agent を構築 (tools=[search_speeches, fetch_population_trend])。lazy import。"""
        from google.adk import Agent
        from google.adk.tools import FunctionTool

        from . import tools as watcher_tools

        return Agent(
            name="machi_watcher",
            description="ユーザー専属の自律型マイ街エージェント。watch街の議題から本人に意味ある発見を見つける。",
            model=self.model,
            instruction=WATCHER_SYSTEM_PROMPT,
            tools=[
                FunctionTool(func=watcher_tools.search_speeches),
                FunctionTool(func=watcher_tools.fetch_population_trend),
                FunctionTool(func=watcher_tools.compare_towns),
            ],
        )

    def _ensure_vertex_env(self) -> None:
        """ADK google_llm が Vertex AI(ADC 認証)を使うよう env を設定。

        未設定だと ADK は Gemini API バックエンドを選び API キーを要求して失敗する。
        Citify は Vertex AI を使うため明示する(既存 genai エージェントと同方針)。
        """
        import os

        os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", self.location)
        if self.project_id:
            os.environ.setdefault("GOOGLE_CLOUD_PROJECT", self.project_id)

    async def run(self, watch: WatchInput) -> WatcherResult:
        """1 ユーザー分の自律実行 → WatcherResult (repo があれば Firestore 永続化)。"""
        import uuid

        self._ensure_vertex_env()

        import google.genai.types as gat
        from google.adk import Runner
        from google.adk.sessions import InMemorySessionService

        run_id = uuid.uuid4().hex
        agent = self._build_agent()
        session_service = InMemorySessionService()
        app, uid, sid = "watcher", watch.user_id, f"{watch.user_id}-{run_id[:8]}"
        await session_service.create_session(app_name=app, user_id=uid, session_id=sid)
        runner = Runner(agent=agent, app_name=app, session_service=session_service)

        prompt = build_watch_user_prompt(
            watch.user_id,
            watch.age_group,
            list(watch.interests),
            watch.home_municipality_code,
            list(watch.watched_codes),
        )
        msg = gat.Content(role="user", parts=[gat.Part(text=prompt)])

        tool_calls: list[ToolCall] = []
        final_text = ""
        token_cost: int | None = None
        status = "ok"
        try:
            async for event in runner.run_async(user_id=uid, session_id=sid, new_message=msg):
                for part in getattr(getattr(event, "content", None), "parts", []) or []:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        tool_calls.append(ToolCall(tool=fc.name, args=dict(fc.args or {})))
                        if len(tool_calls) > MAX_TOOL_CALLS:
                            status = "max_iterations"
                            logger.warning("watcher.max_tool_calls user=%s", watch.user_id)
                            break
                # token_cost は最終 event の usage を採用 (加算は二重計上の恐れ)
                usage = getattr(event, "usage_metadata", None)
                total = getattr(usage, "total_token_count", None) if usage else None
                if total is not None:
                    token_cost = total
                is_final = getattr(event, "is_final_response", lambda: False)()
                if is_final and event.content and event.content.parts:
                    final_text = event.content.parts[0].text or ""
        except Exception as exc:  # noqa: BLE001
            logger.exception("watcher.run_failed user=%s err=%s", watch.user_id, exc)
            return WatcherResult(
                analysis=None,
                run_log=_build_run_log(
                    run_id,
                    watch.user_id,
                    watch.all_codes(),
                    tool_calls,
                    0,
                    "error",
                    str(exc)[:200],
                    token_cost,
                ),
            )

        parsed = parse_analysis(final_text)
        analysis = apply_ethics(parsed)
        n_assessed = len(analysis.town_assessments) if analysis else 0
        note = ""
        if analysis is None:
            # 診断: なぜ空になったか (parse 失敗か倫理ドロップか) を note に残す
            if parsed is None:
                note = f"parse_failed: {final_text[:300]}"
                logger.warning(
                    "watcher.parse_empty user=%s text=%r", watch.user_id, final_text[:300]
                )
            else:
                note = "ethics_dropped"
        if status != "max_iterations":
            status = "ok" if analysis else "empty"
        run_log = _build_run_log(
            run_id,
            watch.user_id,
            watch.all_codes(),
            tool_calls,
            n_assessed,
            status,
            note,
            token_cost,
        )
        self._persist(watch.user_id, run_log, analysis)
        return WatcherResult(analysis=analysis, run_log=run_log)

    def _persist(self, user_id: str, run_log: AgentRunLog, analysis: TownAnalysis | None) -> None:
        """repo があれば agent_runs + analysis を永続化 (graceful、無ければ skip)。"""
        if self.repo is None:
            return
        try:
            self.repo.save_run(run_log)
            if analysis is not None:
                self.repo.save_analysis(user_id, run_log.run_id, analysis)
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher.persist_failed user=%s err=%s", user_id, exc)
