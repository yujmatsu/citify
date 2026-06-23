# ミニプラン: Watcher 自律性 Lv3 — Coordinator LlmAgent

## 概要
- **タスクID**: TASK-WATCHER-LV3（設計: docs/plans/2026-06-15-watcher-autonomy-lv3-coordinator-design.md）
- **目的**: 制御フローを Coordinator `LlmAgent` が所有する完全自律オーケストレーターを実装し、
  審査基準①「AIエージェントが価値の中核」を**主張ではなく実装の事実**にする。
- **完了条件**:
  1. `WATCHER_AUTONOMY_MODE=coordinator` で `/run` が `investigation_plan` ＋ 妥当な `TownAnalysis` を返し、
     **`tool_calls` に `record_plan` と、priorities 上位2軸に対応する specialist が出現**する（検証可能・本番 smoke）
  2. coordinator 失敗時に `_run_crew()` へ自動フォールバックし結論が出る（テスト green）
  3. 倫理ゲート・bound(`MAX_COORDINATOR_STEPS`)・graceful 維持
  4. `ruff` / `pytest agents apps/api` / `tsc` / `next build` 全 green
  5. `/agent` に調査計画表示 + AutonomyTrace に coordinator の判断列

## スコープ
### IN
- `_run_crew()` 温存（現 `run()` 本体をリネーム）+ `_run_coordinator()` 追加 + flag 分岐 + フォールバック
- `_build_coordinator()`（AgentTool で専門家/critic/advocate を保持）, `record_plan` FunctionTool
- `COORDINATOR_PROMPT` 追加（計画→調査→深掘り→批判→結論、倫理・JSON 規約は既存統一）
- `TownAnalysis.investigation_plan` 追加（後方互換）+ UI 表示
- 構造化出力の二段構え（parse 不能→ `_synthesize` で整形）

### OUT
- 専門家の内部ロジック/ツール群の作り替え（既存流用）
- UI 全面刷新（計画表示の追加のみ）
- 固定クルーの廃止（温存）

## 作業ステップ
1. [ ] **[先行] AgentTool 疎通 smoke**: ADK 2.1.0 で `AgentTool(agent=...)` の import/最小動作を本番で1本確認（不可なら FunctionTool ラッパ方式に即切替＝以降のステップ前にリスク潰し）
2. [ ] schema: `TownAnalysis.investigation_plan: list[str] = []`（+ api.ts zod 同期）
3. [ ] prompts: `COORDINATOR_PROMPT` 追加
4. [ ] main.py: 現 `run()` → `_run_crew()` リネーム（挙動不変、既存テスト green 維持）
5. [ ] main.py: `record_plan` ツール / `_build_coordinator()` / `_run_coordinator()`（イベント回収・bound・二段構え）
5. [ ] main.py: `run()` を flag 分岐 + coordinator 失敗→crew フォールバック結線
6. [ ] main.py: `run()` を flag 分岐 + coordinator 失敗→crew フォールバック結線
7. [ ] tests: crew 既定で従来通り / coordinator 失敗→fallback / `_build_coordinator` 構造テスト
8. [ ] UI: `/agent` に investigation_plan セクション
9. [ ] 検証: ruff / pytest / tsc / next build → 本番デプロイ(flag=crew) → smoke → flag=coordinator

## 上限とタイムアウトの整合
- `MAX_COORDINATOR_STEPS`（例 16）は **coordinator が直接呼ぶツール回数の上限**（専門家内部のツール呼び出しは既存 `MAX_SPECIALIST_TOOL_CALLS=4` が別途 bound）。
- 専門家1人 ≒ 数十秒。最悪ケース（16ステップ×専門家呼び）が Cloud Run の API timeout を超えないよう、初期は `MAX_COORDINATOR_STEPS=8` 程度から本番計測して調整。超過時は finalize 強制。

## 成果物
- agents/watcher/main.py, prompts/system.py, schema.py
- apps/web/src/lib/api.ts, apps/web/src/app/agent/page.tsx
- agents/watcher/tests/test_watcher.py（更新）

## リスク
| リスク | 対策 |
|---|---|
| AgentTool が ADK 2.1.0 で想定と違う | 本番 smoke で早期検証。不可なら専門家を FunctionTool ラッパ化に切替 |
| ループ/タイムアウト | `MAX_COORDINATOR_STEPS` 打ち切り→finalize→`_synthesize`→crew |
| 最終 JSON 崩れ | 二段構え（collected findings を `_synthesize`）|
| 既存クルー回帰 | `_run_crew()` 温存 + flag 既定を crew で段階導入 |
| local genai 破損で unit 不可 | 純粋関数＋fallback はテスト、自律本体は本番 smoke |
