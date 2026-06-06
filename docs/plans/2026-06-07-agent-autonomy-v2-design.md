# 設計: Watcher v2 — 自律型マルチエージェント街選びアナリスト (フル版)

> 作成 2026-06-07 / ステータス: 設計確定(実装未着手) / 対象: 審査基準① 8.5→9+ / 決定: **フルマルチエージェント(A1-A11)**

## 1. Context / 決定
第三者評価の①最大リスク「結局スマートな検索+LLM要約では?」を**構造的に否定**する。
本ハッカソンのテーマ「**マルチエージェント AI**」に直球で当てるため、単一エージェントを
**オーケストレータ + 専門エージェント群 + 批判/反論 + 統合**の多エージェント系へ再設計する。
A1-A11 を全て取り込む(到達点=フル)。ただし7/10へ**段階リリース**(各段で動く状態を維持)。

## 2. アーキテクチャ全体像
```
[Orchestrator / Planner]  (A8 明示プラン + A4 小問分解 + A2 学習した選好を投入)
   │  「住み続ける?移る?」を小問に分解し調査計画を提示
   ▼  並行ディスパッチ (A5 マルチエージェント)
[専門エージェント群]  ※各自 根拠引用(A11)+確信度(A7) 付きで SpecialistFinding を返す
   ├ 人口アナリスト    : fetch_population_trend / fetch_forecast(A6)
   ├ 財政アナリスト    : compare_towns(財政5指標)
   ├ 暮らし・治安      : 所得 / 治安 / 住居(compare_towns 派生)
   └ 議題アナリスト    : search_speeches / fetch_timeline / rag_search_minutes(A6)
   ▼
[Synthesizer]  専門家の findings を統合し TownAnalysis 草案 + verdict
   ▼  反復検証ループ (上限2)
[Critic(A1) + 悪魔の代弁者(A9)]
   ├ Critic: 各主張が引用で裏付くか/見落とした軸はないかを機械+LLMで検証(A11)
   └ Devil's Advocate: 反対結論を主張し弱点を突く
   ▼ needs_revision なら
[Reviser]  不足を追加調査 → 最終 TownAnalysis(confidence 付き)
   ▼
[Post] 前回との差分(A3 変化検知) + 反応を memory へ(A2 学習)
   ▼
[日次 Cloud Run Job(A3/Slice4)]  全ユーザー分を毎朝先回り実行 → discoveries 更新
```

## 3. A1-A11 の配置(全項目の実装箇所)
| 案 | 実装箇所 |
|---|---|
| A1 自己批判 | Critic フェーズ(Draft→Critique→Revise、上限2往復) |
| A2 学習 | reactions/preferences を memory 化し Orchestrator プロンプトへ注入。発見の keep/dismiss を記録 |
| A3 変化検知+先回り | previous analysis 退避 + `diff_against_previous()` + 日次 Cloud Run Job(Slice4) |
| A4 小問分解 | Orchestrator が sub_questions[] を生成し専門家へ割当 |
| A5 マルチエージェント | 4 専門エージェント(ADK sub-agent / AgentTool)を並行実行 |
| A6 ツール拡張 | 既存3 + `fetch_forecast` / `fetch_timeline` / `rag_search_minutes` を追加。各専門家に配賦 |
| A7 確信度 | SpecialistFinding と verdict に `confidence` + `open_questions[]` |
| A8 明示プラン | Orchestrator が研究計画を先に出力 → UI 表示 → 計画対比 |
| A9 悪魔の代弁者 | Critic と並ぶ反論エージェント。両論を Reviser が weigh |
| A10 反実仮想(任意) | verdict に `what_would_change_it`(「小田原が子育て予算+20%で逆転」) |
| A11 引用グラウンディング | 全 claim に `citation`(speech_id/metric/値)必須。Critic が機械的に裏取り |

## 4. ADK 実装方針
- ADK の **ParallelAgent(専門家) → Synthesizer → LoopAgent(Critic+Advocate→Reviser, max_iter=2)** を
  Orchestrator(LlmAgent)が統括。専門家は `AgentTool` か sub-agent として登録。
- **純粋ロジックを ADK I/O から徹底分離**(現行方針継承): `build_plan` / `merge_findings` /
  `critique_analysis` / `arbitrate(draft, critique, advocacy)` / `diff_against_previous` は
  ADK 非依存の純関数 → 全て unit test。ADK 多段は薄いオーケストレーションに留める。
- 専門家は **gemini-2.5-flash**(速・安)、Synthesizer/Critic は flash で十分。コスト最適化。

## 5. データモデル(packages/types or agents/watcher/schema.py)
- `ResearchPlan{ sub_questions: [{q, assigned_specialist}] }`
- `Claim{ text, citation, confidence }` / `SpecialistFinding{ domain, claims[], summary, confidence, open_questions[] }`
- `Critique{ issues[], missing_axes[], grounding_failures[], needs_revision }`
- `Advocacy{ counter_verdict, strongest_points[] }`
- `TownAnalysis`(拡張): + `plan` / `confidence` / `open_questions[]` / `what_would_change_it` /
  `changes_since_last[]` / `agent_trace`(どの専門家が何を調べたか)
- `AgentRunLog`(拡張): specialist 呼出・critique・advocacy のトレース(透明性)
- memory: `user_preferences{ weights, dismissed[], kept_towns[] }`(A2)
- Firestore: `watcher_analyses` に previous 世代保持、`user_preferences` collection

## 6. UI(/agent)への反映
- 「🧭 調査計画」(A8/A4) → 「👥 専門エージェントの所見」(A5、ドメイン別カード+確信度)→
  「⚖️ 検証と反論」(A1/A9 critique・反論の要約)→ verdict。
- 「🔔 前回からの変化」(A3)、「❓ もっと確かにするには」(A7 open_questions)、
  「🔀 何が変われば結論が動くか」(A10)。
- 既存 autonomy-trace を「マルチエージェントの調査過程」へ拡張。

## 7. 倫理・コスト・レイテンシの死守ライン
- 倫理ゲート(forbidden + null言及禁止)は全エージェント最終出力に適用。Advocate も賛否表明はしない。
- **コスト bound**: 専門家4並行 + synth + critic + advocate + revise ≈ 8-10 LLM call。
  ツール上限/エージェント、critique 上限2、token_cost 合算記録。
- **レイテンシ**: 並行化で短縮しても 30-60s 想定 → **「クイック(単一)/ディープ(マルチ)」2モード** or
  日次Jobで事前計算しホームは即表示(オンデマンドは"今すぐ深掘り")。デモは事前実行 + ライブ1回。

## 8. 段階実装(各段デプロイ可能・pytest green 維持)
1. **P1 基盤**: ツール拡張(A6)+ 引用グラウンディング(A11)+ 確信度(A7) を現行単一エージェントに。
2. **P2 検証ループ**: Critic(A1)+ 悪魔の代弁者(A9)→ Reviser(Draft→Critique→Revise)。
3. **P3 マルチエージェント**: 専門家4 + Orchestrator 明示プラン(A5+A8+A4)に再構成。
4. **P4 継続/学習**: 変化検知(A3 diff)+ 学習(A2 memory)+ 反実仮想(A10)。
5. **P5 先回り**: 日次 Cloud Run Job(Slice4)で全ユーザー実行。
- UI(§6)は各段に追随。

## 9. 検証
- 純関数(build_plan/merge_findings/critique_analysis/arbitrate/diff)を unit test(ADK非依存)。
- 実環境 smoke: 専門家が並行起動・critique で再調査・advocate の反論が trace に出ること。
- /agent で 調査計画→専門家所見→検証/反論→結論→変化 が表示。
- pytest 全 green / ruff / CI / コスト・レイテンシ実測。

## 10. リスク
| リスク | 対策 |
|---|---|
| レイテンシ/コスト増(10 call) | 並行化・flash・上限・2モード(quick/deep)・日次事前計算 |
| ADK マルチエージェントの複雑さ・不安定 | 純関数分離 + 薄いADK層。P2(単一+critic)で挙動確証してから P3 |
| 7/10 に間に合わない | 段階リリース。P2 までで「考え直すAI」、P3 で「マルチエージェント」を達成。各段で価値が出る |
| ②④(検証・Veo)が後回しに | 本設計は①特化。②④は別途確保(並行 or 後続)を意識 |
| 「マルチエージェントも演出では?」 | trace に各専門家の tool_calls/引用/確信度を実データで残す(機械検証可能) |
```
