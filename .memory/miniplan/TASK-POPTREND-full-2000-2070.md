# ミニプラン: 人口推移グラフ (フル: 過去2000-2020 + 将来2025-2070) — TASK-POPTREND

## 概要

- **タスク ID**: TASK-POPTREND
- **目的**: 各街の **人口推移 (過去 2000〜実績 2020 → 将来予測 2070)** を簡単なグラフで可視化し、
  「あなたの街は 2050 年に何 % 減るか」を若者向けに体感させる。XKT013 の SHICODE 修正
  (TASK-POPFIX フォローアップ) と e-Stat 国勢調査の時系列ロードを組み合わせる。
- **ユーザー承認**: スコープ「フル: 過去2000-2020 + 将来2025-2070」を選択済
- **完了条件**:
  - XKT013 が **SHICODE で自治体絞り込み**して 2020-2070 を正しく集計 (50km box 合算バグ解消)
  - e-Stat 国勢調査 2000/2005/2010/2015/2020 を現行境界 (組替) で取得・格納
  - 1 自治体の人口時系列 (過去実績 + 将来予測) が API で取得できる
  - city ダッシュボードに人口推移グラフ (実績=実線 / 予測=破線) が表示される
  - 倫理: AI 生成でない客観統計 (出典: 総務省国勢調査 / 国交省将来推計) を明記
- **想定工数**: 大 (6-9h、データ fetch 待ち含む)。**2 段リリース** (Reviewer High#2):
  - **Stage 1 (初回, 4-5h)**: 将来カーブ 2020→2070 のみ (XKT013)。合併リスクゼロ、「2050 に何 % 減るか」体験が完成
  - **Stage 2 (後続 v0.6)**: 過去 census 2000-2020 を延伸 (e-Stat、合併境界処理)
  - フルスコープは維持しつつ、価値の核 (将来) を先に出荷する

## 前提・ブロッカー

| 依存 | 状態 | 必要アクション |
|---|---|---|
| `REINFOLIB_API_KEY` | env になし (.env 管理?) | Phase 0 で所在確認。XKT013 検証 + 再fetch に必須 |
| e-Stat `appId` (API key) | 既存 e-Stat ロード実績あり → どこかに存在 | prep_estat 系の取得方法を踏襲 |
| XKT013 PT00 実在年次 | 公式は "PT00_20XX" 汎用記法 | Phase 0 の live call で 2020/2025/.../2070 を確定 |
| 1889 自治体 再fetch | API quota + 時間 | ユーザー実行 (キー必要)。バッチ + rate limit |

## Phase 0 検証結果 (2026-05-31 実施、確定)

| 項目 | 結果 | 設計への反映 |
|---|---|---|
| PT00 年次 | **2025〜2070 の5年刻み (10点)**。2020 基準年なし | 将来カーブ = 2025-2070。現在の anchor は e-Stat 2015/2020 を流用 |
| HITOKU | HITOKU2025〜2070 (年次連動) | 動的検出で対応済 |
| SHICODE フィルタ | ✅ 正確 (新宿 357,971 / 高山 77,198 = 実人口相当)。2870倍バグ解消 | parser 完成 |
| 政令市 (札幌01100) | ⚠️ メッシュ SHICODE は**区コード(01102等)**、親01100 は存在しない | parser を **区コード集合の合算**に対応済 (targets の city_sum 範囲を使う) |
| 広域カバレッジ (高山) | radius=1: 1737メッシュ → radius=2: 1910 (**+1.7%**、減少率の形は同一) | **radius=1 採用** (形は正確、絶対値~98%、4.7h)。caveat 明記 |

**Stage 1 のデータ構成 (確定)**: e-Stat 2015/2020 (既に municipality_stats にある実績) を census anchor とし、
XKT013 2025-2070 を projection として接続 → **2015→2070 のカーブ**が追加 fetch 最小で完成。
(Stage 2 で e-Stat 2000-2010 を過去側に延伸)

## 調査で確定した事実

| 事実 | 値 |
|---|---|
| XKT013 SHICODE | メッシュ属性で保持 → 自治体絞り込み可 (例 SHICODE=12219 市原市) |
| XKT013 年次 | 2020(実績基準)〜2070、5年刻み (2025-03-04 更新)。z=11-15、秘匿 HITOKU20XX |
| e-Stat 国勢調査 | 政府統計コード 00200521。各回別 statsDataId。「都道府県・市区町村別の主な結果」/時系列が組替済で扱いやすい |
| 合併境界 | 2000-2020 は平成大合併を含む → 組替 (遡及集計) データ or 時系列表で現行境界に揃える |
| ForecastChart | apps/web/src/app/forecast/page.tsx に inline SVG (historical 実線 + forecast 破線)。流用可 |

## 設計

### スキーマ (別テーブル = 時系列の王道)

```
citify-dev.citify_curated.municipality_population_series
  municipality_code  STRING   -- 5桁
  year               INTEGER  -- 2000..2070
  population         INTEGER  -- 総人口
  source             STRING   -- 'census' (e-Stat実績) | 'projection' (XKT013将来)
  loaded_at          TIMESTAMP
  source_url         STRING
PRIMARY KEY (municipality_code, year) 相当 (BQ は論理キー)
```

- `municipality_stats` は肥大化させない (15列横持ちを避ける)
- 過去=census, 将来=projection。2020 は両方に存在しうる → API 側で source 優先順位 (census 実績 > projection 基準) で重複排除

### XKT013 parser 修正 (scrapers/reinfolib/parsers/xkt013.py)

```python
def aggregate_population_series(
    features: list[dict], target_shicode: str
) -> dict[int, int]:
    """SHICODE == target のメッシュのみ、各 PT00_YYYY 年次を合算。秘匿(HITOKU{year}=1)除外。"""
    # 1. SHICODE 正規化比較: str(props["SHICODE"]).zfill(5) == target.zfill(5) (北海道 01xxx 対策、Medium#4)
    # 2. PT00_ prefix を動的検出し year を抽出。各 year で f"PT00_{year}" と f"HITOKU{year}" をペアで参照 (Medium#5)
    # 3. {2020: pop, 2025: pop, ...} を返す
```

- 既存 `aggregate_future_population` は deprecated (後方互換で残すか削除は Phase 1 で判断)
- 年次リスト + HITOKU 実名は Phase 0 の実 response で確定
- **カバレッジ (Critical#1)**: SHICODE フィルタは fetch された box 内メッシュにしか効かない。広域自治体で
  box (radius=1 ~36km) に収まらない場合、自治体 bbox から radius を動的算出して全メッシュを確保する

### e-Stat historical loader (新規 apps/api/scripts/load_estat_population_series.py)

- e-Stat API: getStatsList で 00200521 + 各年 → statsDataId 特定
- getStatsData で cdArea (市区町村) × cdTime (年) → 総人口
- 組替/時系列表を優先し現行境界に整合
- 出力: `municipality_population_series` に source='census' で INSERT

### API endpoint (apps/api)

```
GET /v1/cities/{code}/population-trend
→ { code, series: [{year, population, source}], latest_actual_year, projection_start_year }
```

- `municipality_population_series` を code で SELECT、year 昇順
- cache (既存 _*_CACHE パターン)

### Frontend (city ダッシュボード)

- ForecastChart を参考に `PopulationTrendChart` を実装 (実績=実線青 / 予測=破線オレンジ、2020 で接続)
- city ページに「人口推移 (2000→2070)」セクション追加
- 出典明記: 総務省国勢調査 + 国交省将来推計人口 (250m メッシュ集計)

## 作業ステップ (Phase 分割・段階デリバリ)

### Phase 0 (検証スパイク、40分) — 後続を gate
1. [ ] REINFOLIB_API_KEY / e-Stat appId の所在確認 + `municipality_stats` の管理手段 (Terraform or DDL) 確認 (Low#6)
2. [ ] XKT013 を **新宿区 13104 (小区) と広域自治体 1つ (例: 高山市 21203 / 浜松市 22130)** の z=11 タイルで live call →
   (a) PT00_YYYY 実在年次 + **HITOKU{year} の実フィールド名** を確認 (Medium#5)
   (b) **SHICODE 絞り込み件数が box 境界で切れていないか** = 広域自治体で過小にならないか (Critical#1)
   (c) SHICODE の型 (先頭ゼロ落ち int 由来か) を確認 (Medium#4)
3. [ ] e-Stat で 1 自治体の 2000-2020 総人口が取れる statsDataId / 時系列表を特定
4. [ ] 結果で詳細確定 + **広域自治体で取りこぼす場合は radius 動的算出 (自治体 bbox ベース) を Phase 1 に組込む**

--- **【Stage 1: 将来カーブ先行】** ---

### Phase 1 (60分) — XKT013 parser 修正 + test
5. [ ] xkt013.py に `aggregate_population_series(features, shicode)` 実装 (SHICODE zfill 正規化 / PT00・HITOKU 動的年次 / 必要なら radius 動的化)
6. [ ] GeoJSON fixture で test (SHICODE フィルタ / 北海道 01xxx / 秘匿除外 / 多年次集計 / box 境界カバレッジ)

### Phase 3 (45分) — スキーマ + BQ
9. [ ] municipality_population_series テーブル作成 (Phase 0 で確認した Terraform/DDL 手段に揃える)
10. [ ] XKT013 投入経路を BQ 書き込み対応 (source='projection')

### Phase 4a (データ投入、ユーザー実行) — reinfolib キー必要
11. [ ] XKT013 再fetch 1889 自治体 (SHICODE 集計) → series 投入。**所要試算 ~4.7h (rate 1.0s×9tile×1889)、radius 増で増大** (Low#7)
13a. [ ] 検証: **新宿 13104 (小区) + 広域自治体 (高山/浜松)** で 2020-2070 が妥当 (新宿 2020 ~34万) (Critical#1)

### Phase 5 (45分) — API endpoint + test
14. [ ] GET /v1/cities/{code}/population-trend + smoke test

### Phase 6 (75分) — Frontend グラフ
15. [ ] PopulationTrendChart (ForecastChart 流用)。**2020 は実線終端=破線始点の共有 1 点として描画** (census 優先、projection 2020 は破線起点座標のみ) (Medium#3)
16. [ ] city ページ統合 + 出典明記 (国交省将来推計) + tsc --noEmit

### Phase 7 (30分) — docs + regression + commit (Stage 1 出荷)
17. [ ] docs (PHASE_F v0.5 節) + 全 regression + commit 提示

--- **【Stage 2: 過去 census 延伸 (後続 v0.6)】** ---

### Phase 2 (90分) — e-Stat historical loader + test
7. [ ] load_estat_population_series.py 新規 (getStatsData ラッパー、source='census')
8. [ ] 組替/境界マッピング + test (fixture ベース)

### Phase 4b (データ投入、ユーザー実行) — e-Stat キー必要
12. [ ] e-Stat 2000-2020 投入 (census)
13b. [ ] 検証: 13104 等で 2000→2070 が連続、2020 census↔projection 接続が妥当

### Phase 6b / 7b — グラフに過去側 (実線左延伸) 反映 + docs v0.6

## 成果物
- [ ] scrapers/reinfolib/parsers/xkt013.py (SHICODE 集計) + tests
- [ ] apps/api/scripts/load_estat_population_series.py (新規) + tests
- [ ] BQ municipality_population_series テーブル
- [ ] apps/api: /v1/cities/{code}/population-trend + tests
- [ ] apps/web: PopulationTrendChart + city ページ統合
- [ ] docs 更新

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| API キー (reinfolib/e-Stat) が手元にない | データ fetch 不可 | Phase 0 で所在確認。無ければユーザーに依頼。コード/test は fixture で先行実装可 |
| XKT013 の PT00 実在年次が想定と違う | 集計年次ズレ | Phase 0 live call で確定。PT00_ prefix 動的検出で頑健化 |
| 平成大合併で過去コード不整合 | 過去カーブ欠損/誤り | e-Stat 組替・時系列表 (現行境界) を優先。マッピング不能な合併自治体は過去欠損で許容 (グラフは将来側のみ表示) |
| 1889 再fetch の quota/時間 | 投入遅延 | rate limit + バッチ。Phase 4 はユーザー実行で分離 |
| メッシュ→自治体集計が境界上で誤差 | 人口微差 | SHICODE 完全一致のみ採用 (按分しない)。「Citify 集計値」と注記 |
| グラフが2点しか出ない自治体 | 見栄え | 過去 census が無くても XKT013 2020-2070 で最低 11 点確保 |

## Out of Scope
- 2025 年国勢調査 (2026後半〜2027 公表) の反映
- 年齢階級別 (PT01-15) の推移 (総人口 PT00 のみ)
- メッシュ按分 (SHICODE 完全一致のみ)
- 人口以外の指標トレンド
