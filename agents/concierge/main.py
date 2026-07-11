"""ConciergeAgent: 街診断 Migration Concierge (Plan E)。

設計 (TranslatorAgent / RelevanceAgent と並列):
    - ADK Runner ベースで Concierge Agent を起動、tool calls を収集して
      最終 reply + tool_call_logs + candidates を組み立てて返す
    - 倫理ガードレールは agents._shared.forbidden の FORBIDDEN_PATTERNS で post-validation
    - ADK Agent インスタンス自体は遅延構築 (テストで mock 注入可能)

このファイルは ConciergeAgent class のみ。実際の ADK Agent の build は
adk_agent.py の ADKConciergeAgent が行う (構造責務分離)。

設計判断:
    - main.py = orchestration + post-validation
    - adk_agent.py = ADK Agent / Tool 組立て
    - tools.py = 純粋な BQ query 関数
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol

from agents._shared.forbidden import find_forbidden_matches, find_political_leak

from .prompts.system import PROMPT_VERSION
from .schema import (
    ConciergeRequest,
    ConciergeResponse,
    MunicipalityCandidate,
    ToolCallLog,
)

if TYPE_CHECKING:
    from google.adk import Agent

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.4  # ヒアリング系は少し多様性、translator (0.3) より高め
DEFAULT_MAX_OUTPUT_TOKENS = 2048
DEFAULT_THINKING_BUDGET = 256  # tool 選択判断に少しは思考を割く
# 注: 反復ツール呼び出しの上限は実行体である GenaiConciergeRunner.MAX_ITERATIONS (=5) が
# 唯一の enforce ポイント。以前ここに MAX_TOOL_CALLS_PER_TURN 定数があったが、どこからも
# 参照されない死に定数で「上限がある」という誤った安心感を与えるため削除した (2026-07)。


class _RunnerProto(Protocol):
    """ADK Runner の最小 interface (テスト用 mock 注入)。"""

    def run(self, *args: object, **kwargs: object) -> Any: ...


class ConciergeAgent:
    """街診断 Migration Concierge Agent。

    Args:
        project_id: GCP project ID (Vertex AI / ADK 経由 Gemini)
        location: Vertex AI location
        model: Gemini モデル名
        prompt_version: ログ用 prompt バージョン
        agent: テスト用 mock 注入 (ADK Agent インスタンス、None なら遅延構築)
        runner: テスト用 mock 注入 (ADK Runner インスタンス)
    """

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        prompt_version: str = PROMPT_VERSION,
        temperature: float = DEFAULT_TEMPERATURE,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        thinking_budget: int = DEFAULT_THINKING_BUDGET,
        agent: Agent | None = None,
        runner: _RunnerProto | None = None,
        memory: Any | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.model = model
        self.prompt_version = prompt_version
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.thinking_budget = thinking_budget
        self._agent = agent
        self._runner = runner
        # Plan L+LL: ConversationMemory (Firestore + embedding) を optional 注入
        self._memory = memory

    def _format_persona(self, request: ConciergeRequest) -> str:
        """persona の自然言語要約を組み立て (system prompt の persona_desc 用)。"""
        p = request.persona
        parts = [
            f"- 年代: {p.age_group}",
            f"- 関心軸: {', '.join(p.interests) if p.interests else '未指定'}",
            f"- 登録自治体コード: {', '.join(p.municipality_codes) if p.municipality_codes else '未登録'}",
        ]
        # TASK-ONBOARDING: 前提整理 (省略時は出さない)。重視順は推薦・トレードオフ説明に反映させる。
        if p.priorities:
            parts.append(
                f"- 特に重視する順: {' > '.join(p.priorities)} (この優先順位で推薦・説明すること)"
            )
        if p.household:
            parts.append(f"- 家族構成: {p.household}")
        if p.budget_man is not None:
            parts.append(f"- 住まいの予算上限: {p.budget_man} 万円")
        if p.area_pref:
            parts.append(f"- 希望エリア(都道府県コード): {', '.join(p.area_pref)}")
        if p.free_form_context:
            parts.append(f"- 補足: {p.free_form_context}")
        return "\n".join(parts)

    def respond(self, request: ConciergeRequest) -> ConciergeResponse:
        """ユーザー入力に対して Concierge Agent を起動して 1 ターン応答を返す。

        現実装は **mock-friendly な薄い orchestration**:
            1. runner.run() を呼ぶ (or fallback で簡易 echo)
            2. 戻り値から reply / tool_calls / candidates を抽出
            3. find_forbidden_matches で post-validation
            4. ConciergeResponse として整形

        ADK Runner の戻り値 schema は ADK 2.x の Event 系を想定。
        テストでは Runner mock で固定 dict を返させる。
        """
        start = time.monotonic()
        try:
            if self._runner is None:
                # Runner 未注入時は遅延構築 (production)、失敗時は下の except に落ちる
                self._runner = self._build_runner()

            run_result = self._runner.run(
                request=request,
                persona_desc=self._format_persona(request),
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("concierge.runner_failed err=%s", exc)
            return ConciergeResponse(
                reply="申し訳ありません、システムエラーが発生しました。少し時間を置いて再度お試しください。",
                tool_calls=[],
                candidates=[],
                ethical_violations=["runner_exception"],
            )

        reply = run_result.get("reply", "") if isinstance(run_result, dict) else ""
        tool_call_logs_raw = (
            run_result.get("tool_calls", []) if isinstance(run_result, dict) else []
        )
        candidates_raw = run_result.get("candidates", []) if isinstance(run_result, dict) else []

        # tool_calls を ToolCallLog に正規化
        tool_calls = [self._normalize_tool_call(tc) for tc in tool_call_logs_raw]

        # candidates を MunicipalityCandidate に正規化 (search_municipalities が呼ばれた場合)
        candidates: list[MunicipalityCandidate] = []
        for c in candidates_raw:
            if isinstance(c, MunicipalityCandidate):
                candidates.append(c)
            elif isinstance(c, dict):
                try:
                    candidates.append(MunicipalityCandidate.model_validate(c))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("concierge.candidate_parse_failed err=%s", exc)

        # 倫理 post-validation (禁止語 + 政党名/政治家名 leak)
        ethical_violations = find_forbidden_matches(reply)
        political_leak = find_political_leak(reply)
        if political_leak:
            ethical_violations.append(f"political_leak: '{political_leak}'")
        if ethical_violations:
            logger.warning(
                "concierge.ethics_violation violations=%s reply_preview=%r",
                ethical_violations,
                reply[:200],
            )
            reply = (
                "申し訳ありません、応答内容が倫理ガイドラインに抵触したため、"
                "別の角度からお調べし直します。もう一度ご相談内容を教えていただけますか?"
            )

        duration_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "concierge.respond.done n_tools=%d n_candidates=%d duration_ms=%d violations=%s",
            len(tool_calls),
            len(candidates),
            duration_ms,
            ethical_violations,
        )

        # Plan L+LL: 倫理 OK の場合のみ Firestore に履歴保存 (fire-and-forget)
        if self._memory is not None and not ethical_violations:
            try:
                self._memory.save_turn(
                    user_id=request.persona.user_id,
                    message=request.message,
                    reply=reply,
                    candidates=candidates,
                )
            except Exception as exc:  # noqa: BLE001
                # save 失敗してもユーザー応答は返す (graceful)
                logger.warning("concierge.memory_save_failed err=%s", exc)

        return ConciergeResponse(
            reply=reply,
            tool_calls=tool_calls,
            candidates=candidates,
            ethical_violations=ethical_violations,
        )

    def _normalize_tool_call(self, tc: object) -> ToolCallLog:
        """ADK Runner の tool_call 戻り値を ToolCallLog に変換。"""
        if isinstance(tc, ToolCallLog):
            return tc
        if isinstance(tc, dict):
            name = str(tc.get("name", "unknown"))
            args = tc.get("args", {}) if isinstance(tc.get("args"), dict) else {}
            output = tc.get("output", "")
            preview = self._truncate_preview(output)
            duration_ms = int(tc.get("duration_ms", 0))
            return ToolCallLog(
                name=name,
                args=args,
                output_preview=preview,
                duration_ms=duration_ms,
            )
        return ToolCallLog(name="unknown", args={}, output_preview=str(tc)[:300])

    @staticmethod
    def _truncate_preview(output: object) -> str:
        """tool output を 300 文字以内の string に。"""
        try:
            if isinstance(output, str):
                return output[:300]
            return json.dumps(output, ensure_ascii=False, default=str)[:300]
        except Exception:  # noqa: BLE001
            return str(output)[:300]

    def _build_runner(self) -> _RunnerProto:
        """ADK Runner を遅延構築 (production)、テストでは __init__ で注入される。

        実装は adk_agent.py の ADKConciergeAgent で行うため、ここでは循環 import を
        避けるためコメントアウトしたままのスタブ。
        """
        # Phase 3 で endpoint 経由から build_runner() を呼ばれる時に実装
        raise NotImplementedError(
            "Runner は ADKConciergeAgent (adk_agent.py) から build_runner() で渡してください"
        )
