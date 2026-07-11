"""GenaiConciergeRunner: google.genai 関数呼び出しベースの Concierge Runner (Plan E Phase 3)。

**本番 /v1/concierge の実行体はこの Runner**。google.genai SDK 直で LLM call と
tool 呼び出しのループをオーケストレーションする、4 tool を自律反復する単一エージェント。
(ADK 親子構成 adk_agent.py は demo 用の別成果物で、本番経路ではない。)

設計判断:
    - Plan C の translator/relevance と同じ `client.models.generate_content()` 経由
    - 4 tool は Pydantic *Args の model_json_schema() で FunctionDeclaration 生成
    - 反復 loop: LLM → function_call(s) → execute → function_response → LLM → ...
    - max_iterations 5 で gating (無限 retry 防止) ← 反復上限の唯一の enforce ポイント
    - 各 tool 呼び出しは別 sub-Pydantic instance に variate して invoke

なぜ ADK Runner ではないか:
    ADK Runner の Event ストリーム解析は ADK 2.x の API surface が新しく安定性
    不明。Plan C で実証済の google.genai 直叩きの方が、production の信頼性が高い。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from agents._shared.forbidden import find_forbidden_matches, find_political_leak

from . import tools as concierge_tools
from .prompts.system import SYSTEM_PROMPT, build_user_prompt
from .schema import (
    ConciergeRequest,
    FetchCityDashboardArgs,
    FetchCitySpeechesArgs,
    MunicipalityCandidate,
    SearchMunicipalitiesArgs,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_LOCATION = "us-central1"
DEFAULT_TEMPERATURE = 0.4
DEFAULT_MAX_OUTPUT_TOKENS = 2048
MAX_ITERATIONS = 5  # tool call ループ上限 (無限 retry 防止)


def _inject_persona_premises(args: dict[str, Any], persona: Any) -> dict[str, Any]:
    """TASK-ONBOARDING: persona の前提を search_municipalities の args に決定的注入。

    priorities は persona を採用 (重み付けに使用)。制約は会話で未指定の項目だけ補完
    (家賃上限 / 希望エリア / 子育て世帯→保育施設>=1)。会話で明示された制約を上書きしない。
    """
    merged = dict(args)
    pri = list(getattr(persona, "priorities", None) or [])
    if pri:
        merged["priorities"] = pri
    cons = dict(merged.get("constraints") or {})
    budget = getattr(persona, "budget_man", None)
    if budget is not None and cons.get("max_avg_rent_man") is None:
        cons["max_avg_rent_man"] = float(budget)
    area = list(getattr(persona, "area_pref", None) or [])
    if area and not cons.get("prefecture_codes"):
        cons["prefecture_codes"] = area
    if (
        getattr(persona, "household", "") == "family_kids"
        and cons.get("min_childcare_count") is None
    ):
        cons["min_childcare_count"] = 1
    if cons:
        merged["constraints"] = cons
    return merged


class _GenAIClientProto(Protocol):
    """google.genai.Client の最小 interface (mock 注入用)。"""

    models: Any


class GenaiConciergeRunner:
    """google.genai 関数呼び出しベースの Concierge Runner。

    Args:
        project_id: GCP project ID (Vertex AI)
        location: Vertex AI location
        model: Gemini モデル名
        client: テスト用 mock 注入 (google.genai.Client インスタンス)
        bq_client: テスト用 mock 注入 (BQ client、tools.py に渡す)
    """

    def __init__(
        self,
        project_id: str | None = None,
        location: str = DEFAULT_LOCATION,
        model: str = DEFAULT_MODEL,
        temperature: float = DEFAULT_TEMPERATURE,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        max_iterations: int = MAX_ITERATIONS,
        client: _GenAIClientProto | None = None,
        bq_client: Any | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.max_iterations = max_iterations
        self._client = client
        self._bq_client = bq_client

    def _ensure_client(self) -> _GenAIClientProto:
        if self._client is not None:
            return self._client
        from google import genai

        self._client = genai.Client(vertexai=True, project=self.project_id, location=self.location)
        return self._client

    # ------------------------------------------------------------------
    # Tool 実行: name + args dict から実際の tool function を呼ぶ
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, args: dict[str, Any], persona: Any = None) -> Any:
        """Tool name + args dict から実際の関数を呼んで結果を返す。

        TASK-ONBOARDING: search_municipalities には persona の前提 (priorities/予算/エリア/家族)
        を決定的に注入 (LLM が埋め損ねても効く)。会話で明示された制約 (args) を優先。
        """
        if name == "search_municipalities":
            if persona is not None:
                args = _inject_persona_premises(args, persona)
            parsed = SearchMunicipalitiesArgs.model_validate(args)
            return concierge_tools.search_municipalities(parsed, bq_client=self._bq_client)
        if name == "compare_municipalities":
            return concierge_tools.compare_municipalities(
                municipality_codes=args["municipality_codes"],
                interest=args["interest"],
                limit=args.get("limit", 3),
                bq_client=self._bq_client,
                user_id=args.get("user_id", "demo-25-29"),
            )
        if name == "fetch_city_dashboard":
            parsed = FetchCityDashboardArgs.model_validate(args)
            return concierge_tools.fetch_city_dashboard(parsed, bq_client=self._bq_client)
        if name == "fetch_city_speeches":
            parsed = FetchCitySpeechesArgs.model_validate(args)
            return concierge_tools.fetch_city_speeches(parsed, bq_client=self._bq_client)
        raise ValueError(f"Unknown tool: {name}")

    # ------------------------------------------------------------------
    # FunctionDeclaration build (genai に渡す tool schema)
    # ------------------------------------------------------------------

    def _build_tools_param(self) -> Any:
        """4 つの tool の FunctionDeclaration を含む Tool オブジェクトを返す。"""
        from google.genai import types

        from .schema import CompareMunicipalitiesArgs

        return [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name="search_municipalities",
                        description=(
                            "ペルソナ (年代 + 関心軸) と制約 (家賃上限 / 保育園下限 等) から"
                            "合う自治体 TOP N を match_score (0-100) 順で返す。"
                            "ユーザーが街診断を求めたら最初に呼ぶべき主要 tool。"
                        ),
                        parameters_json_schema=SearchMunicipalitiesArgs.model_json_schema(),
                    ),
                    types.FunctionDeclaration(
                        name="compare_municipalities",
                        description=(
                            "2-3 自治体を同一 interest 軸で比較。"
                            "各自治体の上位議題 (translated summary 含む) を横並びで返す。"
                            "ユーザーが「A 市と B 市を比べて」と言ったら呼ぶ。"
                        ),
                        parameters_json_schema=CompareMunicipalitiesArgs.model_json_schema(),
                    ),
                    types.FunctionDeclaration(
                        name="fetch_city_dashboard",
                        description=(
                            "1 自治体の街ダッシュボード (主要統計 + 関心軸別議題数 + 上位議題)。"
                            "ユーザーが特定の自治体について詳しく聞いた時に呼ぶ。"
                        ),
                        parameters_json_schema=FetchCityDashboardArgs.model_json_schema(),
                    ),
                    types.FunctionDeclaration(
                        name="fetch_city_speeches",
                        description=(
                            "1 自治体の議題を relevance 順で取得 (optional interest フィルタ)。"
                            "ユーザーが「この街の最近の話題は?」のような要求時に呼ぶ。"
                        ),
                        parameters_json_schema=FetchCitySpeechesArgs.model_json_schema(),
                    ),
                ]
            )
        ]

    # ------------------------------------------------------------------
    # メインの runner.run() — ConciergeAgent.respond() から呼ばれる
    # ------------------------------------------------------------------

    def run(
        self,
        request: ConciergeRequest,
        persona_desc: str,
    ) -> dict[str, Any]:
        """LLM + 4 tool の反復 loop で対話 1 ターン分の応答を組み立てる。

        Returns:
            ConciergeAgent.respond() が期待する dict:
                {"reply": str, "tool_calls": list[dict], "candidates": list[dict]}
        """
        from google.genai import types

        client = self._ensure_client()
        user_prompt = build_user_prompt(request.message, persona_desc)
        tools_param = self._build_tools_param()

        # genai contents (会話履歴) を組み立て。初回は user message のみ。
        contents: list[Any] = [types.Content(role="user", parts=[types.Part(text=user_prompt)])]

        tool_calls_log: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []

        for iteration in range(self.max_iterations):
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=tools_param,
                    temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
                ),
            )

            # response.candidates[0].content.parts から function_call / text を抽出
            function_calls, response_text = self._extract_calls_and_text(response)

            if not function_calls:
                # 終端: text を最終応答として返す
                logger.info(
                    "concierge.runner.done iterations=%d n_tools=%d n_candidates=%d",
                    iteration + 1,
                    len(tool_calls_log),
                    len(candidates),
                )
                return {
                    "reply": response_text,
                    "tool_calls": tool_calls_log,
                    "candidates": candidates,
                }

            # function_call(s) を実行
            assistant_parts: list[Any] = []
            user_parts: list[Any] = []

            for fc in function_calls:
                fc_name = fc.name or "unknown"
                fc_args = dict(fc.args or {})

                start = time.monotonic()
                try:
                    output = self._execute_tool(fc_name, fc_args, persona=request.persona)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("concierge.tool_failed name=%s err=%s", fc_name, exc)
                    output = {"error": str(exc)}
                duration_ms = int((time.monotonic() - start) * 1000)

                # search_municipalities の場合は candidates を抽出
                if fc_name == "search_municipalities" and isinstance(output, list):
                    for item in output:
                        if isinstance(item, MunicipalityCandidate):
                            candidates.append(item.model_dump())
                        elif isinstance(item, dict):
                            candidates.append(item)

                # output を genai に渡せる serializable に変換
                serializable_output = self._serialize_for_genai(output)

                tool_calls_log.append(
                    {
                        "name": fc_name,
                        "args": fc_args,
                        "output": serializable_output,
                        "duration_ms": duration_ms,
                    }
                )

                # assistant_parts: function_call (LLM の発話を会話履歴に保存)
                assistant_parts.append(types.Part(function_call=fc))

                # user_parts: function_response (我々が実行した結果を LLM に返す)
                user_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc_name,
                            response={"result": serializable_output},
                        )
                    )
                )

            # 会話履歴に append
            contents.append(types.Content(role="model", parts=assistant_parts))
            contents.append(types.Content(role="user", parts=user_parts))

        # max_iterations 到達 (LLM が無限 retry 状態)
        logger.warning("concierge.runner.max_iterations_reached iters=%d", self.max_iterations)
        return {
            "reply": "ご相談内容が複雑なため、絞り込みきれませんでした。もう少し条件を限定して再度お聞かせください。",
            "tool_calls": tool_calls_log,
            "candidates": candidates,
        }

    # ------------------------------------------------------------------
    # genai response parsing
    # ------------------------------------------------------------------

    def _extract_calls_and_text(self, response: Any) -> tuple[list[Any], str]:
        """genai response.candidates[0].content.parts から function_call / text を分離。"""
        function_calls: list[Any] = []
        text_chunks: list[str] = []

        try:
            cand = response.candidates[0] if response.candidates else None
            if cand is None:
                return [], (getattr(response, "text", "") or "")

            content = cand.content
            parts = (content.parts if content else []) or []
            for part in parts:
                if hasattr(part, "function_call") and part.function_call is not None:
                    fc = part.function_call
                    if (fc.name or "") != "":
                        function_calls.append(fc)
                elif hasattr(part, "text") and part.text:
                    text_chunks.append(part.text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("concierge.runner.response_parse_failed err=%s", exc)
            return [], (getattr(response, "text", "") or "")

        text = "".join(text_chunks).strip()
        return function_calls, text

    @staticmethod
    def _serialize_for_genai(output: Any) -> Any:
        """tool output を JSON-serializable に変換。Pydantic / list を flatten。"""
        try:
            if hasattr(output, "model_dump"):
                return output.model_dump(mode="json")
            if isinstance(output, list):
                return [
                    item.model_dump(mode="json") if hasattr(item, "model_dump") else item
                    for item in output
                ]
            if isinstance(output, dict):
                return output
            return str(output)
        except Exception:  # noqa: BLE001
            return str(output)


# ----------------------------------------------------------------------
# Module-level factory (FastAPI endpoint から使う)
# ----------------------------------------------------------------------


def build_runner(
    project_id: str | None = None,
    **kwargs: Any,
) -> GenaiConciergeRunner:
    """Production 用 Runner 生成のヘルパー (lazy import friendly)。"""
    return GenaiConciergeRunner(project_id=project_id, **kwargs)


# ----------------------------------------------------------------------
# Post-validation helper (FastAPI endpoint で reply を後処理する用)
# ----------------------------------------------------------------------


def validate_reply_ethics(reply: str) -> list[str]:
    """reply に倫理違反パターンが含まれているか check。"""
    violations = find_forbidden_matches(reply)
    leak = find_political_leak(reply)
    if leak:
        violations.append(f"political_leak: '{leak}'")
    return violations
