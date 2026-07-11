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

from agents._shared.forbidden import find_forbidden_matches, find_political_leak

from .prompts.system import (
    ADVOCATE_PROMPT,
    CRITIC_PROMPT,
    PLANNER_PROMPT,
    SPECIALIST_DESCRIPTIONS,
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
_SYNTH_MAX_ATTEMPTS = 3  # Synthesizer の最大試行回数 (解析失敗時のみ再実行し空振りを抑制)
# 補助エージェント(synthesize/critique/advocate/revise)の温度。verdict は結論なので
# 再現性を優先し低温に固定 (未設定だと ADK/Gemini 既定 ~1.0 で、同一ペルソナでも結論が
# 大きくゆらぐ。W8 対策 2026-07)。専門家(tools 付き)は探索の多様性を残すため未設定のまま。
_AUX_TEMPERATURE = 0.3

# 段階導入 (設計 §10): 既定は実績ある crew。本番で coordinator(=プランナー主導 Lv2.5) を
# smoke 検証後、Cloud Run env WATCHER_AUTONOMY_MODE=coordinator で有効化する。
DEFAULT_AUTONOMY_MODE = "crew"  # WATCHER_AUTONOMY_MODE 未設定時 (coordinator / crew)
# Lv3 ガードレール: coordinator が薄くしか調べなくても、街選びの核となる所見は必ず揃える
# コア専門家。欠けていればコードで補完ディスパッチする (本番 smoke で flash の偏り判明)。
# fiscal は compare_towns が living_safety と重複し latency 重いため床には含めない(任意)。
COVERAGE_FLOOR_DOMAINS: tuple[str, ...] = ("population", "living_safety", "topics")

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


def _extract_grounded_speech_ids(part: Any) -> set[str]:
    """ADK の function_response part から実在 speech_id を best-effort 抽出 (完全 guard)。

    search_speeches 等が返した dict/list を走査して speech_id を集める。ADK の
    レスポンス構造はバージョン差があるため、失敗しても例外を投げず空集合を返す
    (接地は「取れたら使う」補助であり、run を壊してはならない)。
    """
    ids: set[str] = set()
    try:
        fr = getattr(part, "function_response", None)
        if fr is None:
            return ids
        response = getattr(fr, "response", None)

        def _walk(obj: Any) -> None:
            if isinstance(obj, dict):
                sid = obj.get("speech_id")
                if isinstance(sid, str) and sid:
                    ids.add(sid)
                for v in obj.values():
                    _walk(v)
            elif isinstance(obj, (list, tuple)):
                for v in obj:
                    _walk(v)

        _walk(response)
    except Exception:  # noqa: BLE001
        return set()
    return ids


def _ground_finding_source_ids(
    finding: SpecialistFinding | None, grounded_ids: set[str]
) -> SpecialistFinding | None:
    """finding.source_speech_ids を実在 ID 集合に絞る (捏造 ID = 死にリンク防止)。

    grounded_ids が空 (ツール結果を拾えなかった) の場合は絞り込まない
    (over-filter で正当な所見を空にしないため、安全側)。
    """
    if finding is None or not grounded_ids or not finding.source_speech_ids:
        return finding
    kept = [sid for sid in finding.source_speech_ids if sid in grounded_ids]
    if len(kept) != len(finding.source_speech_ids):
        logger.info(
            "watcher.finding_ungrounded_ids_dropped domain=%s before=%d after=%d",
            finding.domain,
            len(finding.source_speech_ids),
            len(kept),
        )
        finding.source_speech_ids = kept
    return finding


def _coverage_missing(
    findings: list[SpecialistFinding], floor: tuple[str, ...] = COVERAGE_FLOOR_DOMAINS
) -> list[str]:
    """所見が揃っていないコア専門家ドメインを返す (Lv3 カバレッジ床、純関数)。"""
    have = {f.domain for f in findings}
    return [d for d in floor if d not in have]


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
    # fit_score は LLM 生成でゆらぐため、しきい値 10 以上の変化のみ「変化」とみなす(ノイズ抑制)
    prev_fit = {a.municipality_code: a.fit_score for a in prev.town_assessments}
    for a in cur.town_assessments:
        old = prev_fit.get(a.municipality_code)
        if old is not None and abs(a.fit_score - old) >= 10:
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
    joined = " ".join(texts)
    matches = find_forbidden_matches(joined)
    # 政党名 / 氏名+役職 の leak も検出。verdict 全体を破棄するゲートなので
    # 誤検知源の敬称パターン (「議員さん」等) は除外し高精度サブセットのみで判定。
    leak = find_political_leak(joined, include_honorific=False)
    if matches or leak or analysis.verdict.contains_political_judgment:
        logger.info("watcher.ethics_dropped matches=%s leak=%s", matches, leak)
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
        """1 ユーザー分の自律実行 → WatcherResult。

        WATCHER_AUTONOMY_MODE で実行戦略を選択 (設計 Lv3):
            coordinator: Coordinator LlmAgent が制御フローを所有する完全自律。
            crew(既定) : 固定クルー(4専門家→統合→批判→修正)。
        段階導入のため既定は crew。coordinator が例外 or 結論を出せない場合は
        **自動で crew にフォールバック** (回帰防止)。
        """
        import os

        mode = (os.getenv("WATCHER_AUTONOMY_MODE") or DEFAULT_AUTONOMY_MODE).strip().lower()
        if mode == "coordinator":
            try:
                result = await self._run_coordinator(watch, town_names)
                if result is not None and result.analysis is not None:
                    return result
                logger.warning("watcher.coordinator_no_analysis user=%s → crew", watch.user_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "watcher.coordinator_failed user=%s err=%s → crew", watch.user_id, exc
                )
        return await self._run_crew(watch, town_names)

    async def _run_crew(
        self, watch: WatchInput, town_names: dict[str, str] | None = None
    ) -> WatcherResult:
        """固定クルー型 (従来 run() 本体)。4専門家 並列 → 統合 → 批判+反論 → 条件付き修正。

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

        return self._finalize(
            watch,
            run_id,
            prev_analysis,
            draft,
            draft_parsed_ok,
            tool_calls,
            token_cost,
            findings,
            town_names=town_names,
            critique_note=critique_note,
            advocate_note=advocate_note,
        )

    def _finalize(
        self,
        watch: WatchInput,
        run_id: str,
        prev_analysis: TownAnalysis | None,
        draft: TownAnalysis | None,
        draft_parsed_ok: bool,
        tool_calls: list[ToolCall],
        token_cost: int | None,
        findings: list[SpecialistFinding],
        *,
        town_names: dict[str, str] | None = None,
        critique_note: str = "",
        advocate_note: str = "",
        investigation_plan: list[str] | None = None,
    ) -> WatcherResult:
        """倫理ゲート適用・透明性フィールド付与・run_log 構築・永続化 (crew/coordinator 共通の締め)。"""
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
            if investigation_plan:
                analysis.investigation_plan = investigation_plan
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
                priorities=list(watch.priorities),
                household=watch.household,
                budget_man=watch.budget_man,
                free_form_context=watch.free_form_context,
            )
            msg = gat.Content(role="user", parts=[gat.Part(text=prompt)])
            final_text = ""
            grounded_ids: set[str] = set()  # ツールが実在返却した speech_id (捏造検出用)
            capped = False
            async for event in runner.run_async(
                user_id=watch.user_id, session_id=sid, new_message=msg
            ):
                for part in getattr(getattr(event, "content", None), "parts", []) or []:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        tool_calls.append(ToolCall(tool=fc.name, args=dict(fc.args or {})))
                        if len(tool_calls) > MAX_SPECIALIST_TOOL_CALLS:
                            logger.warning("watcher.specialist_max domain=%s", domain)
                            capped = True
                            break
                    # ツール結果から実在 speech_id を best-effort 収集 (接地用、完全 guard)
                    grounded_ids |= _extract_grounded_speech_ids(part)
                usage = getattr(event, "usage_metadata", None)
                total = getattr(usage, "total_token_count", None) if usage else None
                if total is not None:
                    token_cost = total
                is_final = getattr(event, "is_final_response", lambda: False)()
                if is_final and event.content and event.content.parts:
                    final_text = event.content.parts[0].text or ""
                if capped:
                    # MAX 超過: 外側 event ループも抜けて specialist を確実に停止
                    # (以前は inner break のみで暴走が止まらなかった)。
                    break
            finding = parse_finding(final_text, domain)
            finding = _ground_finding_source_ids(finding, grounded_ids)
            return finding, tool_calls, token_cost
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
            description=SPECIALIST_DESCRIPTIONS.get(domain, f"{domain} ドメインの専門アナリスト"),
            model=self.model,
            instruction=SPECIALIST_INSTRUCTIONS.get(domain, ""),
            tools=[FunctionTool(func=f) for f in tool_funcs],
        )

    def _build_planner(self, plan_sink: list[str], selected_sink: list[str]) -> Any:
        """調査プランナー LlmAgent を構築 (Lv2.5)。record_plan のみを持ち、調査方針と
        対象専門家を LLM に決めさせる。実行(専門家)はコードが並列で行う(高速化)。lazy import。

        plan_sink / selected_sink: record_plan が受け取った方針・対象専門家を積むリスト(呼出側参照)。
        """
        from google.adk import Agent
        from google.adk.tools import FunctionTool

        def record_plan(plan: list[str], specialists: list[str], reason: str = "") -> dict:
            """調査の方針と、調べてもらう専門家を宣言する(最初に1回)。

            Args:
                plan: 何を重点的に調べるかの箇条書き。**ユーザー向けの平易な日本語**で、
                    ツール名やコードは含めない。
                specialists: 調査を依頼する専門家のキー。次から1つ以上選ぶ:
                    "population"(人口・将来性) / "fiscal"(財政) /
                    "living_safety"(住居・医療・治安) / "topics"(議事録の動き)。
                reason: その方針にした理由(ユーザーの優先順位に基づく)。
            """
            for p in plan or []:
                if isinstance(p, str) and p.strip():
                    plan_sink.append(p.strip())
            for s in specialists or []:
                d = str(s).strip().lower()
                if d in SPECIALIST_DOMAINS and d not in selected_sink:
                    selected_sink.append(d)
            logger.info(
                "watcher.plan_recorded items=%d specialists=%s reason=%s",
                len(plan_sink),
                selected_sink,
                reason,
            )
            return {"status": "recorded", "specialists": selected_sink}

        return Agent(
            name="watcher_planner",
            description="街選び調査のプランナー",
            model=self.model,
            instruction=PLANNER_PROMPT,
            tools=[FunctionTool(func=record_plan)],
        )

    async def _run_coordinator(
        self, watch: WatchInput, town_names: dict[str, str] | None = None
    ) -> WatcherResult:
        """Lv2.5: プランナー(LLM)が調査計画と対象専門家を決定 → コードが専門家を **並列実行** →
        統合 → 自己検証。pure Lv3 の逐次性によるレイテンシを避けつつ、計画と采配は LLM が握る。
        """
        import asyncio
        import uuid

        import google.genai.types as gat
        from google.adk import Runner
        from google.adk.sessions import InMemorySessionService

        self._ensure_vertex_env()
        run_id = uuid.uuid4().hex

        prev_analysis: TownAnalysis | None = None
        if self.repo is not None:
            try:
                prev_analysis = self.repo.get_latest_analysis(watch.user_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("watcher.prev_fetch_failed user=%s err=%s", watch.user_id, exc)

        prompt = build_watch_user_prompt(
            watch.user_id,
            watch.age_group,
            list(watch.interests),
            watch.home_municipality_code,
            list(watch.watched_codes),
            town_names=town_names,
            priorities=list(watch.priorities),
            household=watch.household,
            budget_man=watch.budget_man,
            free_form_context=watch.free_form_context,
        )

        # 1. プランナー: 調査方針と対象専門家を LLM に決めさせる (record_plan のみ・軽量1ラウンド)。
        plan_sink: list[str] = []
        selected_sink: list[str] = []
        tool_calls: list[ToolCall] = []
        token_cost: int | None = None
        try:
            planner = self._build_planner(plan_sink, selected_sink)
            ss = InMemorySessionService()
            await ss.create_session(
                app_name="watcher_planner", user_id=watch.user_id, session_id=run_id
            )
            runner = Runner(agent=planner, app_name="watcher_planner", session_service=ss)
            msg = gat.Content(role="user", parts=[gat.Part(text=prompt)])
            async for event in runner.run_async(
                user_id=watch.user_id, session_id=run_id, new_message=msg
            ):
                for part in getattr(getattr(event, "content", None), "parts", []) or []:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        tool_calls.append(ToolCall(tool=fc.name, args=dict(fc.args or {})))
                usage = getattr(event, "usage_metadata", None)
                total = getattr(usage, "total_token_count", None) if usage else None
                if total is not None:
                    token_cost = total
        except Exception as exc:  # noqa: BLE001
            logger.warning("watcher.planner_failed user=%s err=%s", watch.user_id, exc)

        # 2. 実行する専門家 = LLM 選択 ∪ カバレッジ床 (核は必ず調べる)。SPECIALIST_DOMAINS 順を保つ。
        chosen = set(selected_sink) | set(COVERAGE_FLOOR_DOMAINS)
        run_domains = [d for d in SPECIALIST_DOMAINS if d in chosen]

        # 3. 専門家をコードが **並列実行** (crew と同じ fan-out = 高速)。
        findings: list[SpecialistFinding] = []
        results = await asyncio.gather(
            *[self._run_specialist(d, watch, town_names) for d in run_domains],
            return_exceptions=True,
        )
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

        # 専門家全滅 → 空 (run() が crew にフォールバック)。
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

        # 4. 統合 (専門家所見 → TownAnalysis 草案)。
        draft = await self._synthesize(findings, watch, town_names, prev_analysis)
        draft_parsed_ok = draft is not None

        # 5. 独立した自己検証(Critic A1 / Devil's Advocate A9)を **必ず1回** 通す (失敗は graceful)。
        critique_note, advocate_note = "", ""
        if draft is not None:
            try:
                draft, critique_note, advocate_note = await self._verify_and_revise(
                    draft, watch, town_names
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("watcher.verify_failed user=%s err=%s", watch.user_id, exc)

        return self._finalize(
            watch,
            run_id,
            prev_analysis,
            draft,
            draft_parsed_ok,
            tool_calls,
            token_cost,
            findings,
            town_names=town_names,
            critique_note=critique_note,
            advocate_note=advocate_note,
            investigation_plan=plan_sink,
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
            priorities=list(watch.priorities),
            household=watch.household,
            budget_man=watch.budget_man,
            free_form_context=watch.free_form_context,
        )
        # A2: 前回結論を継続性のため文脈に追加 (状況が変われば反映、変わらなければ一貫性)
        if prev_analysis is not None and prev_analysis.verdict.headline:
            context += f"\n\n# 前回の結論(継続性の参考)\n{prev_analysis.verdict.headline}"
        findings_json = json.dumps([f.model_dump() for f in findings], ensure_ascii=False)
        synth_msg = build_synth_prompt(findings_json, context)
        # 統合は結論の要。解析失敗は LLM のサンプリング変動が主因(同入力で成否が割れる)なので
        # 最大3回まで再試行し空振り(status=empty)を実質排除する。失敗時のみ追加実行。
        parsed: TownAnalysis | None = None
        for attempt in range(_SYNTH_MAX_ATTEMPTS):
            if attempt:
                logger.info("watcher.synthesize_retry user=%s attempt=%d", watch.user_id, attempt)
            text = await self._run_single_agent(SYNTHESIZER_PROMPT, synth_msg)
            parsed = parse_analysis(text)
            if parsed is not None:
                break
        return parsed

    async def _run_single_agent(self, instruction: str, message: str) -> str:
        """ツール無しの単発 ADK エージェントを1回回し、最終テキストを返す (critique/advocate/revise 用)。"""
        import uuid

        import google.genai.types as gat
        from google.adk import Agent, Runner
        from google.adk.sessions import InMemorySessionService

        # JSON モード: ツール無しの補助エージェント(synthesize/critique/advocate/revise)は
        # 必ず JSON を返すので、構文上妥当な JSON を強制し parse 失敗(synthesize_failed)を防ぐ。
        # ※ tools 付きの専門家エージェントは function-calling と非互換のため適用しない。
        agent = Agent(
            name="watcher_aux",
            model=self.model,
            instruction=instruction,
            tools=[],
            generate_content_config=gat.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=_AUX_TEMPERATURE,
            ),
        )
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
            priorities=list(watch.priorities),
            household=watch.household,
            budget_man=watch.budget_man,
            free_form_context=watch.free_form_context,
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
