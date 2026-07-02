# ミニプラン: 財政指標の取り込み (街選びアナリストの判断軸拡充)

> **⏸️ 中止 (2026-07-02)**: ハッカソン提出 (7/10) 優先のため凍結。
> 新規データパイプライン一式 (取込→正規化→Terraform列→テスト) は審査員に見えない改善であり、
> 残り 8 日はデモ動画・アーキ図・ProtoPedia 登録・審査員動線の防御に全振りする判断。
> **提出後に再開**。設計・データソース調査 (SSDS) は下記の通り完了済みなので再開コストは低い。

## 概要
- **タスクID**: TASK-FISCAL
- **目的**: マイ街エージェント(街選びアナリスト)の結論精度を上げるため、自治体の
  「財政の体力」を `municipality_stats` に取り込み、`compare_towns` の比較軸に加える。
- **背景**: 実機FBで「結論に財政状況など取り込めると良い」と要望。現状データには財政指標が無い。
- **完了条件**:
  1. `municipality_stats` に財政指標列が入り、**対象自治体マスタ(国会/集計行除く)の 70% 以上が非null**
     (#3: 移住候補が欠損だと比較が破綻するため最低カバレッジ閾値を設定)
  2. `compare_towns` が財政指標を返す(値が無い街は null を明示)
  3. Watcher が verdict/assessment で財政に言及できる(プロンプトに軸追加)。
     **ただし財政データが null の街では財政軸に言及しない**ガードを明記(#4: 誤断定=倫理リスク回避)
  4. 取り込みスクリプト + seed CSV + Terraform列 + テストが揃い、pytest green
  5. 数値の出典(公表年度・URL)を保持(倫理・透明性)

## スコープ (80/20)
単一データセット(すがた)なので 2指標でも5指標でも取り込みコストはほぼ同じ。
そこで「財政の体力 + 暮らしの豊かさ + 治安」を1スライスで取り、街選び結論の説得力を底上げする。

### IN — MVP 推奨指標(すがた由来、現状未保有)
| 列名 | 指標(すがた分野) | 意味 | 型 |
|---|---|---|---|
| `financial_capability_index` | 財政力指数(D行政基盤) | 1.0超で財政的余裕。街の体力の代表値 | FLOAT |
| `real_debt_service_ratio_pct` | 実質公債費比率(D) | 借金の重さ(高いほど硬直) | FLOAT |
| `taxable_income_per_capita_yen` | 1人当たり課税対象所得(C経済基盤) | 住民の所得水準=暮らしの豊かさ | INTEGER |
| `homeownership_rate_pct` | 持ち家比率(G居住) | 定住度・住まいの安定 | FLOAT |
| `crime_rate_per_1000` | 刑法犯認知件数(人口千対)(J安全) | 体感治安 | FLOAT |
| `ssds_data_year` | 公表年度 | 出典年度(指標別の年度差は非ゴール、公表年度で統一) | INTEGER |
| `ssds_source_url` | 出典URL | e-Stat / 総務省統計局 | STRING |
| `ssds_loaded_at` | ロード時刻 | メタ | TIMESTAMP |

※ **ユーザー決定: 上記5指標で確定**(2026-06)。SSDS同梱のため5指標でも取込コストは小。
※ 着手タイミング: **街名修正のデプロイ確認後**に開始。

### OUT (将来) — 事業所数/従業者数(雇用基盤)、空き家率、学校数、将来負担比率/ラスパイレス指数。
同一データセットなので MVP安定後に列追加するだけで拡張可能。

## データソース方針 (2026-06 e-Stat 実地調査で確定)
**第一ソース = 「統計でみる市区町村のすがた」(社会・人口統計体系 SSDS)**。理由:
- 財政力指数(D2201, D行政基盤)を市区町村別・**市区町村コード付き**で収録(区/特別区の名寄せ不要)
- 財政以外の判断軸(経済基盤C・居住G・安全J 等)も**同一データセット**に含む = 1回のパースで多軸取得
- 最新2025年版(公開2025-06-20)、**Excel(基礎データ)** + e-Stat DB + API(statsCode)
- 取得経路: (a) すがた「基礎データ」Excel をDL→パース(既存 xlsx パース資産を流用、推奨) /
  (b) e-Stat API `getStatsList(statsCode=社会人口統計体系)` → `getStatsData`
- フォールバック: 元データ「地方財政状況調査」(toukei=00200251) — より詳細だが複雑。すがたで不足する項目のみ。
- 正規化 → `infra/seed/ssds_indicators_normalized.csv` (列は下記 MVP 指標 + municipality_code,
  fiscal_data_year, fiscal_source_url)。

### 取得可否 (確認済)
✅ 財政力指数の市区町村別データは e-Stat / すがた に実在・DL可能。年度は3か年平均表記(例: 令和6年度=「4〜6年度」)。

### ステップ0 調査結果 (2026-06 確定)
- **政府統計コード(statsCode/toukei) = `00200502`**(社会・人口統計体系)
- 2025基礎データ: `lid=000001460868` / `tstat=000001229545` / `tclass1=000001229546`(2025-06-20公開)
- **5指標の所在分野**(SSDS 分野記号): 財政力指数・実質公債費比率=**D 行政基盤** / 1人当たり課税対象所得=**C 経済基盤** / 持ち家比率=**H 居住** / 刑法犯認知件数=**K 安全**
- API手順: `getStatsList(statsCode=00200502)` → 「市区町村 基礎データ ○分野」の statsDataId 特定 →
  `getMetaInfo` で cdCat01 項目コード確認(財政力指数=D2201系 等) → `getSimpleStatsData(cdCat01, cdArea)`。
- **残る要確定(ESTAT_APP_ID 必須・実環境)**: 各分野の正確な statsDataId と各指標の cdCat01 項目コード。
  → ステップ1 で getStatsList/getMetaInfo の生応答を確認して pin する。
- 取得経路: (A) 分野別Excel(C/D/H/K)をDL→パース(推奨・安定) / (B) API。どちらも可。
- 注記: 1人当たり課税対象所得は「課税対象所得 ÷ 納税義務者数(所得割)」で算出する派生指標。

## 作業ステップ
0. [ ] **【着手前・タイムボックス調査 30分】データソース実在性の確定**(#1: 本タスク最大の不確実性)
   - `fetch_estat_api list --search-word "地方財政状況調査 財政力指数"` で市区町村別 statsDataId を探す。
   - **判断分岐**:
     - e-Stat に市区町村別がある → e-Stat 採用
     - e-Stat 不可 → 総務省「財政状況資料集」CSV をフォールバック採用
     - 両方とも単一ファイルで市区町村別が揃わない → **MVP指標を「財政力指数」1本に縮退**して続行
   - この調査結果を miniplan に追記してから次へ進む(空振りなら指標縮退 or 一旦保留の判断)。
1. [ ] **データ特定**: ステップ0で決めたソースの statsDataId / CSV を確定。
2. [ ] **取得・正規化**: 取得 → `infra/seed/ssds_indicators_normalized.csv` 生成
   (政令市の区・特別区・都道府県集計行・国会00000 は対象外。市区町村コードで正規化)。
3. [ ] **Terraform**: `infra/env/dev/main.tf` の municipality_stats schema array に上記5列を追加
   (terraform fmt 必須)。
4. [ ] **Loader**: `apps/api/scripts/load_ssds_stats.py` を新規作成。
   `load_reinfolib_stats.py` の MERGE UPDATE パターンを踏襲(既存列を保護、財政5列のみ更新)。
5. [ ] **BQ投入・検証**: 実行 → 主要自治体(朝霞/小田原/新宿等)で値が入ることを確認。
6. [ ] **エージェント連携**:
   - `agents/watcher/tools.py` `compare_towns` の SELECT/返却に財政2指標を追加(値が無い街は null 明示)。
   - `agents/watcher/prompts/system.py` に「財政力指数=街の体力、経常収支比率=財政の硬直度」の軸を追記。
     **+ 財政データが null/不明の街については財政に言及しない**ガードを1行追記(#4: 倫理)。
   - (任意) `apps/api/main.py` CityDashboard `MunicipalityStats` schema + api.ts に列追加。
7. [ ] **テスト**(#5: 除外ロジックを最重要テスト対象に明示):
   - 正規化: **政令市の区行・特別区・集計行・00000 が除外される**こと、財政力指数の数値型パース(全角/欠損/"-"の扱い)。
   - `compare_towns`: 財政列が返ること、欠損自治体で null になること。
   - pytest agents apps/api green。
8. [ ] **検証**: ruff/pytest/(必要なら)実BQ。terraform fmt。

## 成果物
- [x] `apps/api/scripts/fetch_ssds_indicators.py` (e-Stat 取得・list/meta/fetch、経路B)
- [x] `apps/api/scripts/ssds_config.json` (statsDataId/cat01 確定: D2201/D2211/C120110/C120120/H1310/H1101/K4201/A1101)
- [x] `infra/seed/ssds_indicators_normalized.csv` (fetch 出力、1911市区町村、カバレッジ 財政89%/公債費91%/所得91%/持ち家68%/治安99%)
- [x] `infra/env/dev/main.tf` (財政5列 + メタ3列追加、fmt OK)
- [x] `apps/api/scripts/load_ssds_stats.py` (+ test、dry-run 1911行OK)
- [x] `agents/watcher/tools.py` compare_towns 拡張 (+test) / `prompts/system.py` 軸+nullガード追記

## 残 (ユーザー実環境)
- [ ] commit/push → terraform apply (列追加) → load_ssds_stats (BQ MERGE) → /agent 再分析で財政反映確認
- [ ] `agents/watcher/tools.py` compare_towns 拡張 (+ test更新)
- [ ] `agents/watcher/prompts/system.py` 財政軸追記
- [ ] (任意) CityDashboard 表示連携

## リスクと対策
| リスク | 対策 |
|---|---|
| e-Stat API に市区町村別財政力指数が無い | 総務省「財政状況資料集」CSV手動DLにフォールバック(ステップ1で早期判定) |
| 政令市の区・特別区のコード不一致 | 市/特別区単位で正規化、municipality_master.csv と突合 |
| データ年度が人口統計と揃わない | `fiscal_data_year` を別列で保持し、UIで年度明記 |
| BQ実書込はsandbox不可 | loaderの純ロジックはunit test、BQ投入は実環境で実行 |
| スコープ膨張 | MVPは5指標厳守。残り(雇用基盤/空き家/学校等)はOUTでバックログ |

## 非ゴール
- 財政の予測・時系列(まずは最新1年のスナップショット)
- 全分野網羅(5指標で「財政の体力 + 暮らしの豊かさ + 治安」を表現)
