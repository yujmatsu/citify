# ミニプラン: Watcher v2 P4 — 変化検知(A3) + 学習/継続性(A2)

## 概要
- **タスクID**: TASK-WATCHERV2-P4(設計 §8 P4 / A3+A2)
- **目的**: "計算機→見張る存在"。前回分析との差分を surface(A3)+ 前回結論を踏まえた継続判断(A2)。
- **完了条件**:
  1. 前回分析との差分(推し街変更/各街fit_score増減)を `changes_since_last` に格納し /agent 上部に「🔔前回からの変化」表示
  2. Synthesizer が前回の結論を踏まえる(状況が変われば反映、変わらなければ一貫性維持)= 継続性
  3. 初回(前回なし)は変化なしで graceful、pytest green / tsc / build

## スコープ
### IN
- A3: `diff_against_previous(prev, cur, town_names)` 純関数 → list[str](街名で表現)。
  run() で persist 前に `repo.get_latest_analysis`(=前回)を取得し diff、`changes_since_last` に付与。
- A2(継続性): 前回 verdict を `_synthesize` の文脈に渡し、Synthesizer が継続性を踏まえる。
- schema: TownAnalysis に `changes_since_last: list[str]`。UI バナー + api.ts。
### OUT(後続)
- A2 反応学習(dismiss/keep→重み)は UI/endpoint が要るため P4b/後続。A10 反実仮想も後続。

## 作業ステップ
1. [ ] schema: `TownAnalysis.changes_since_last: list[str]`
2. [ ] main.py: `diff_against_previous` 純関数(推し街変更・fit_score増減・推奨確信度変化)
3. [ ] main.py run(): persist前に prev取得 → diff付与 / `_synthesize` に prev_verdict 文脈
4. [ ] prompts: SYNTHESIZER に「前回結論」考慮の一文 + build_synth_prompt に previous 引数
5. [ ] UI: /agent 上部「🔔 前回からの変化」 + api.ts changes_since_last
6. [ ] テスト(diff_against_previous)+ 検証

## リスク
| リスク | 対策 |
|---|---|
| 差分が文言ゆらぎで誤検出 | 構造化フィールド(recommended_code/fit_score)中心、文言比較はしない |
| prev取得の追加I/O | doc直接取得(既存get_latest_analysis)で軽量。repo無し(smoke)はskip |
| 継続性で前回に固執しすぎ | プロンプトで「状況が変われば必ず反映」と明示 |
