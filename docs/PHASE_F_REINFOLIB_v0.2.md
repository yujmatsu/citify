# Phase F v0.2 — Reinfolib 統合仕様書 (11 API 拡張版)

> 国土交通省「不動産情報ライブラリ」(reinfolib.mlit.go.jp) の **11 個の Web API** を統合し、街ダッシュボードに「住居・防災・子育て・医療・教育・移住」軸の客観統計を多層的に追加する。

- **Owner**: Yuji
- **Status**: Draft v0.2 (Reviewer v0.1 指摘 4 件を反映 + ユーザー要求 で API 全量 → 11 個に拡張)
- **作成日**: 2026-05-27
- **位置付け**: Phase D MVP の延長、Plan A の客観統計補強 (Should、AI Agent 要素なし)
- **前バージョン**: `docs/PHASE_F_REINFOLIB.md` (v0.1、2 API スコープ)

---

## 1. 目的

Citify の街ダッシュボードに、Phase D の人口統計に並ぶ **6 軸の客観レイヤー**を追加。

> 本機能は **AI Agent ではない** が、A-3 街ダッシュボード (Plan A 本筋) の信頼性を底上げする客観統計レイヤーとして、ハッカソン審査軸 4 (実用性・体験価値) の補強要素として位置付ける。

## 2. スコープ

### 採用 API (11 個) — Citify 関心軸との対応

| 関心軸 | API | 内容 | 提示形式 (UI) |
|---|---|---|---|
| 住居 | XIT001 | 不動産取引価格 | 中古マンション中央値 (万円) |
| 住居 | XPT002 | 地価公示 | 5 年変動率 (%、住宅地) |
| **防災** | XKT026 | 洪水浸水想定 | 該当エリア比率 / 該当世帯数 |
| **防災** | XKT028 | 津波浸水想定 | 同上 (沿岸自治体のみ) |
| **防災** | XKT029 | 土砂災害警戒区域 | 同上 (山間部自治体のみ) |
| **防災** | XGT001 | 指定緊急避難場所 | 自治体内施設数 |
| 移住・人口 | XKT013 | 将来推計人口 250m メッシュ | 2050 年予測 vs 2020 比 |
| 移住・人口 | XKT015 | 駅別乗降客数 | 主要 3 駅の規模 |
| 子育て | XKT007 | 保育園・幼稚園 | 万人あたり施設数 |
| 医療 | XKT010 | 医療機関 | 万人あたり施設数 |
| 教育 | XKT004 + XKT005 | 小・中学校区 | 学校数 (UI なし、データ蓄積のみ MVP) |

### 対象自治体 (Reviewer #3 対応)

**105 自治体 — 政令市 20 + 中核市 62 + 特別区 23**

- リスト: `infra/seed/municipality_master.csv` で `tier=1 AND is_active=true` の自治体を抽出
- 全国 1795 自治体に広げるのは v0.3 以降 (レート制限と工数のリスク考慮)

### スコープ外 (Phase F v3 以降に保留)

- 残り 22 API (図書館 / 福祉施設 / 用途地域 / 都市計画道路 / 災害履歴 等)
- 物件単位の地図ピン (個人特定リスク)
- 賃料 (本 API 群では取得不可)

## 3. 利用規約 verify (Reviewer #2 対応)

| 確認項目 | 確認日 | 結果 | 根拠 |
|---|---|---|---|
| BQ への保存 | 2026-05-27 | ✅ 可 | API 利用規約には保存禁止条項なし、PDL1.0 適用範囲 |
| 加工値の web 公開 | 2026-05-27 | ✅ 可 (条件あり) | PDL1.0 下、編集・加工した旨を明記すれば可 |
| 「国が作成したかのような態様」 | 2026-05-27 | ❌ NG | 必ず「Citify 集計値」と表記 |
| 出典クレジット | 2026-05-27 | ✅ 必須 | 「出典: 国土交通省 不動産情報ライブラリ (URL)」を併記 |
| 商用利用 | 2026-05-27 | ✅ 可 | PDL1.0 下で許諾 |
| 第三者への再配布 | 2026-05-27 | ✅ 可 | ただし「国作成と誤認させない」が条件 |

- 確認元: `https://www.reinfolib.mlit.go.jp/help/termsOfUse/`
- 規約改定時の再確認担当: Yuji

## 4. 各 API の詳細仕様

### 4.1 共通

| 項目 | 値 |
|---|---|
| Base URL | `https://www.reinfolib.mlit.go.jp/ex-api/external/` |
| 認証ヘッダ | `Ocp-Apim-Subscription-Key: <API_KEY>` |
| Method | GET |
| レート制限 | 明示なし、Citify 側で **1 req/sec** で運用 |
| 形式 | JSON (一部 GIS API は GeoJSON) |

### 4.2 価格系 (2 API)

| API | パラメータ | 整備範囲 | Citify 加工 |
|---|---|---|---|
| **XIT001** 取引価格 | `year` + `quarter` + `city` (5桁) | 2005Q3〜 | 直近 4Q の **中古マンション中央値** (`Type=中古マンション等`)、サンプル数併記 |
| **XPT002** 地価公示 | `year` + `area` or `city` | 1995〜 | **5 年変動率** = 同一 `StandardLandNumber` で 2020→2024 比較、住宅地のみフィルタ、変動率の中央値 (Reviewer #4 対応) |

### 4.3 防災系 (4 API)

| API | パラメータ | Citify 加工 |
|---|---|---|
| **XKT026** 洪水浸水想定 (河川単位) | `city` | 自治体面積に対する**該当エリア比率** (%) |
| **XKT028** 津波浸水想定 | `city` | 同上 (内陸自治体は `null`) |
| **XKT029** 土砂災害警戒区域 | `city` | 同上 (平野部自治体は `null`) |
| **XGT001** 指定緊急避難場所 | `city` | 自治体内**施設数** (万人あたり) |

倫理ガード (防災):
- 「危険な街」「住むべきでない」などのテキスト一切なし
- 「ハザード該当エリア比率 N%」「最寄り避難所 M か所」の **客観事実のみ**
- カード下に「**避難計画は自治体の公式ハザードマップを確認してください**」と link 併記

### 4.4 人口・移住系 (2 API)

| API | パラメータ | Citify 加工 |
|---|---|---|
| **XKT013** 将来推計人口 250m メッシュ | `city` | 自治体合計 → 2050 年予測 vs 2020 比 (%) |
| **XKT015** 駅別乗降客数 | `city` | **主要 3 駅** (乗降客数 top 3) の総乗降客数 |

### 4.5 周辺施設系 (3 API)

| API | パラメータ | Citify 加工 |
|---|---|---|
| **XKT007** 保育園・幼稚園 | `city` | **万人あたり施設数** (= count / 人口 × 10000) |
| **XKT010** 医療機関 | `city` | 同上 |
| **XKT004** + **XKT005** 小・中学校区 | `city` | 学校数のみ蓄積 (UI 表示は v0.3 以降) |

## 5. アーキテクチャ

```
新規ディレクトリ: scrapers/reinfolib/
  ├─ __init__.py
  ├─ client.py           # httpx AsyncClient + Ocp-Apim-Subscription-Key
  ├─ parsers/
  │   ├─ __init__.py
  │   ├─ xit001.py       # 中古マンション中央値集計
  │   ├─ xpt002.py       # 5 年地価変動率 (同一標準地点比較の中央値)
  │   ├─ xkt026.py       # 洪水該当エリア比率
  │   ├─ xkt028.py       # 津波同上
  │   ├─ xkt029.py       # 土砂同上
  │   ├─ xgt001.py       # 避難所カウント
  │   ├─ xkt013.py       # 将来推計人口
  │   ├─ xkt015.py       # 駅別乗降客数
  │   ├─ xkt007.py       # 保育園・幼稚園カウント
  │   ├─ xkt010.py       # 医療機関カウント
  │   └─ xkt004_005.py   # 学校区カウント
  ├─ schema.py           # Pydantic: RealEstateStats (1 自治体 1 record、11 fields)
  ├─ __main__.py         # CLI: fetch-all, load-bq, dry-run
  └─ tests/
      ├─ test_client.py
      ├─ test_parsers_xit001.py ... (各 parser ごと)
      └─ fixtures/                # 各 API の固定 JSON / GeoJSON
```

**Pub/Sub 不使用** (Reviewer #6 対応): reinfolib は 1 自治体 1 record の集計値で時系列 publish の意味が薄いため、Phase D `load_estat_stats.py` パターン (NDJSON + WRITE/MERGE) を踏襲。

```
apps/api/scripts/
  └─ load_reinfolib_stats.py     # MERGE 構文で reinfolib 由来列のみ UPDATE

apps/api/main.py
  └─ MunicipalityStats モデルに 11 fields 追加 + _fetch_municipality_stats で同時取得
     (e-Stat と同じ municipality_stats テーブルから 1 query で取得、JOIN なし)

apps/web/src/lib/api.ts
  └─ MunicipalityStatsSchema に 11 fields 追加

apps/web/src/app/cities/[code]/page.tsx
  └─ StatsCards (Phase D 6 カード) + RealEstateCards (3) + DisasterCards (4) +
     ChildcareCards (2) + DemographicsCards (2) を sectioned で表示
```

## 6. BQ スキーマ拡張

既存 `citify_curated.municipality_stats` に **追加 14 列** (派生指標含む):

| 列名 | 型 | NULL | 由来 API | 説明 |
|---|---|---|---|---|
| `used_apartment_median_price_man_yen` | INTEGER | YES | XIT001 | 中古マンション中央値 (万円) |
| `used_apartment_sample_size` | INTEGER | YES | XIT001 | サンプル数 (n<10 は UI 非表示) |
| `landprice_residential_yen_per_m2` | INTEGER | YES | XPT002 | 住宅地平均地価 |
| `landprice_change_pct_5yr` | FLOAT | YES | XPT002 | 5 年変動率 (中央値) |
| `landprice_baseline_year` | INTEGER | YES | XPT002 | 比較ベース年 (Reviewer #8) |
| `landprice_latest_year` | INTEGER | YES | XPT002 | 最新年 |
| `flood_risk_area_pct` | FLOAT | YES | XKT026 | 洪水想定該当面積比率 |
| `tsunami_risk_area_pct` | FLOAT | YES | XKT028 | 津波想定該当面積比率 |
| `landslide_risk_area_pct` | FLOAT | YES | XKT029 | 土砂警戒該当面積比率 |
| `emergency_shelter_count` | INTEGER | YES | XGT001 | 指定緊急避難場所数 |
| `population_2050_estimated` | INTEGER | YES | XKT013 | 2050 推計人口 |
| `population_change_2050_pct` | FLOAT | YES | XKT013 | 2050 vs 2020 変動率 |
| `top3_stations_passengers_daily` | INTEGER | YES | XKT015 | 主要 3 駅日次乗降客数合計 |
| `childcare_facilities_per_10k` | FLOAT | YES | XKT007 | 保育施設数 / 万人 |
| `medical_facilities_per_10k` | FLOAT | YES | XKT010 | 医療機関数 / 万人 |
| `elementary_school_count` | INTEGER | YES | XKT004 | 小学校区数 |
| `junior_high_school_count` | INTEGER | YES | XKT005 | 中学校区数 |
| `reinfolib_source_url` | STRING | YES | — | "https://www.reinfolib.mlit.go.jp/" |
| `reinfolib_loaded_at` | TIMESTAMP | YES | — | reinfolib データの最終ロード時刻 |

合計: **既存 16 列 + 19 列 = 35 列** (PoC レベルで許容、将来は別テーブル分離も検討)

ロード方式: MERGE 構文で reinfolib 由来 19 列のみ UPDATE (e-Stat 由来 16 列は壊さない)。

```sql
MERGE INTO citify_curated.municipality_stats T
USING tmp_reinfolib_load S
ON T.municipality_code = S.municipality_code
WHEN MATCHED THEN UPDATE SET
  used_apartment_median_price_man_yen = S.used_apartment_median_price_man_yen,
  ... (19 列分)
WHEN NOT MATCHED THEN
  INSERT (municipality_code, used_apartment_median_price_man_yen, ...)
  VALUES (S.municipality_code, S.used_apartment_median_price_man_yen, ...)
```

## 7. API キー管理 (Reviewer #7 対応で pre-commit Must 化)

### 7.1 ローカル

`.env.local` (gitignore 済) に:
```bash
REINFOLIB_API_KEY=<API_KEY>
```

### 7.2 本番 (Cloud Run / Job)

Terraform で:
```hcl
resource "google_secret_manager_secret" "reinfolib_api_key" {
  secret_id = "citify-reinfolib-api-key"
  replication { auto {} }
}
```

値は `gcloud secrets versions add citify-reinfolib-api-key --data-file=-` で手動投入。

Cloud Run Job env で `secret_key_ref` 参照。

### 7.3 漏洩防止 (Must 受け入れ条件に格上げ、Reviewer #7)

- pre-commit hook `scripts/check-secrets.sh` を **Must** で導入
  - パターン: `Ocp-Apim-Subscription-Key:` / 32 桁 hex / `REINFOLIB_API_KEY=` (値付き)
  - 検出時は commit を block
- `.env.local` 内容が `git status -uall` に出ないことを CI で確認

## 8. Frontend 統合

### 8.1 街ダッシュボード — 4 セクション構成

```
┌──────────────────────────────────────────────────┐
│ 📊 街のかたち (客観統計)                          │
├──────────────────────────────────────────────────┤
│ 人口・年齢構成: 既存 6 カード (Phase D)            │
├──────────────────────────────────────────────────┤
│ 🏠 住居 (Phase F)                                  │
│   中古マンション中央値 / 地価変動 5 年              │
├──────────────────────────────────────────────────┤
│ 🌊 防災 (Phase F)                                  │
│   洪水該当 / 津波該当 / 土砂該当 / 避難所数        │
│   ⚠️ 「避難計画は自治体公式ハザードマップを確認」  │
├──────────────────────────────────────────────────┤
│ 👶 子育て・医療 (Phase F)                          │
│   保育施設/万人 / 医療機関/万人                    │
├──────────────────────────────────────────────────┤
│ 🚆 人口・移動 (Phase F)                            │
│   2050 年人口予測 / 主要 3 駅乗降客数              │
├──────────────────────────────────────────────────┤
│ 出典: e-Stat + 不動産情報ライブラリ (国土交通省)    │
│      「Citify 編集・加工」                          │
└──────────────────────────────────────────────────┘
```

### 8.2 倫理ガード UI

| ガード | 実装 |
|---|---|
| サンプル不足 (n<10) | カード自体を非描画 |
| 価値判断 NG | 数値のみ、「安い/高い/危険」等のテキスト禁止 |
| 防災情報の煽り回避 | 各防災カード下に「公式ハザードマップ確認」link |
| 出典明示 | セクション header に出典 link、bottom に「Citify 集計値」 |
| 「国作成と誤認」回避 | 「不動産情報ライブラリ (国土交通省) をもとに Citify 編集・加工」を出典に明記 |
| レスポンシブ (Reviewer #9) | sm:1col / md:2col / lg:4col の grid、セクションは縦並びで崩れない |

## 9. 受け入れ条件

### Must (Phase F v1 として実装、これが全部 green で merge 可)

- [ ] `scrapers/reinfolib/__main__.py fetch-all --city 13104 --year 2024` で 11 API すべての JSON が取れる
- [ ] `load_reinfolib_stats.py --munis-tier 1` で BQ municipality_stats に 19 列の値が書き込まれる (105 自治体)
- [ ] BFF `/v1/cities/13104` レスポンスの `stats` に 19 新 fields が含まれる (zod schema 一致)
- [ ] Web `/cities/13104` に 4 セクション (住居/防災/子育て・医療/人口・移動) が描画される
- [ ] サンプル不足の自治体ではカードが非描画 (UI クラッシュなし)
- [ ] 出典に「不動産情報ライブラリ (国土交通省)」と「Citify 編集・加工」が表示される
- [ ] 防災カード下に「公式ハザードマップ確認」link が表示される
- [ ] **API キー漏洩防止 (Reviewer #7)**: pre-commit hook が動作、`scripts/check-secrets.sh` が Reinfolib キーパターンを検出して commit block
- [ ] pytest scrapers/reinfolib/tests/ で正常系 11 + 異常系 (401 / n<10 / 5年地価補完不能) 計 14 件以上 pass
- [ ] ruff check/format + terraform fmt + next build が全 pass

### Should

- [ ] Cloud Run Job 通し動作確認 (Reviewer #12): GCP 実環境で `gcloud run jobs execute citify-worker-reinfolib --wait` が成功、ログに 105 自治体分の処理ログ
- [ ] チェックポイント (Reviewer #5): 途中失敗時、どこまで取れたか BQ に部分書込済で再実行可能
- [ ] サンプル数 / 算定年度を API レスポンス含めて UI に表示 (n=45 件 / 2020→2024 等)

### Won't (本フェーズではやらない)

- 残り 22 API (図書館 / 福祉 / 用途地域 等)
- 物件単位の地図ピン
- 賃料データ
- ハザードマップの GIS レイヤー重ね合わせ (数値のみ)
- 全国 1795 自治体 (105 自治体のみ MVP)

## 10. 工数見積もり (Reviewer #1, #12 反映、楽観値 → 現実値に修正)

| 工程 | 時間 |
|---|---|
| API キー Secret Manager 登録 (手動) | 5 分 |
| `scrapers/reinfolib/client.py` | 2 h |
| 11 個の parser 実装 (各 ~1h、GIS API は GeoJSON 解析必要) | 12 h |
| `scrapers/reinfolib/__main__.py` CLI (fetch-all / load-bq) | 2 h |
| pytest fixtures (11 API の sample JSON) + unit test 14 件 | 6 h |
| `apps/api/scripts/load_reinfolib_stats.py` (MERGE 構文) | 3 h |
| BQ schema Terraform 更新 + apply | 1 h |
| `apps/api/main.py` MunicipalityStats 拡張 (19 fields) | 1.5 h |
| `apps/web/src/lib/api.ts` zod schema 拡張 | 0.5 h |
| `cities/[code]/page.tsx` 4 セクション StatsCards + 倫理 UI + レスポンシブ | 4 h |
| pre-commit hook `scripts/check-secrets.sh` | 1 h |
| ruff/format/test + Cloud Run Job 通し動作確認 | 3 h |
| **合計** | **36 h (4.5 日)** |

> v0.1 の 15.5h は 2 API 想定。11 API に拡張で +20.5h。Plan A 本筋 (A-5/A-6/A-7) に 6/15 までに進捗が出るかの monitoring point を設置。

## 11. リスクと緩和 (Reviewer #5 + 新規)

| リスク | 影響 | 緩和策 |
|---|---|---|
| 11 API × 105 自治体 = 1155 リクエスト + 5 年地価 +420 = 1575 req → 26 分 (rate 1/sec) | 中 | Cloud Run Job timeout を `task_timeout=3600s` に設定、チェックポイント実装 (BQ に部分書込)、再実行で残り処理 |
| 政令市の区単位データが無い | 中 | 1 件 sample call で確認、無ければ親市コードに集約 (例: 13101 千代田区 → 13100 東京都?) — ただし特別区は親自治体なしの可能性、別途要確認 |
| GIS API (XKT026 等) の GeoJSON 解析が複雑 | 高 | shapely / geopandas を使って自治体ポリゴンと交差判定、面積比率計算。実装時間が +50% かかる可能性 |
| サンプル不足の自治体が多い | 高 | n<10 は UI 非表示、105 自治体すべてではなくサンプル豊富な top 自治体から優先表示 |
| API キー漏洩 | 高 | Secret Manager + pre-commit hook (Must 受け入れ条件)、git 不混入 |
| **Plan A 本筋の遅れ** (Reviewer #1) | **高** | 6/15 進捗チェックポイント設置、A-5/A-6/A-7 の進捗が出ていなければ Phase F v3 (子育て・医療・人口推計) を Drop して Plan A に戻る |
| 利用規約変更 | 低 | §3 に確認日 + URL 明記、規約改定時に再確認 |

## 12. 実装着手の前提 (Reviewer #1 対応)

- [x] 仕様書 v0.2 が作成された
- [ ] 仕様書 v0.2 が Reviewer subagent で再レビューされる (Critical/High 指摘がなければ承認)
- [ ] ユーザー承認 (このドキュメントで OK)
- [ ] Plan A Must (A-5/A-6/A-7) の進捗確認 — 既に走行中なので並行で進める判断
- [ ] **6/15 monitoring point**: Plan A 本筋に進捗が出ているか確認、出ていなければ Phase F v3 Drop

## 改訂履歴

- 2026-05-27 v0.1 Draft 作成 (2 API スコープ、Reviewer Needs Improvement)
- 2026-05-27 v0.2 Draft 作成 (11 API 拡張 + Reviewer 4 件指摘反映)
