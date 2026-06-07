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

from .prompts.system import (
    ADVOCATE_PROMPT,
    CRITIC_PROMPT,
    SPECIALIST_INSTRUCTIONS,
    SYNTHESIZER_PROMPT,
    build_review_user_prompt,
    build_revise_prompt,
    build_synth_prompt,
    build_watch_user_prompt,
)
from .schema import (
    Advocacy,
    AgentRunLog,
    Critique,
    SpecialistFinding,
    ToolCall,
    TownAnalysis,
    WatcherResult,
    WatchInput,
)

# P3: 専門エージェントと担当ツール (A5)。各ドメインは tool 部分集合で自ドメインを調査。
SPECIALIST_TOOLS: dict[str, tuple[str, ...]] = {
    "population": ("fetch_population_trend", "compare_towns"),
    "fiscal": ("compare_towns",),
    "living_safety": ("compare_towns",),
    "topics": ("search_speeches", "fetch_topic_trend"),
}
SPECIALIST_DOMAINS: tuple[str, ...] = ("population", "fiscal", "living_safety", "topics")
MAX_SPECIALIST_TOOL_CALLS = 4  # 専門家1人あたりのツール上限

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
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


def _extract_json(final_text: str) -> dict | None:
    """最外 JSON ブロックを dict で抽出 (critique/advocacy 用、graceful)。"""
    if not final_text:
        return None
    m = _JSON_BLOCK.search(final_text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def parse_critique(final_text: str) -> Critique | None:
    """Critic 応答 (JSON) を Critique に。失敗は None (graceful)。"""
    data = _extract_json(final_text)
    if data is None:
        return None
    try:
        return Critique.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.critique_invalid err=%s", exc)
        return None


def parse_advocacy(final_text: str) -> Advocacy | None:
    """Devil's Advocate 応答 (JSON) を Advocacy に。失敗は None (graceful)。"""
    data = _extract_json(final_text)
    if data is None:
        return None
    try:
        return Advocacy.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.advocacy_invalid err=%s", exc)
        return None


def parse_finding(final_text: str, domain: str) -> SpecialistFinding | None:
    """専門エージェント応答 (JSON) を SpecialistFinding に。失敗は None (graceful)。"""
    data = _extract_json(final_text)
    if data is None:
        return None
    data["domain"] = domain  # LLM が日本語ラベル等を入れても正規キーに強制 (UI マップ整合)
    try:
        return SpecialistFinding.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        logger.warning("watcher.finding_invalid domain=%s err=%s", domain, exc)
        return None


def should_revise(critique: Critique | None) -> bool:
    """critique が修正を要求しているか。None は False (草案を採用)。"""
    if critique is None:
        return False
    return critique.needs_revision or bool(
        critique.issues or critique.missing_axes or critique.grounding_failures
    )


def _summarize_critique(critique: Critique | None) -> str:
    """critique を1行要約 (UI/透明性用)。"""
    if critique is None:
        return ""
    parts = [*critique.issues, *critique.missing_axes, *critique.grounding_failures]
    return " / ".join(parts[:3])


def diff_against_previous(
    prev: TownAnalysis | None,
    cur: TownAnalysis,
    town_names: dict[str, str] | None = None,
) -> list[str]:
    """前回分析と今回を比較し、変化を街名で表現した list[str] にする (A3、純関数)。

    文言は揺れるので比較しない。構造化フィールド(推し街・各街 fit_score)中心。
    prev が None(初回)は空。
    """
    if prev is None:
        return []
    names = town_names or {}

    def nm(code: str) -> str:
        return names.get(code) or f"自治体{code}"

    changes: list[str] = []
    # 推し街の変更
    if prev.verdict.recommended_code != cur.verdict.recommended_code:
        before = nm(prev.verdict.recommended_code) if prev.verdict.recommended_code else "未定"
        after = nm(cur.verdict.recommended_code) if cur.verdict.recommended_code else "未定"
        if before != after:
            changes.append(f"推し街が {before} → {after} に変わりました")
    # 各街の適合度の増減 (同 municipality_code をマッチ)
    prev_fit = {a.municipality_code: a.fit_score for a in prev.town_assessments}
    for a in cur.town_assessments:
        old = prev_fit.get(a.municipality_code)
        if old is not None and abs(a.fit_score - old) >= 5:
            arrow = "上昇" if a.fit_score > old else "低下"
            changes.append(f"{nm(a.municipality_code)}の評価が {old} → {a.fit_score} に{arrow}")
    return changes


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

    async def run(
        self, watch: WatchInput, town_names: dict[str, str] | None = None
    ) -> WatcherResult:
        """1 ユーザー分の自律実行 → WatcherResult (repo があれば Firestore 永続化)。

        town_names: コード→街名。出力文章で街名を使わせるためにプロンプトへ渡す(任意)。
        """
        import asyncio
        import uuid

        self._ensure_vertex_env()
        run_id = uuid.uuid4().hex

        # P4: 前回分析を取得 (A3 変化検知 + A2 継続性)。repo 無し(smoke)は None。
        prev_analysis: TownAnalysis | None = None
        if self.repo is not None:
            try:
                prev_analysis = self.repo.get_latest_analysis(watch.user_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("watcher.prev_fetch_failed user=%s err=%s", watch.user_id, exc)

        # P3: 4 専門エージェントを並行ディスパッチ (A5)。各自が自ドメインを自律調査。
        tool_calls: list[ToolCall] = []
        token_cost: int | None = None
        results = await asyncio.gather(
            *[self._run_specialist(d, watch, town_names) for d in SPECIALIST_DOMAINS],
            return_exceptions=True,
        )
        findings: list[SpecialistFinding] = []
        for r in results:
            if isinstance(r, BaseException) or r is None:
                if isinstance(r, BaseException):
                    logger.warning("watcher.specialist_failed err=%s", r)
                continue
            finding, tcalls, tcost = r
            tool_calls.extend(tcalls)
            if tcost is not None:
                token_cost = (token_cost or 0) + tcost
            if finding is not None:
                findings.append(finding)

        # 専門家全滅 → 空 (graceful)
        if not findings:
            run_log = _build_run_log(
                run_id,
                watch.user_id,
                watch.all_codes(),
                tool_calls,
                0,
                "empty",
                "no_specialist_findings",
                token_cost,
            )
            self._persist(watch.user_id, run_log, None)
            return WatcherResult(analysis=None, run_log=run_log)

        # Synthesizer: 専門家所見を統合し TownAnalysis 草案 (A2: 前回結論を継続性のため渡す)
        draft = await self._synthesize(findings, watch, town_names, prev_analysis)
        draft_parsed_ok = draft is not None

        # P2: 自己批判(A1) + 悪魔の代弁者(A9) + 修正。草案がある時のみ、失敗は graceful。
        critique_note, advocate_note = "", ""
        if draft is not None:
            try:
                draft, critique_note, advocate_note = await self._verify_and_revise(
                    draft, watch, town_names
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("watcher.verify_failed user=%s err=%s", watch.user_id, exc)

        analysis = apply_ethics(draft)
        n_assessed = len(analysis.town_assessments) if analysis else 0
        note = ""
        if analysis is None:
            note = "synthesize_failed" if not draft_parsed_ok else "ethics_dropped"
        else:
            # 透明性: 検証・反論の要約 + 専門家所見 + 前回からの変化を付与 (倫理スキャン後に設定)
            analysis.critique_note = critique_note
            analysis.devils_advocate = advocate_note
            analysis.specialist_findings = findings
            analysis.changes_since_last = diff_against_previous(prev_analysis, analysis, town_names)
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

    async def _run_specialist(
        self, domain: str, watch: WatchInput, town_names: dict[str, str] | None
    ) -> tuple[SpecialistFinding | None, list[ToolCall], int | None]:
        """1 専門エージェント(ツール付き)を回し SpecialistFinding を返す。失敗は (None,[],None)。"""
        import google.genai.types as gat
        from google.adk import Runner
        from google.adk.sessions import InMemorySessionService

        tool_calls: list[ToolCall] = []
        token_cost: int | None = None
        try:
            agent = self._build_specialist_agent(domain)
            ss = InMemorySessionService()
            app, sid = f"spec_{domain}", watch.user_id
            await ss.create_session(app_name=app, user_id=watch.user_id, session_id=sid)
            runner = Runner(agent=agent, app_name=app, session_service=ss)
            prompt = build_watch_user_prompt(
                watch.user_id,
                watch.age_group,
                list(watch.interests),
                watch.home_municipality_code,
                list(watch.watched_codes),
                town_names=town_names,
            )
            msg = gat.Content(role="user", parts=[gat.Part(text=prompt)])
            final_text = ""
            async for event in runner.run_async(
                user_id=watch.user_id, session_id=sid, new_message=msg
            ):
                for part in getattr(getattr(event, "content", None), "parts", []) or []:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        tool_calls.append(ToolCall(tool=fc.name, args=dict(fc.args or {})))
                        if len(tool_calls) > MAX_SPECIALIST_TOOL_CALLS:
                            logger.warning("watcher.specialist_max domain=%s", domain)
                            break
                usage = getattr(event, "usage_metadata", None)
                total = getattr(usage, "total_token_count", None) if usage else None
                if total is not None:
                    token_cost = total
                is_final = getattr(event, "is_final_response", lambda: False)()
                if is_final and event.content and event.content.parts:
                    final_text = event.content.parts[0].text or ""
            return parse_finding(final_text, domain), tool_calls, token_cost
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher.specialist_run_failed domain=%s err=%s", domain, exc)
            return None, tool_calls, token_cost

    def _build_specialist_agent(self, domain: str) -> Any:
        """ドメイン別の専門 ADK エージェント (instruction + tool 部分集合)。lazy import。"""
        from google.adk import Agent
        from google.adk.tools import FunctionTool

        from . import tools as watcher_tools

        tool_funcs = [getattr(watcher_tools, name) for name in SPECIALIST_TOOLS.get(domain, ())]
        return Agent(
            name=f"specialist_{domain}",
            description=f"{domain} ドメインの専門アナリスト",
            model=self.model,
            instruction=SPECIALIST_INSTRUCTIONS.get(domain, ""),
            tools=[FunctionTool(func=f) for f in tool_funcs],
        )

    async def _synthesize(
        self,
        findings: list[SpecialistFinding],
        watch: WatchInput,
        town_names: dict[str, str] | None,
        prev_analysis: TownAnalysis | None = None,
    ) -> TownAnalysis | None:
        """専門家所見を統合し TownAnalysis 草案を生成 (Synthesizer、ツール無し単発)。

        prev_analysis: 前回の結論。継続性のため文脈に渡す (A2)。
        """
        context = build_watch_user_prompt(
            watch.user_id,
            watch.age_group,
            list(watch.interests),
            watch.home_municipality_code,
            list(watch.watched_codes),
            town_names=town_names,
        )
        # A2: 前回結論を継続性のため文脈に追加 (状況が変われば反映、変わらなければ一貫性)
        if prev_analysis is not None and prev_analysis.verdict.headline:
            context += f"\n\n# 前回の結論(継続性の参考)\n{prev_analysis.verdict.headline}"
        findings_json = json.dumps([f.model_dump() for f in findings], ensure_ascii=False)
        text = await self._run_single_agent(
            SYNTHESIZER_PROMPT, build_synth_prompt(findings_json, context)
        )
        return parse_analysis(text)

    async def _run_single_agent(self, instruction: str, message: str) -> str:
        """ツール無しの単発 ADK エージェントを1回回し、最終テキストを返す (critique/advocate/revise 用)。"""
        import uuid

        import google.genai.types as gat
        from google.adk import Agent, Runner
        from google.adk.sessions import InMemorySessionService

        agent = Agent(name="watcher_aux", model=self.model, instruction=instruction, tools=[])
        ss = InMemorySessionService()
        sid = uuid.uuid4().hex[:8]
        await ss.create_session(app_name="watcher_aux", user_id="aux", session_id=sid)
        runner = Runner(agent=agent, app_name="watcher_aux", session_service=ss)
        msg = gat.Content(role="user", parts=[gat.Part(text=message)])
        final_text = ""
        async for event in runner.run_async(user_id="aux", session_id=sid, new_message=msg):
            is_final = getattr(event, "is_final_response", lambda: False)()
            if is_final and event.content and event.content.parts:
                final_text = event.content.parts[0].text or ""
        return final_text

    async def _verify_and_revise(
        self, draft: TownAnalysis, watch: WatchInput, town_names: dict[str, str] | None
    ) -> tuple[TownAnalysis, str, str]:
        """Draft を Critic(A1)+Advocate(A9)で検証し、必要なら1回 Revise。

        Returns: (最終 analysis, critique_note, advocate_note)。LLM 失敗時は draft をそのまま。
        """
        context = build_watch_user_prompt(
            watch.user_id,
            watch.age_group,
            list(watch.interests),
            watch.home_municipality_code,
            list(watch.watched_codes),
            town_names=town_names,
        )
        draft_json = json.dumps(draft.model_dump(), ensure_ascii=False)
        review_msg = build_review_user_prompt(draft_json, context)

        # critique と advocate は独立 → 並列実行でレイテンシ短縮 (Cloud Run timeout 対策)
        import asyncio

        critic_text, advocate_text = await asyncio.gather(
            self._run_single_agent(CRITIC_PROMPT, review_msg),
            self._run_single_agent(ADVOCATE_PROMPT, review_msg),
        )
        critique = parse_critique(critic_text)
        advocacy = parse_advocacy(advocate_text)
        critique_note = _summarize_critique(critique)
        advocate_note = advocacy.counter_verdict if advocacy else ""

        if should_revise(critique):
            crit_json = json.dumps(critique.model_dump(), ensure_ascii=False) if critique else "{}"
            adv_json = json.dumps(advocacy.model_dump(), ensure_ascii=False) if advocacy else "{}"
            revise_instr = build_revise_prompt(crit_json, adv_json)
            revised = parse_analysis(
                await self._run_single_agent(revise_instr, f"# 草案\n{draft_json}")
            )
            if revised is not None:
                draft = revised
                logger.info("watcher.revised user=%s", watch.user_id)
        return draft, critique_note, advocate_note

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
