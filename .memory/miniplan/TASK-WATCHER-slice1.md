# ミニプラン: マイ街エージェント Slice 1 (自律性の証明)

## 概要
- **タスク ID**: TASK-WATCHER-S1
- **目的**: ADK 自律プランナーが「**自分でツールを選んで**」watch街の新着から Discovery を
  why_surfaced 付きで 1 件生成できることを e2e で証明する縦切り。①(自律性)の作りを先に確定。
- **設計**: docs/plans/2026-06-06-machi-watch-agent-design.md
- **完了条件**:
  - `agents/watcher/` 新規。ADK `LlmAgent` がツール2つ(search_speeches / fetch_population_trend)を
    **LLM の判断で**呼び、Discovery(title/summary/why_surfaced/significance/source refs)を生成
  - 手順をハードコードしない(スクリプト化禁止。LLM がツール選択)
  - 倫理: 既存 forbidden-pattern 検証を Discovery に適用
  - 1 デモユーザー × watch街1 で動作確認(BQ/ADK は mock 可の unit test + 実データ smoke)
  - Discovery schema (pydantic) + agent_runs の tool_calls 記録
  - 8+ test 全 pass、ruff clean
- **想定工数**: 2-3h

## スコープ (Slice 1 のみ)
### IN
- `agents/watcher/schema.py`: WatchInput / Discovery / AgentRunLog
- `agents/watcher/tools.py`: search_speeches / fetch_population_trend を ADK FunctionTool 化 (既存BQ流用)
- `agents/watcher/main.py`: ADK LlmAgent 構築 + 自律ループ起動 + Discovery 抽出 + 倫理検証
- `agents/watcher/prompts/system.py`: 自律プランナーのシステムプロンプト (目標 + ツール使用方針 + 倫理)
- `agents/watcher/tests/`: 自律ツール選択 / Discovery生成 / 倫理ゲート / graceful

### OUT (後続 Slice)
- 複数街・全ツール (Slice 2) / ホームUI (Slice 3) / Push日次Job (Slice 4)
- Firestore 永続化は Slice 1 では schema 定義のみ、書込みは Slice 2 で (or mock)

## 設計詳細
### Discovery schema
```python
class Discovery(BaseModel):
    municipality_code: str
    title: str
    summary: list[str]            # translator 流用 (若者向け)
    why_surfaced: str             # 「なぜあなたに」= 差別化の核 (max 200字)
    significance: Literal["high","medium","low"]
    source_speech_ids: list[str]
    contains_political_judgment: bool   # 倫理チェック
```
### 自律ループ (main.py) — ★ADK Runner 採用確定 (2026-06-06 スパイク OK)
- **スパイク結果**: scrapers/reinfolib/adk_runner_spike.py を実環境で実行 → `SPIKE_RESULT=OK`。
  ADK Runner 2.1.0 が `run_async` で LLM にツールを自律選択させ正しく実行することを実証。
  旧 runner.py の「ADK 2.x 不安定」評価は過去のもの → **ADK Runner を採用**(⑤最強・①genuine)
- **実装**: `google.adk` の `Agent`(tools=[FunctionTool(func=...)]) + `Runner(agent, app_name,
  session_service=InMemorySessionService)` + `run_async` でイベントを解析し tool_calls を記録
- **Discovery 抽出**: ADK は tools と output_schema の併用に制約があるため、
  **エージェントの最終応答を JSON で出させてパース**(version 非依存・堅牢)
- **サンドボックス制約**: 開発環境では google.adk の import 不可(google.genai 読取制限)。
  → main.py は **lazy import**(adk_agent.py パターン)、unit test は ADK/genai を **stub**(conftest 流用)、
  実 Runner 実行の検証は **実環境 smoke**(自律性ゲート)で行う
- `max_iterations` 相当: Runner は自然終了するが、暴走防止に **tool_call 上限 + token 監視**を main 側で記録/打切り
- tools=[search_speeches, fetch_population_trend] を function declarations として渡す
- system prompt で目標を与える:「このユーザーの watch街・関心・人生段階を踏まえ、新着から
  *本人に意味があるもの* を見つけ、必要なら人口推移等で深掘りし、why_surfaced を付けて返せ」
- **LLM が `function_calls` を自分で生成 = ツール選択は LLM の自律判断**(スクリプト化しない)
- **`max_iterations=5`**(runner.py 流用)で gating。到達時は safe に打ち切り = コスト bound
- **Discovery は LLM 最終応答を structured output(response_schema / JSON)でパース**
  (why_surfaced は LLM 生成物なので structured 必然。Medium#5)
- 出力 Discovery に既存 `agents/_shared/forbidden` の find_forbidden_matches を適用
  → political なら surface しない or below_threshold

### 既存資産の流用元
- search_speeches: concierge/tools.py の BQ single-query 純関数パターン
- fetch_population_trend: **apps/api/main.py の population-trend SQL を tools.py の純関数として移植**
  (`municipality_population_series` を tools.py の定数で定義。Medium#4)
- 倫理検証: `agents/_shared/forbidden` の find_forbidden_matches (Concierge main.py:155 で実績)
- 自律ループ: **concierge/runner.py の GenaiConciergeRunner**(反復 function-calling, max_iterations=5)

## 作業ステップ
1. [ ] agents/watcher/ 雛形 + schema.py (Discovery / WatchInput / AgentRunLog)
2. [ ] tools.py: search_speeches / fetch_population_trend を FunctionTool 化 (BQ client DI)
3. [ ] prompts/system.py: 自律プランナー system prompt (目標/ツール方針/倫理footer)
4. [ ] main.py: ADK LlmAgent 構築 + run + Discovery 抽出 + 倫理検証 + tool_calls 記録
5. [ ] tests (8+ = 5観点 × 正常/異常): ①ループが任意の tool 系列を捌く(機構) ②Discovery生成
   ③政治的内容は surface しない ④BQ/LLM失敗graceful ⑤why_surfaced 必須 ⑥max_iterations で打切り
   ※ unit test は LLM 出力を mock 固定するため「機構」の検証。**自律性そのものは unit で証明不可**
6. [ ] **自律性の合否ゲート = 実データ smoke (Reviewer High#2)**: ツール選択を指示しない prompt で
   2状況(新着少/多)を実 Gemini に投げ、`tool_calls[]` が状況で変わることを1回確認しログ保存。
   (dangerouslyDisableSandbox + SSL_CERT_FILE)
7. [ ] ruff + regression

## 成果物
- agents/watcher/{__init__,schema,tools,main}.py + prompts/system.py + tests/

## リスク・懸念点
| リスク | 対策 |
|---|---|
| スクリプト化(自律でない) | ADK にツールを渡し LLM に選択を委ねる。test で「状況により呼ぶツールが変わる」を検証 |
| ADK のツール呼び出しが mock しづらい | concierge tests の ADK mock パターン流用 |
| コスト | Slice1 は1ユーザーのみ。ツール呼出上限を agent 設定に |
| 倫理すり抜け | Discovery 出力に既存検証を必ず通す test |

## Out of Scope
- Firestore 永続化の本実装 (Slice 2)、ホームUI (Slice 3)、Push Job (Slice 4)、Veo (Phase 2)
