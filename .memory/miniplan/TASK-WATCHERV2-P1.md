# ミニプラン: Watcher v2 P1 — 基盤(ツール拡張 + 引用 + 確信度)

> **⏸️ 中止 (2026-07-02)**: ハッカソン提出 (7/10) 優先のため凍結。P2〜P5 も同様に凍結。
> Watcher の自律性演出は現行 Lv2.5 (プランナー主導 + 並列実行 + 自己検証) で既に成立しており、
> 残り 8 日は提出物 (デモ動画・アーキ図・ProtoPedia) に全振りする判断。**提出後に再開**。

## 概要
- **タスクID**: TASK-WATCHERV2-P1(設計: docs/plans/2026-06-07-agent-autonomy-v2-design.md §8 P1)
- **目的**: マルチエージェント化(P3)の土台として、単一エージェントのまま
  A6(ツール拡張)/ A11(引用)/ A7(確信度)を入れる。
- **完了条件**:
  1. 新ツール `fetch_topic_trend` をエージェントが自律的に呼べる(議題の時系列シグナル)
  2. 各 town_assessment が根拠(source_speech_ids)を持つ + verdict が指標に言及(A11)
  3. verdict / 各 assessment に `confidence` + TownAnalysis に `open_questions[]`(A7)
  4. /agent で確信度バッジ + 「もっと確かにするには」表示
  5. pytest green / tsc / build / ruff

## スコープ
### IN
- ツール拡張 A6: `fetch_topic_trend(municipality_code, interest)` = 月次議題件数の傾向
  (増加/横ばい/減少 + 直近件数)。`meeting_date` 集計で算出。WatcherAgent に登録。
- 確信度 A7: schema に `confidence`(high/medium/low)を verdict と各 assessment に、
  `open_questions[]` を TownAnalysis に追加。prompt で自己評価を要求。
- 引用 A11: prompt で「各 assessment に source_speech_ids 必須」を強調(schema は既存)。
- UI: 確信度バッジ(verdict/各街)+ open_questions セクション。

### OUT(後続P)
- RAG ツール(corpus が国会のみのため見送り)、forecast エンジン本格流用
- マルチエージェント / critic / 変化検知(P2-P5)

## 作業ステップ
1. [ ] `agents/watcher/tools.py`: `fetch_topic_trend` 追加(+ test)
2. [ ] `agents/watcher/main.py` `_build_agent`: tools に登録
3. [ ] `agents/watcher/schema.py`: confidence(verdict/assessment)+ open_questions(analysis)
4. [ ] `agents/watcher/prompts/system.py`: 新ツール説明 + 引用必須 + 確信度/open_questions + JSON例更新
5. [ ] `apps/web/src/lib/api.ts`: confidence / open_questions を schema に追加
6. [ ] UI: verdict-card / town-assessment-card に確信度バッジ、agent page に open_questions
7. [ ] テスト更新(tools/parse)+ 検証(pytest/ruff/tsc/build)

## 成果物
- tools.py / main.py / schema.py / prompts/system.py
- api.ts / verdict-card.tsx / town-assessment-card.tsx / agent/page.tsx
- test_tools.py / test_watcher.py 更新

## リスク
| リスク | 対策 |
|---|---|
| confidence 追加で既存 parse 互換崩れ | デフォルト値付き(medium)で後方互換、parse_analysis は pydantic 任せ |
| topic_trend が議題薄い街で空 | graceful(series 空 + trend="unknown") |
| プロンプト肥大で JSON 崩れ | 例を1つ更新し簡潔に。parse 失敗は既存 graceful(empty) |
