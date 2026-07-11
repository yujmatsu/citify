"""OpsCrewAgent: 運用 SRE マルチエージェントクルー。

Watcher と **同一の設計パターン** を運用ドメインに適用する:
    計画 → 並列専門家 → 統合(synthesizer) → 批判(critic) → 人間/ブラスト半径ゲート

専門家は既存エージェントを **合成** (重複実装しない):
    - scraper_health : agents.scraper_doctor (DiagnosticAgent + RepairProposalAgent)
    - cost           : agents.cost_hunter (CostAnomalyDetector + CostRootCauseAgent)
    - data_freshness : 純関数 (最終取込からの経過時間シグナルを受け取り判定)

安全:
    - すべての提案・結論に `requires_human_review=True` を **サーバー側で強制** (自動実行防止)。
    - run() は決して例外を投げない (Firestore/LLM 障害でも graceful に status を返す)。

テスト容易性: 全依存 (sub-agents / repo / detector / synth client) は
コンストラクタで注入可能。未指定なら lazy に実体を構築する。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Protocol

from .prompts.system import (
    CRITIC_SYSTEM_PROMPT,
    SYNTH_SYSTEM_PROMPT,
    build_critic_user_prompt,
    build_synth_user_prompt,
    dumps,
)
from .schema import (
    OpsAssessment,
    OpsCrewResult,
    OpsFinding,
    OpsRemediationProposal,
    OpsRunLog,
    OpsToolCall,
    OpsVerdict,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.2  # 運用判断は再現性重視
DEFAULT_MAX_OUTPUT_TOKENS = 1024
MAX_PER_DOMAIN = 5  # 1 ドメインあたり診断する最大件数 (コスト bound)
_FRESHNESS_STALE_HOURS = 30.0  # 日次バッチ想定 (24h) + 猶予

# 重大度ランク (専門家由来の文字列を数値化。未知値は 0)。
_SEVERITY_RANK: dict[str, int] = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "none": 0,
}
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)
# 破壊的/自動実行を示唆する action 語 (検出したら risk を risky に引き上げ)
_DESTRUCTIVE_HINTS = ("delete", "drop", "scale_down", "disable", "terminate", "rm ", "truncate")


class _GenAIClientProto(Protocol):
    models: Any


def _severity_rank(sev: str) -> int:
    return _SEVERITY_RANK.get(str(sev).lower(), 0)


def _extract_json(text: str) -> dict | None:
    """LLM 応答から最初の JSON オブジェクトを取り出す (graceful)。"""
    if not text:
        return None
    m = _JSON_BLOCK.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group())
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


class OpsCrewAgent:
    """運用アセスメントを行うマルチエージェントクルー。"""

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        *,
        diagnostic_agent: Any | None = None,
        repair_agent: Any | None = None,
        failure_repo: Any | None = None,
        cost_detector: Any | None = None,
        cost_root_cause_agent: Any | None = None,
        cost_seed_loader: Any | None = None,
        synth_client: _GenAIClientProto | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.model = model
        self._diagnostic_agent = diagnostic_agent
        self._repair_agent = repair_agent
        self._failure_repo = failure_repo
        self._cost_detector = cost_detector
        self._cost_root_cause_agent = cost_root_cause_agent
        self._cost_seed_loader = cost_seed_loader
        self._synth_client = synth_client

    # ------------------------------------------------------------------ lazy deps
    def _diag(self) -> Any:
        if self._diagnostic_agent is None:
            from agents.scraper_doctor.main import DiagnosticAgent

            self._diagnostic_agent = DiagnosticAgent(project_id=self.project_id)
        return self._diagnostic_agent

    def _repair(self) -> Any:
        if self._repair_agent is None:
            from agents.scraper_doctor.main import RepairProposalAgent

            self._repair_agent = RepairProposalAgent(project_id=self.project_id)
        return self._repair_agent

    def _failures(self) -> Any:
        if self._failure_repo is None:
            from agents.scraper_doctor.firestore_repo import FailureLogRepository

            self._failure_repo = FailureLogRepository()
        return self._failure_repo

    def _detector(self) -> Any:
        if self._cost_detector is None:
            from agents.cost_hunter.detector import CostAnomalyDetector

            self._cost_detector = CostAnomalyDetector()
        return self._cost_detector

    def _root_cause(self) -> Any:
        if self._cost_root_cause_agent is None:
            from agents.cost_hunter.main import CostRootCauseAgent

            self._cost_root_cause_agent = CostRootCauseAgent(project_id=self.project_id)
        return self._cost_root_cause_agent

    def _cost_seed(self) -> Any:
        if self._cost_seed_loader is None:
            from agents.cost_hunter.seed_loader import load_sample_seed

            self._cost_seed_loader = load_sample_seed
        return self._cost_seed_loader

    def _client(self) -> _GenAIClientProto:
        if self._synth_client is not None:
            return self._synth_client
        from google import genai

        self._synth_client = genai.Client(
            vertexai=True, project=self.project_id, location=self.location
        )
        return self._synth_client

    # ------------------------------------------------------------------ run
    async def run(
        self,
        *,
        days: int = 7,
        use_sample: bool = False,
        freshness_hours: float | None = None,
        max_per_domain: int = MAX_PER_DOMAIN,
    ) -> OpsCrewResult:
        """運用アセスメントを実行。決して例外を投げない (graceful)。

        Args:
            days: スクレイパー/コストの参照期間。
            use_sample: Firestore が空/未構築のとき seed を使うか。
            freshness_hours: 最終取込からの経過時間 (API 層で BQ から算出して渡す)。
                None なら data_freshness 専門家はスキップ。
        """
        run_id = uuid.uuid4().hex
        tool_calls: list[OpsToolCall] = []
        try:
            results = await asyncio.gather(
                asyncio.to_thread(self._scraper_specialist, days, use_sample, max_per_domain),
                asyncio.to_thread(self._cost_specialist, max_per_domain),
                asyncio.to_thread(self._freshness_specialist, freshness_hours),
                return_exceptions=True,
            )
        except Exception as exc:  # noqa: BLE001 (gather 自体は return_exceptions で守るが二重防御)
            logger.exception("ops_crew.gather_failed run=%s err=%s", run_id, exc)
            return OpsCrewResult(
                run_log=OpsRunLog(run_id=run_id, status="error", note=f"gather_failed: {exc}")
            )

        findings: list[OpsFinding] = []
        proposals: list[OpsRemediationProposal] = []
        for r in results:
            if isinstance(r, Exception):
                logger.warning("ops_crew.specialist_exception run=%s err=%s", run_id, r)
                continue
            if r is None:
                continue
            finding, props, calls = r
            tool_calls.extend(calls)
            if finding is not None:
                findings.append(finding)
                proposals.extend(props)

        targets = [f.domain for f in findings]
        if not findings:
            return OpsCrewResult(
                run_log=OpsRunLog(
                    run_id=run_id,
                    targets_checked=targets,
                    tool_calls=tool_calls,
                    n_findings=0,
                    status="empty",
                    note="no findings (すべて正常 or データ無し)",
                )
            )

        # 統合 → 批判 → 安全ゲート
        verdict = self._synthesize(findings)
        critique_note = self._critique(verdict, findings)
        assessment = OpsAssessment(
            verdict=verdict,
            findings=findings,
            proposals=proposals,
            critique_note=critique_note,
            investigation_plan=self._plan(findings),
        )
        assessment = self._enforce_safety(assessment)

        return OpsCrewResult(
            assessment=assessment,
            run_log=OpsRunLog(
                run_id=run_id,
                targets_checked=targets,
                tool_calls=tool_calls,
                n_findings=len(findings),
                status="ok",
            ),
        )

    # ------------------------------------------------------------------ specialists
    def _scraper_specialist(
        self, days: int, use_sample: bool, max_per_domain: int
    ) -> tuple[OpsFinding | None, list[OpsRemediationProposal], list[OpsToolCall]]:
        from agents.scraper_doctor.firestore_repo import dedupe_by_pattern

        calls = [OpsToolCall(tool="scraper.fetch_recent_failures", args={"days": days})]
        try:
            repo = self._failures()
            failures = repo.fetch_recent(days=days, limit=50)
            if not failures and use_sample:
                failures = repo.load_sample_seed()
            failures = dedupe_by_pattern(failures)[:max_per_domain]
        except Exception as exc:  # noqa: BLE001
            logger.warning("ops_crew.scraper_fetch_failed err=%s", exc)
            return None, [], calls

        if not failures:
            return None, [], calls

        props: list[OpsRemediationProposal] = []
        worst = "none"
        categories: list[str] = []
        refs: list[str] = []
        for f in failures:
            try:
                diag = self._diag().diagnose(f)
                calls.append(
                    OpsToolCall(tool="scraper.diagnose", args={"failure_id": f.failure_id})
                )
                proposal = self._repair().propose(diag, f)
                categories.append(str(diag.error_category))
                refs.append(f.failure_id)
                if _severity_rank(str(diag.severity)) > _severity_rank(worst):
                    worst = str(diag.severity)
                props.append(
                    OpsRemediationProposal(
                        domain="scraper_health",
                        action=str(proposal.proposed_action),
                        rationale=proposal.rationale,
                        risk_assessment=proposal.risk_assessment,
                        source=proposal.source,
                    )
                )
            except Exception as exc:  # noqa: BLE001 (1 件失敗で全体を止めない)
                logger.warning("ops_crew.scraper_diag_failed id=%s err=%s", f.failure_id, exc)
                continue

        finding = OpsFinding(
            domain="scraper_health",
            headline=f"{len(failures)} 件の失敗パターンを検知",
            key_points=[f"主なカテゴリ: {', '.join(sorted(set(categories))[:4])}"]
            if categories
            else [],
            severity=worst,
            confidence="medium",
            source_refs=refs,
        )
        return finding, props, calls

    def _cost_specialist(
        self, max_per_domain: int
    ) -> tuple[OpsFinding | None, list[OpsRemediationProposal], list[OpsToolCall]]:
        from agents.cost_hunter.detector import detect_cross_service_pattern

        calls = [OpsToolCall(tool="cost.load_observations", args={})]
        try:
            observations = self._cost_seed()()
            anomalies = self._detector().detect_anomalies(observations)
            calls.append(OpsToolCall(tool="cost.detect_anomalies", args={"n": len(observations)}))
        except Exception as exc:  # noqa: BLE001
            logger.warning("ops_crew.cost_detect_failed err=%s", exc)
            return None, [], calls

        abnormal = [a for a in anomalies if str(a.anomaly_type) != "normal"]
        abnormal.sort(key=lambda a: (_severity_rank(str(a.severity)), a.spike_ratio), reverse=True)
        abnormal = abnormal[:max_per_domain]
        if not abnormal:
            return None, [], calls

        cross = detect_cross_service_pattern(anomalies)
        props: list[OpsRemediationProposal] = []
        worst = "none"
        services: list[str] = []
        for a in abnormal:
            try:
                proposal = self._root_cause().propose(a, trend_summary=cross or "")
                calls.append(OpsToolCall(tool="cost.root_cause", args={"service": str(a.service)}))
                services.append(str(a.service))
                if _severity_rank(str(a.severity)) > _severity_rank(worst):
                    worst = str(a.severity)
                props.append(
                    OpsRemediationProposal(
                        domain="cost",
                        action=str(proposal.proposed_action),
                        rationale=proposal.rationale,
                        risk_assessment=proposal.risk_assessment,
                        source=proposal.source,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ops_crew.cost_root_cause_failed svc=%s err=%s", a.service, exc)
                continue

        key_points = [f"異常サービス: {', '.join(sorted(set(services))[:4])}"] if services else []
        if cross:
            key_points.append(f"横断: {cross}")
        finding = OpsFinding(
            domain="cost",
            headline=f"{len(abnormal)} 件のコスト異常を検知",
            key_points=key_points,
            severity=worst,
            confidence="medium",
            source_refs=services,
        )
        return finding, props, calls

    def _freshness_specialist(
        self, freshness_hours: float | None
    ) -> tuple[OpsFinding | None, list[OpsRemediationProposal], list[OpsToolCall]]:
        calls = [OpsToolCall(tool="freshness.check", args={"hours": freshness_hours})]
        if freshness_hours is None:
            return None, [], calls
        if freshness_hours <= _FRESHNESS_STALE_HOURS:
            # 鮮度 OK → 所見なし (正常)
            return None, [], calls
        finding = OpsFinding(
            domain="data_freshness",
            headline=f"データが {freshness_hours:.0f} 時間更新されていません",
            key_points=[
                f"日次バッチ想定 ({_FRESHNESS_STALE_HOURS:.0f}h) を超過",
                "Cloud Scheduler の paused / worker 失敗の可能性",
            ],
            severity="high" if freshness_hours > _FRESHNESS_STALE_HOURS * 2 else "medium",
            confidence="high",
            source_refs=["scored_speeches_latest"],
        )
        props = [
            OpsRemediationProposal(
                domain="data_freshness",
                action="investigate_pipeline",
                rationale="Scheduler の resume 状態と直近 worker 実行ログを確認",
                risk_assessment="safe",
                source="rule_based",
            )
        ]
        return finding, props, calls

    # ------------------------------------------------------------------ synth / critic
    def _synthesize(self, findings: list[OpsFinding]) -> OpsVerdict:
        """LLM で統合結論を作る。失敗時は rule-based fallback。"""
        try:
            from google.genai import types

            payload = dumps([f.model_dump() for f in findings])
            resp = self._client().models.generate_content(
                model=self.model,
                contents=build_synth_user_prompt(payload),
                config=types.GenerateContentConfig(
                    system_instruction=SYNTH_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=DEFAULT_TEMPERATURE,
                    max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
                ),
            )
            data = _extract_json(getattr(resp, "text", "") or "")
            if data:
                dom = data.get("top_priority_domain")
                if dom not in ("scraper_health", "cost", "data_freshness"):
                    dom = self._rule_top_domain(findings)
                return OpsVerdict(
                    headline=str(data.get("headline", ""))[:160],
                    reasoning=str(data.get("reasoning", ""))[:600],
                    top_priority_domain=dom,
                    confidence=self._coerce_conf(data.get("confidence")),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ops_crew.synth_llm_failed err=%s", exc)
        return self._rule_based_verdict(findings)

    def _critique(self, verdict: OpsVerdict, findings: list[OpsFinding]) -> str:
        """LLM 批判。失敗時は空文字 (graceful、結論は残す)。"""
        try:
            from google.genai import types

            resp = self._client().models.generate_content(
                model=self.model,
                contents=build_critic_user_prompt(
                    dumps(verdict.model_dump()), dumps([f.model_dump() for f in findings])
                ),
                config=types.GenerateContentConfig(
                    system_instruction=CRITIC_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    temperature=DEFAULT_TEMPERATURE,
                    max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
                ),
            )
            data = _extract_json(getattr(resp, "text", "") or "")
            if data:
                return str(data.get("note", ""))[:600]
        except Exception as exc:  # noqa: BLE001
            logger.warning("ops_crew.critic_llm_failed err=%s", exc)
        return ""

    # ------------------------------------------------------------------ rule-based / safety
    @staticmethod
    def _coerce_conf(v: Any) -> str:
        return v if v in ("high", "medium", "low") else "medium"

    @staticmethod
    def _rule_top_domain(findings: list[OpsFinding]) -> str | None:
        if not findings:
            return None
        return max(findings, key=lambda f: _severity_rank(f.severity)).domain

    def _rule_based_verdict(self, findings: list[OpsFinding]) -> OpsVerdict:
        top = self._rule_top_domain(findings)
        heads = "; ".join(f.headline for f in findings if f.headline)[:160]
        return OpsVerdict(
            headline=heads or "運用アセスメント完了",
            reasoning="LLM 統合が使えなかったため、重大度最大のドメインを優先課題としました。",
            top_priority_domain=top,
            confidence="low",
        )

    @staticmethod
    def _plan(findings: list[OpsFinding]) -> list[str]:
        order = sorted(findings, key=lambda f: _severity_rank(f.severity), reverse=True)
        return [f"[{f.domain}] {f.headline}" for f in order if f.headline]

    @staticmethod
    def _enforce_safety(assessment: OpsAssessment) -> OpsAssessment:
        """ブラスト半径ゲート: 人間レビュー強制 + 破壊的 action を risky に引き上げ。

        cost_hunter._enforce_safety_constraints と同じ「LLM の後段でポリシー上書き」パターン。
        """
        assessment.verdict.requires_human_review = True
        for p in assessment.proposals:
            p.requires_human_review = True
            if any(h in p.action.lower() for h in _DESTRUCTIVE_HINTS):
                p.risk_assessment = "risky"
        return assessment
