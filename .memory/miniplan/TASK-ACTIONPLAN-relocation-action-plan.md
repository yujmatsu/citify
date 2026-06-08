# ミニプラン: 移住アクションプラン (Relocation Action Plan)

## 概要
- **タスクID**: TASK-ACTIONPLAN
- **目的**: 移住ジャーニーの出口（⑤決断→⑥行動）の穴を埋め、Watcher の分析を「持ち帰れる1枚の行動プラン」に収束させる。Citify だけで移住"判断"が完結する体感を作り、審査基準②（課題アプローチ）④（実用性）を補強。
- **設計**: [docs/plans/2026-06-08-relocation-action-plan-design.md](../../docs/plans/2026-06-08-relocation-action-plan-design.md)（v2・レビュー反映済）
- **完了条件**:
  1. `GET /v1/watcher/{uid}/plan` が最新分析から `ActionPlan` を返す（分析なしは空）
  2. relocate / stay 2モードで `/plan` が正しく描画される
  3. 訪問チェックリストが街固有数値を反映し生成され、倫理スキャンを通る
  4. 公式リンクが seed優先→信頼ポータルfallback で出る（stayは非表示）
  5. localStorage でチェック保持・印刷/コピー（家族共有）が動く
  6. /agent verdict 直下に /plan CTA＋空状態ワンタップ分析
  7. ruff・pytest(agents+api)・tsc・next build がすべて green

## 作業ステップ
1. [ ] **schema**: `ActionPlan`/`OfficialLink` を pydantic で定義。**完了条件: TownAnalysis/WatchVerdict の既存フィールド対応表を `action_plan.py` docstring に明記**（decision_summary←verdict.headline / reasons←推し街assessment.strengths＋verdict.reasoning / open_questions←分析open_questions / mode←recommended_code==home）（レビュー#1）
2. [ ] **N1前倒し検証**: 信頼ポータル(JOIN等)のディープリンク可否を先に確認。**不可でも固定fallback文言でまず通せるよう確定**してから純関数を書く（レビュー#2）
3. [ ] **infra/seed/relocation_links.csv**: デモ主要市の公式移住窓口URLを少数キュレーション（`agents/cost_hunter/seed_loader.py` と同じ `infra/seed` ロードパターン）
4. [ ] **agents/watcher/action_plan.py**: `assemble_action_plan`(純関数・mode判定・reuse)／`construct_official_links`(seed→portal fallback)／`generate_visit_checklist`(ADK `response_mime_type=json`＋`response_schema`、街固有数値投入)／倫理は `agents/_shared/forbidden.py:find_forbidden_matches` 再利用
5. [ ] **apps/api/main.py**: `GET /v1/watcher/{uid}/plan`（`_require_watcher_user` 認可・`get_latest_analysis` 再利用・run_idキャッシュ・graceful）
6. [ ] **api.ts**: `ActionPlanSchema`＋`fetchActionPlan(userId)`＋コピー文面整形を純関数に切出し（レビュー#4）
7. [ ] **apps/web/src/app/plan/page.tsx**: 状態(loading/empty/ok)・行動主役レイアウト・localStorage・印刷/コピー・到達フィードバック
8. [ ] **apps/web/src/app/agent/page.tsx**: /plan CTA＋空状態ワンタップ分析
9. [ ] **tests**: `test_action_plan.py`(純関数・mode判定・seed→portal fallback・ethics・**checklist生成失敗時 visit_checklist=[] で200**、checklistモック)＋API smoke＋コピー整形TS純関数（レビュー#3#4）
10. [ ] **検証**: ruff/pytest/tsc/next build → コミット案提示（人間がpush）

## 成果物
- [ ] backend: schema＋`action_plan.py`＋`/plan` endpoint＋seed CSV
- [ ] frontend: `/plan` ページ＋/agent CTA＋api.ts
- [ ] tests: action_plan 単体＋API smoke
- [ ] 検証ログ（全green）とコミット/デプロイ手順

## 留意（レビュー反映）
- 4つ目の結論を生成しない（Watcher再利用）。①毀損回避＝"エージェントの出口"位置づけ
- 倫理: 中立な検討材料に徹する（処方/投票推奨/政治主体誘導NG）
- BQ変更なし（terraform/load不要）。`agents/**`+`apps/api/**`でAPI自動再デプロイ、日次Jobは本機能を呼ばない
