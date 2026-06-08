# ミニプラン: 前提整理オンボーディング (Onboarding Priorities & Premises)

## 概要
- **タスクID**: TASK-ONBOARDING
- **目的**: ジャーニー入口①「前提整理・自己理解」を埋める。優先順位の重み付け＋制約＋背景を取得し、全機能（Watcher/コンシェルジュ/カルテ/アクションプラン）に一貫反映。
- **設計**: [docs/plans/2026-06-08-onboarding-priorities-design.md](../../docs/plans/2026-06-08-onboarding-priorities-design.md)
- **スコープ**: 意欲版 A〜F（フェーズ P1→P2→P3）
- **完了条件**:
  1. persona に priorities/household/budget_man/area_pref/free_form_context を保持（全省略可・後方互換）
  2. onboarding で上位3順位＋制約＋背景を入力でき、結果サマリーで確認できる
  3. priorities が Watcher プロンプト・コンシェルジュ match_score（重み付け）・ConstraintFilter に反映
  4. カルテのレーダーで優先軸が強調、アクションプランの reasons が優先順
  5. `POST /v1/preferences/extract` が自由記述から構造化抽出しフォームをプリフィル（失敗時手入力）
  6. ruff・pytest(agents+api)・tsc・next build がすべて green

## 作業ステップ

### P1: persona拡張＋onboardingフォーム（LLMなし）
1. [ ] `apps/web/src/lib/persona.ts`: priorities/household/budget_man/area_pref/free_form_context 追加（省略可・後方互換）
2. [ ] `apps/web/src/app/onboarding/page.tsx`: step2に上位3順位UI（タップ順①②③・スキップ可）＋制約入力（予算/家族構成/希望エリア）＋背景自由記述
3. [ ] 結果サマリー（E）: 確認画面「あなたはこういう人ですね」
4. [ ] 送信時に Watcher watchlist / Concierge persona へ新フィールドを含める

### P2: バックエンド反映
5. [ ] `agents/watcher/schema.py` WatchInput に priorities/制約/背景 ＋ `prompts/system.py build_watch_user_prompt` に注入。**新引数は全て末尾・default付き(=None/[])で既存呼出(apps/api)を壊さない**（レビュー#3）。空なら不注入
6. [ ] `apps/api/main.py` WatchlistBody＋_to_watch_input に新フィールド
7. [ ] `agents/concierge`: `_priority_weighted_interest_score`＋`_calc_match_score(priorities)`／`SearchMunicipalitiesArgs.priorities`／**`_execute_tool` で `fc.args` dict に `persona.priorities` をマージしてから model_validate（決定的注入の唯一点。`ConciergeRequest`/runner に priorities を伝播）**（レビュー#2）／ConstraintFilterに予算(max_avg_rent_man)/エリア(prefecture_codes)/family_kids→min_childcare／UserPersonaInputに新フィールド＋プロンプト。※UserPersonaInput.free_form_context は既存(schema.py:239)確認済
8. [ ] カルテ(D, レビュー#1): **`Interest→metric.key` マップを新設**（医療→医療 / 雇用→雇用 / 住居→住まい+持ち家 / 税→財政力+所得。マップ不能なInterestは強調なし=graceful）＋`town-radar.tsx` に `highlightKeys` prop 追加（該当軸を太線/色）。priorities→highlightKeys を渡す経路を新設
9. [ ] アクションプラン(D): reasons/visit_checklist を優先順で並べ替え（action_plan.py、フル動作する確実な部分）

### P3: F（AI抽出）
10. [ ] `agents/preferences/` or 既存流用: extract 関数（軽量 single-agent JSONモード）＋倫理スキャン
11. [ ] `apps/api/main.py`: `POST /v1/preferences/extract`
12. [ ] onboarding ハイブリッド入口（自由記述→抽出→プリフィル→確認）

### 検証
13. [ ] tests（persona/match_score重み/prompt注入/extract parse＋倫理）＋ ruff/pytest/tsc/build → コミット案提示

## 成果物
- [ ] P1: persona拡張＋onboardingフォーム＋結果サマリー
- [ ] P2: Watcher/Concierge/カルテ/プランへの priorities・制約反映
- [ ] P3: extract エンドポイント＋ハイブリッド入口
- [ ] tests＋検証ログ（全green）＋コミット/デプロイ手順

## 留意
- 全フィールド省略可＝完全な後方互換（既存ユーザー・既存挙動を壊さない）
- 倫理: 中立な検討軸。F抽出はユーザー確認必須（AIが決めない）
- BQ変更なし（terraform/load不要）。フェーズ毎に green を保ち、止まっても一貫した塊が残す
