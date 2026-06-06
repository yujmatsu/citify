# 設計: 情報設計(IA)整理 + 街カルテ強化(e-Stat風) + Concierge 再配置

> 作成 2026-06-07 / ステータス: 設計(実装未着手) / 対象審査基準: ③ 8.0→8.5, ② 補強

## 1. Context / 問題
- 共通ナビが無く、ランディング(/)が**13ページのリンクハブ**化 → 焦点がぼやける(③の弱点)。
- `/cities/[code]` は人口推移+統計カード+上位議題があるが**グラフが控えめ・財政5指標未表示**。
  ユーザーへの「刺さり」が弱い(参考: e-Stat 地域ダッシュボードの時系列・全国比較の見せ方)。
- `/concierge`(676行)は街診断の対話だが、現データ(財政・将来人口)に未整合で立ち位置が曖昧。

## 2. 目標
保有データ(人口2000-2070・財政5指標・年齢構成・子育て/医療・住居)を**街カルテで魅せ**、
**3層IA**で動線を整理。Concierge をエージェントの補助に再配置する。

## 3. 3層 IA(動線整理)
```
Tier1 ヒーロー : マイ街エージェント (/agent)          ← 既存・主役
Tier2 街カルテ : /cities/[code] (e-Stat風に強化)      ← 本設計の中心(D)
Tier3 道具     : compare / heatmap / timeline / forecast ← トップから降格、文脈内リンクで到達
補助           : concierge (対話深掘り) / feed (議題フィード) / municipalities (登録)
管理           : admin/* は分離維持
```
- **共通ナビ追加**: モバイル下部タブ(エージェント / フィード / 街さがし / 設定)を `layout.tsx` に。
  現状 page.tsx のリンク列挙は「もっと見る/道具箱」セクションに集約しトップを軽量化。
- 街カルテ・エージェントの各街から Tier3 道具へ「この街で深掘り(比較/タイムライン/予測)」リンク。

## 4. 街カルテ強化(D / e-Stat ダッシュボード風)
`/cities/[code]` を「街の輪郭が一目で分かる」ダッシュボードへ。**自前SVG(依存追加なし)**で構築。

| セクション | 内容 | データ源(既存) |
|---|---|---|
| ヘッダー | 街名・県・人口規模・将来人口サマリ | stats / population_series |
| 人口推移 | 2000-2070 折れ線(実績+推計) | PopulationTrendChart(既存) |
| 年齢構成 | 若者/生産/高齢の構成バー or ドーナツ + 全国平均比 | youth/elderly_share_pct |
| **暮らし・財政レーダー** | 6軸(財政力/所得/将来人口/治安/財政健全度/持ち家)単一市版 + 全国50%基準線 | compare-stats(codes=単一) |
| **全国/県平均 比較バー** | 主要指標を全国・県中央値と横並び棒(e-Stat の比較体験) | 新規: 全国/県集計(compare-stats の national を流用拡張) |
| キー指標カード | 人口/所得/住居価格/子育て/医療 等 | stats(既存カード + 財政追加) |
| 直近の議題 | 上位 N(既存) | scored_speeches |

実装の肝:
- `MunicipalityStats`(api.ts) と CityDashboard API schema に **財政5指標を追加で公開**
  (現在 Terraform/BQ には在るが API 未露出)。
- レーダーは `compare-stats?codes=<1市>` を再利用(単一市 + 全国50線)。
- 「全国/県平均比較」は compare-stats の national 配列(中央値)を返すよう小拡張、または専用集計。
- グラフは ForecastChart/PopulationTrendChart と同じ自前SVG流儀で新規コンポーネント
  (`age-structure-bar.tsx`, `benchmark-bars.tsx`)。

## 5. Concierge 再配置(C)
- 立ち位置: 「**エージェントの結論を対話で深掘り**」する補助。エージェントホーム/街カルテから起動。
- 現データ整合: 候補提示カード(MunicipalityCandidate)に **財政力・将来人口・所得** を追加表示。
  プロンプト/ツールを現 municipality_stats(財政含む)に合わせて更新。
- トップからは降格(Tier3/補助)。エージェントの verdict 文脈を引き継いで起動できると理想
  (例: 「小田原の人口減少をもっと知りたい」→ concierge に街+論点を渡す)。

## 6. スコープ
- **IN**: (B1) 共通ナビ + トップ整理、(B2) 街カルテ強化(財政露出 + 年齢構成 + 単一市レーダー +
  全国/県比較バー)、(B3) concierge 候補カードに財政/将来人口追加 + 立ち位置調整
- **OUT(後続)**: concierge への verdict 文脈引き継ぎ、Tier3 道具の全面再設計、ダークモード微調整、
  旧ページの物理削除(まずは動線降格のみ・退路維持)

## 7. 段階実装(縦切り、各段で tsc/build green)
1. **B2a**: `MunicipalityStats` schema + CityDashboard API に財政5指標を追加(露出のみ)
2. **B2b**: 街カルテに財政キー指標カード + 単一市レーダー(compare-stats 再利用)
3. **B2c**: 年齢構成バー + 全国/県平均比較バー(新規SVG + national 集計拡張)
4. **B1**: 共通ナビ(モバイル下部タブ)+ トップ(/) 整理
5. **B3**: concierge 候補カード拡張 + 立ち位置文言

## 8. 検証
- API: compare-stats / cities が財政指標を返す(curl)。national 集計の妥当性。
- tsc --noEmit / next build green、モバイル幅(375px)で街カルテ目視。
- pytest(API schema 変更分)green / ruff / CI。

## 9. リスク
| リスク | 対策 |
|---|---|
| データ品質(医療4909件等)が街カルテで目立つ | 露出前に scale 修正 or 該当指標は注記/非表示。財政・人口・所得は信頼可 |
| スコープ膨張(7/10) | B2(街カルテ)を最優先、B1ナビは軽量実装、B3は最小。Tier3再設計はOUT |
| 自前SVGグラフの工数 | 既存 PopulationTrendChart/TownRadar を流用、新規は age-structure/benchmark の2つに限定 |
| 旧ページ削除で回帰 | 物理削除はせず動線降格のみ(退路維持) |
```
