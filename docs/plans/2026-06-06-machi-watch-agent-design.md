# マイ街エージェント設計 — 自律型 Civic Watch Agent

> 作成: 2026-06-06 / ハッカソン提出: 2026-07-10 / ステータス: 設計合意済、Slice 1 着手前

## 1. 背景と戦略転換

第三者評価(厳しめ、7.4/10)で最弱だったのが審査基準①「AIエージェントが価値の中心か」(7.0)。
現状は LLM-in-pipeline / 純計算+ナレーター型が多く、**自律性・エージェントの必然性が弱い**。
また課題「若者の政治無関心 → 60秒翻訳」は政治レイヤーがシステム上弱い。

### 戦略転換(合意済)
- **課題を「自分の街・気になる街を知る/選ぶ」に振り切る**(政治翻訳は1レイヤーに格下げ、捨てない)
  - 人口減少時代に、住む街/移り住む街を"自分ごと"として知り・選び続けるのは情報過多で困難
  - 対象: 住民(知り続ける)+ 移住検討者(選ぶ)を「**ウォッチ街リスト**」で一元化(C軸)
- **自律エージェントを作品の中核に据える**(①を 7→9 へ。最重量配点を直接改善)

### スコア予測(良好実装時)
① 7→9 / ② 7.5→8.5 / ③ 7→8 / ④ 7→8(Veo追加で8.5+) / ⑤ 8.5維持。総合 7.4 → **8.4〜8.7**。

## 2. プロダクト構造(3層 IA、③解決)

```
Tier1 ヒーロー: マイ街エージェント・ホーム(新規・モバイルファースト)
   Push: エージェントの発見フィード(理由付き) / Pull: 対話深掘り(既存Concierge流用)
Tier2 ウォッチ街: 街カルテ(cities/[code] 強化、人口推移2000-2070 + 統計 + 発見)
Tier3 道具: ヒートマップ/比較/タイムライン/予測(トップ動線から外し文脈内到達)
管理: admin/* は分離
```
原則: **バックエンドは全再利用、新規はフロント面 + エージェント・オーケストレーション層のみ**。

## 3. エージェント設計(①の本体)

ADK `LlmAgent` の**自律プランナー**。ツール群を渡され、**呼ぶ順番・回数・深さを自分で判断**。

### 自律ループ Perceive–Judge–Plan–Act–Learn
1. **Perceive**: watch街の新着議題/プレス/統計更新を取得(コンテキスト投入)
2. **Judge/Plan/Act**: LLM が以下ツールを**自分で選択**し、重要性判断 → 深掘り調査 → surface 要否決定
3. **Learn**: discoveries への反応(status)を memory に蓄積、次回 Judge に反映

### ツール群(既存資産を関数として渡す)
| tool | 中身(既存) |
|---|---|
| search_speeches(code, interests) | BQ scored_speeches |
| fetch_city_stats(code) | municipality_stats |
| fetch_population_trend(code) | municipality_population_series |
| compare_towns(codes[]) | comparator |
| recall_user_memory(user_id) | concierge memory |

### 自律性の死守ライン
- LLM にツール選択を委ねる(**スクリプト化禁止**)。Concierge の tool-calling 実績を発展
- コスト bound: watch街上限5・ツール呼出上限・relevance cache
- 倫理: Discovery 出力に既存 forbidden-pattern 検証(政治的断定なし)

## 4. 状態モデル(Firestore)

- `user_watchlist` (user_id): home_municipality_code, watched_codes[]≤5, age_group, interests[]
- `discoveries` (auto): user_id, municipality_code, title, summary[], **why_surfaced**(差別化の核),
  significance, source_speech_ids[], related_refs, status(new/seen/dismissed), agent_run_id, created_at
- `agent_runs` (run_id): user_id, towns_checked[], **tool_calls[]{tool,args,why}**(①の自律証跡), token_cost, status
- memory: 既存 `concierge_history` 拡張流用

差別化の核 = `discoveries.why_surfaced`(「なぜあなたに」)+ `agent_runs.tool_calls`(自律計画の証跡)。

## 5. Push/Pull

- **Push(ヒーロー)**: 日次 Cloud Run Job が全ユーザー分エージェント実行 → discoveries 生成・保存
- **Pull(最小)**: 既存 Concierge を街コンテキスト付きで流用。新規対話エンジンは作らない

## 6. MVP スコープ

### IN
ADK自律プランナー / 判断理由可視化 / watch-list状態 / Push日次 / エージェントホーム(新規・モバイル) /
既存ツール再利用 / 倫理ゲート / コスト bound

### OUT → Phase 2+ バックログ(優先度順、捨てない)
- **P1**: Veo/Imagen(④の天井を 8.0→8.5+。唯一スコアを抑える OUT 項目)
- P2: Push通知(メール/Push)、Pull深掘りの本格化
- P3: リアルタイム/イベント駆動、高度Learn、旧ページ整理/移行、onboarding磨き

### 退路
/feed と全既存ページは生かしたまま、新ホームは追加。デフォルト入口切替は新ホーム安定後。

## 7. 実装シーケンス(縦切り → 横展開)

- **Slice 1(自律性の証明)**: 1ユーザー × watch街1 × ツール2(search_speeches+population_trend)で、
  ADKエージェントが自分でツールを選び Discovery 1件を why_surfaced 付きで生成 → Firestore。e2e。
- **Slice 2**: ツール全部 + 複数街 + コスト bound + 倫理ゲート + agent_runs 記録
- **Slice 3**: エージェントホーム(新規フロント、モバイルファースト)+ watch-list onboarding
- **Slice 4**: Push 日次 Cloud Run Job 化
- **並行**: ⑤ pytest CI gate(GitHub Actions)、②④ ユーザー検証3-5名

## 8. リスクと対策

| リスク | 対策 |
|---|---|
| 自律の偽装(スクリプト化) | Slice 1 で ADK tool-planning を先に証明。スクリプト化を早期検知 |
| スコープ爆発/締切 | MVP厳守 + 既存を退路 + 縦切り |
| コスト/quota(429既往) | watch街上限・ツール上限・relevance cache |
| ただのデータ集約批判 | why_surfaced / tool_calls の可視化で差別化 |
| 課題の未検証 | ユーザー検証3-5名を並行 |
