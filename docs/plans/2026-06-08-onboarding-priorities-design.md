# ジャーニー入口① 前提整理オンボーディング 設計 (Onboarding: Priorities & Premises)

- 作成日: 2026-06-08
- ステータス: 設計確定（実装前）
- 目的: 移住ジャーニーの入口①「前提整理・自己理解」の穴を埋める。迷う人が「何を一番重視するか／前提条件は何か」を一度言語化し、その結果を全機能（Watcher / コンシェルジュ / 街カルテ / アクションプラン）に一貫反映する。
- スコープ: **意欲版 A〜F 全部**（重み付け＋制約＋背景＋全機能反映＋結果サマリー＋AI抽出）

## 背景

ジャーニー分析で①前提整理が最弱と判明。現状 onboarding は 年代／関心軸(フラット)／街 のみで、「何を重視するか」「予算・家族構成などの前提」を捉えていない。コンシェルジュには `ConstraintFilter` の受け皿が既にあるのに onboarding で取れていない。本機能で①を埋め、審査基準②課題アプローチ・③ユーザビリティを補強。

## 決定事項（brainstorming で確定）

| 論点 | 決定 |
|---|---|
| 重みの用途 | **プロンプト反映（全機能）** ＋ コンシェルジュ match_score の決定的重み付け |
| 重みの入力 | 選択済み関心軸から**上位3つを順位付け**（スキップ可） |
| スコープ | A〜F 全部（フェーズ P1→P2→P3） |
| 入口 | フォーム＋AI抽出のハイブリッド（F、human-in-the-loop で必ず確認） |

## 要素 A〜F

| 要素 | 内容 |
|---|---|
| A | 優先順位の重み付け（上位3順位） |
| B | 制約・前提（予算・家族構成・希望エリア） |
| C | 移住の背景・動機（自由記述、`free_form_context` 活用） |
| D | 重みをカルテ（レーダー優先軸強調）／アクションプラン（reasons並べ替え）にも反映 |
| E | onboarding 結果サマリー（自己理解の payoff） |
| F | AI が自由記述から前提を抽出しフォームをプリフィル |

## 1. persona 拡張（後方互換・全フィールド省略可）

```
priorities: Interest[]          # A: 上位3順位 (interests の部分集合)
household: "single"|"couple"|"family_kids"|"other" | null   # B
budget_man: number | null       # B: 上限 → ConstraintFilter.max_avg_rent_man
area_pref: string[]             # B: 希望都道府県コード → prefecture_codes
free_form_context: string       # C: 背景 (UserPersonaInput に既存枠)
```
空＝完全な現状維持（フラット挙動）。

## 2. onboarding（ハイブリッド入口）

1. 入口で2択: 「状況を文章で話す（AIが整理）」 or 「自分で選ぶ（フォーム）」。
2. **F（AI抽出）**: 自由記述 → `POST /v1/preferences/extract` が `{priorities, interests, budget_man, household, area_pref, background_summary}` を JSON で返し、フォームを**自動プリフィル**（必ず確認・編集可）。
3. フォーム: 年代／関心軸＋上位3順位（A）／予算・家族構成・希望エリア（B）／背景（C）。
4. **E. 結果サマリー**: 「あなたはこういう人ですね（医療最重視・子育て世帯・予算◯◯万・神奈川希望）」を確認画面で提示。

倫理: F抽出はユーザーが必ず確認（AIが決めない）。

## 3. バックエンド配線（全機能反映・D含む）

| 反映先 | priorities(A) | 制約(B) | 背景(C) |
|---|---|---|---|
| Watcher | `build_watch_user_prompt` に重視順を注入（specialist/synth/verdict/アクションプランに伝播） | 予算/家族/エリアを context 行に | 背景を context 行に |
| コンシェルジュ | `match_score` の優先順位重み付け＋プロンプト | `ConstraintFilter`（既存）に予算/エリア、family_kids→min_childcare | プロンプト |
| 街カルテ(D) | レーダーで優先軸を強調（太線/色） | — | — |
| アクションプラン(D) | reasons/visit_checklist を優先順で並べ替え | — | — |

**match_score 重み付け（決定的）**: `_priority_weighted_interest_score(matched, priorities)` = マッチ軸に順位加点（①30/②20/③15/順位外8、上限50clamp）。priorities 空なら既存件数ベース（25/40/50）にフォールバック。`SearchMunicipalitiesArgs.priorities` を追加し **dispatch 層（runner）で persona から決定的に注入**（LLM 依存にしない）。

**F: 抽出エンドポイント** `POST /v1/preferences/extract {text}` → 軽量 single-agent（JSONモード）で構造化抽出。倫理スキャン適用。失敗時は空（フォーム手入力にフォールバック）。

## 4. フェーズ（止まっても一貫した塊が残る順）

- **P1**: persona拡張＋onboardingフォーム（A優先順位＋B制約＋C背景＋E結果サマリー）＝LLMなしで完結・即価値
- **P2**: バックエンド反映（Watcher prompt / Concierge match_score重み付け＋ConstraintFilter / カルテレーダー強調 / プラン並べ替え）
- **P3**: F（AI抽出エンドポイント＋ハイブリッド入口）＝上積み

## 5. 倫理・エッジ・テスト

倫理: priorities/制約は中立な検討軸（政治的判断でない）。F抽出はユーザー確認必須。背景の自由記述は最小保存。

エッジ: 全フィールド省略可→現状維持（後方互換）。Interest外の軸はサニタイズ。F抽出失敗→手入力フォールバック。priorities が interests のサブセットでなければ除去。

テスト: persona拡張 schema／`_priority_weighted_interest_score`・`_calc_match_score`（priorities重み）／`build_watch_user_prompt` 注入（空なら不注入）／extract の JSON parse＋倫理スキャン／tsc・build。

検証ゲート: ruff・pytest(agents+api)・tsc・next build。

## デプロイ

- `agents/**`＋`apps/api/**`＋`apps/web/**` 変更 → API 自動再デプロイ＋web デプロイ。BQ 変更なし（terraform/load 不要）。
- 日次Job(workers) は本機能を呼ばないため再ビルド不要（priorities は watchlist に保存され run 時に効くが、Job 反映は workers 再ビルド時）。

## スコープ外（バックログ）

- 通勤先の実距離計算（commute_to のスコア化）→ 今回は context/エリア希望に留める
- priorities の継続的な見直し導線（設定画面）→ onboarding 再実行で代替
