# ミニプラン: Watcher v2 P2 — 自己批判 + 悪魔の代弁者ループ

## 概要
- **タスクID**: TASK-WATCHERV2-P2(設計: docs/plans/2026-06-07-agent-autonomy-v2-design.md §8 P2 / A1+A9)
- **目的**: 「1パス要約」を **Draft → Critique(自己批判)→ Devil's Advocate(反論)→ Revise** に。
  "考え直すAI" を達成し「スマート検索+要約では?」を否定。
- **完了条件**:
  1. 草案生成後に **Critic が根拠/見落としを検証**(A1)、**反論役が反対結論を提示**(A9)
  2. needs_revision の場合のみ **Revise** で最終化(往復上限1)
  3. critique 要約・反論を結果に保持し /agent に「⚖️ 検証と反論」表示(透明性)
  4. コスト bound(critique/advocate/revise 各1回)・倫理ゲートは最終出力に適用
  5. pytest green / ruff / tsc / build

## 設計(単一エージェントのまま、ADK層は薄く)
```
run():
  1. Draft  : 既存のツール使用エージェント → TownAnalysis 草案
  2. Critique: ツール無しの単発エージェント → Critique{issues,missing_axes,grounding_failures,needs_revision}
  3. Advocate: ツール無しの単発エージェント → Advocacy{counter_verdict,strongest_points}
  4. Revise : needs_revision なら 草案+critique+advocacy → 最終 TownAnalysis(上限1往復)
  5. apply_ethics → persist。critique_note / devils_advocate を結果に付与
```
- ADK の単発呼び出しは `_run_single_agent(instruction, message)`(ツール無し Agent を Runner で1回)に集約。
- 純関数を分離: `parse_critique` / `parse_advocacy` / `should_revise` / プロンプトビルダー → unit test。
- run() オーケストレーションは `_run_single_agent` を mock してテスト。

## 作業ステップ
1. [ ] schema: `Critique` / `Advocacy` + TownAnalysis に `critique_note: str` / `devils_advocate: str`
2. [ ] prompts: `CRITIC_PROMPT` / `ADVOCATE_PROMPT` / `build_revise_prompt`
3. [ ] main.py: `parse_critique` / `parse_advocacy` / `should_revise`(純関数)
4. [ ] main.py: `_run_single_agent` ヘルパー + run() を draft→critique→advocate→revise に再構成
5. [ ] UI: /agent に「⚖️ 検証と反論」セクション(critique 要約 + 反論)
6. [ ] api.ts: critique_note / devils_advocate を schema 追加
7. [ ] テスト(parse/should_revise/run orchestration mock)+ 検証

## リスク
| リスク | 対策 |
|---|---|
| LLMコール増(draft+critique+advocate+revise=最大4) | revise 上限1、critique/advocate は単発(ツール無し)で軽量、token_cost 合算記録 |
| ADK 単発呼び出しの不安定 | _run_single_agent に集約・例外時は draft をそのまま採用(graceful) |
| revise で一貫性が崩れる | revise は「critique で指摘された点のみ修正」と明示、最終出力も倫理/parse ゲート通過 |
| テスト不能(実ADK) | 純関数 + _run_single_agent mock でオーケストレーション検証、実挙動は smoke |
