# Watcher 自律性 Lv3 — Coordinator LlmAgent 設計

- **日付**: 2026-06-15
- **ステータス**: 設計承認済み（実装前）
- **関連**: docs/PROJECT.md §審査基準①、docs/plans/2026-06-07-agent-autonomy-v2-design.md（P3 マルチエージェント）

---

## 1. 背景・課題

審査基準①「AIエージェントが価値の中核か」に対し、現状の Watcher は **固定クルー型**：コードが `4専門家(並列) → 統合 → 批判+反論 → (条件付き1回)修正` の順序をハードコードしている（[agents/watcher/main.py](../../agents/watcher/main.py) `run()`）。

本物の自律は2箇所のみ：
- 各専門家の**ツール使用**（LLM が tool/args/回数を決定、`_run_specialist`）
- **条件付き自己修正**（`should_revise`）

弱点：**「何を・どの深さで調べるか」「もう一度掘るか」「いつ終えるか」をコードが決めている**＝プランナー不在。鋭い審査員に「エージェントが計画していない（クルーは開発者がハードコード）」と突かれうる。

## 2. ゴール / 非ゴール

**ゴール**: 制御フロー自体を **Coordinator `LlmAgent` が所有**し、調査計画・専門家の選択/再ディスパッチ・自己批判・終了判断を **LLM が毎ステップ決定**する完全自律オーケストレーター（Lv3）を実装する。自律性を**実装の事実**として（デモ演出に依存せず）示す。

**非ゴール**:
- 既存の固定クルーを廃止すること（→ フォールバックとして温存）
- 専門家の内部ロジック・ツール群の作り替え（既存を AgentTool で再利用）
- UI の全面刷新（`investigation_plan` 表示の追加のみ）

## 3. アーキテクチャ

```
Coordinator LlmAgent  ── 制御フローを所有（function-calling ループ）
  instruction = COORDINATOR_PROMPT（計画→調査→深掘り→批判→結論、倫理ゲート）
  tools = [
    record_plan(plan, reason),            # FunctionTool: 最初に調査計画を宣言（可視化用）
    AgentTool(specialist_population),     # 専門家を“道具”として保持（内部で自前のツールループ）
    AgentTool(specialist_fiscal),
    AgentTool(specialist_living_safety),
    AgentTool(specialist_topics),
    AgentTool(critic_agent),              # 自己批判を呼ぶか自分で判断
    AgentTool(advocate_agent),            # 反論を呼ぶか自分で判断
  ]
```

- **AgentTool 採用理由**: `sub_agents`+transfer は制御が委譲され戻って集約できない。コーディネータが最終 `TownAnalysis` を統合する以上、**結果を受け取って制御を保持できる AgentTool が正解**。
- **自律のネスト**: コーディネータが専門家を選ぶ／専門家が内部で自分のツール（`compare_towns` 等）を選ぶ。
- 専門家エージェント本体は既存 `_build_specialist_agent` を流用（instruction/tool 部分集合は不変）。
- ADK の `AgentTool` import 経路（`google.adk.tools.agent_tool` 等）は **local の google.genai が壊れているため本番 smoke で実機検証**。

## 4. 制御フロー（LLM が所有）

コーディネータの instruction で次を要求（順序は LLM 判断、コードは強制しない）：

1. `record_plan` で **調査計画を最初に宣言**（persona の priorities に基づき、何を重点的に調べるか）。
2. 必要な専門家を `AgentTool` 経由で呼ぶ（全員でなくてよい／重みづけは計画次第）。
3. 所見を観察し、**データ不足・矛盾があれば該当専門家を再度呼んで深掘り**（re-plan）。
4. 確信が持てたら `critic_agent`/`advocate_agent` を呼び、指摘を結論へ反映。
5. 十分なら **最終 `TownAnalysis` JSON のみ**を出力して終了。

コードが持つのは**上限と最終整形だけ**（下記 §5）。

## 5. リスク緩和（Lv3 を壊れにくくする 3 装置）

### (a) フォールバック温存（最重要）
- 現行 `run()` を **`_run_crew()` にリネームして温存**。新規 `_run_coordinator()` を追加。
- env flag **`WATCHER_AUTONOMY_MODE`**（`coordinator`(既定) / `crew`）で切替。
- coordinator が例外 or 解析不能で結論を出せない場合、**自動で `_run_crew()` にフォールバック** → 既存の動く価値を絶対に失わない。

### (b) 構造化出力の二段構え
- coordinator は tools 付き＝JSON モード非互換。最終応答は既存 `parse_analysis`（正規抽出＋pydantic 検証）で受ける。
- **パース不能なら、収集済み `SpecialistFinding` を既存 `_synthesize`（JSON モード）に通して整形**＝結論を必ず出す（Lv2.5 的セーフティネット）。

### (c) 有界化
- **総ツール呼び出し上限** `MAX_COORDINATOR_STEPS`（例 16）＝コスト/レイテンシ/タイムアウト対策。超過時は「今ある材料で結論せよ」と促し finalize、それでも不可なら (b)→(a)。
- トークンも既存同様 `usage_metadata` で集計し `run_log.token_cost` に記録。

## 6. 自律性を「実装で見せる」成果物

- **AutonomyTrace（既存UI [apps/web/src/components/watcher/autonomy-trace.tsx]）が本物の証拠化**: `tool_calls` に `record_plan` → `specialist_population` → `specialist_topics`(2回目=深掘り) → `critic` … と **persona/ラン毎に変わる軌跡**が出る。
- **調査計画アーティファクト**: `record_plan` の内容を `TownAnalysis.investigation_plan: list[str]` に保存し、`/agent` に表示（「子育て重視のため医療・教育を重点調査」等）。**「エージェントが計画した」を可視化**。

## 7. 変更ファイル

### Backend
- `agents/watcher/main.py`:
  - `run()` → `WATCHER_AUTONOMY_MODE` で `_run_coordinator()` / `_run_crew()` に分岐 + フォールバック結線。
  - 既存フロー本体を `_run_crew()` にリネーム（純粋関数 parse/ethics/diff は流用）。
  - `_build_coordinator()`（AgentTool 群を組む）、`_collect_plan_and_findings()`（イベントから `record_plan` 引数と specialist 戻りを回収）。
  - `record_plan` FunctionTool（状態に計画を積むクロージャ）。
- `agents/watcher/prompts/system.py`: `COORDINATOR_PROMPT` 追加（計画→調査→深掘り→批判→結論、倫理・出力 JSON 規約は既存と統一）。
- `agents/watcher/schema.py`: `TownAnalysis.investigation_plan: list[str] = []`（後方互換）。`AgentRunLog.status` に `max_iterations` は既存。
- `apps/api/main.py`: 変更最小（agent 生成箇所は不変。flag は env 読み）。

### Frontend
- `apps/web/src/lib/api.ts`: `TownAnalysisSchema` に `investigation_plan: z.array(z.string()).default([])`。
- `apps/web/src/app/agent/page.tsx`（or 新 `investigation-plan.tsx`）: 計画セクション表示。

### Tests
- `agents/watcher/tests/test_watcher.py`: 純粋関数は維持。新規：
  - `WATCHER_AUTONOMY_MODE=crew` で従来どおり動く（既存 fake/mocks 流用）。
  - **coordinator 失敗 → crew フォールバック**が発火し結論が出る（coordinator パスを例外に monkeypatch）。
  - `_build_coordinator` の構造テスト（tools 名の集合が期待どおり）。
- 自律ループ本体は **本番 smoke** で検証（local genai 破損のため unit 不可）。

## 8. 完了条件（受け入れ）

1. `WATCHER_AUTONOMY_MODE=coordinator`（本番）で `/v1/watcher/{uid}/run` が **`investigation_plan` ＋ persona 毎に変わる `tool_calls` 軌跡 ＋ 妥当な `TownAnalysis`** を返す。
2. coordinator を強制失敗させると **`_run_crew()` にフォールバックして結論が出る**（テスト green）。
3. 倫理ゲート（`apply_ethics`）・bound（`MAX_COORDINATOR_STEPS`）・graceful（空は status=empty）維持。
4. `ruff check/format` ・ `pytest agents apps/api` ・ `tsc` ・ `next build` 全 green。
5. `/agent` に調査計画が表示され、AutonomyTrace に coordinator の判断列が出る。

## 9. リスク

| リスク | 対策 |
|---|---|
| AgentTool の import/挙動が ADK 2.1.0 で想定と違う | 本番 smoke で早期検証。差異あれば AgentTool 不可時は「専門家を関数ツール化」に切替（同一 instruction を FunctionTool ラッパで）|
| coordinator がループしてタイムアウト | `MAX_COORDINATOR_STEPS` で打ち切り→ finalize→(b)→(a) |
| 最終 JSON が崩れる | 二段構え (b)：collected findings を `_synthesize` で整形 |
| coordinator が専門家を全く呼ばず薄い結論 | プロンプトで「最低 priorities 上位2軸は調査」を要求 + crew フォールバック |
| 既存クルーの回帰 | `_run_crew()` 温存 + flag 既定を一時的に crew にして段階移行も可 |
| デモ再現性（軌跡が毎回違う） | 軌跡が変わること自体が自律の証拠。デモは事前 1 回 warm して提示 |

## 10. 段階導入

1. coordinator 実装 + flag 既定 `crew` で本番デプロイ（回帰ゼロを確認）。
2. 本番 smoke で coordinator を手動検証（plan/trace/JSON）。
3. 問題なければ flag 既定を `coordinator` に切替。
