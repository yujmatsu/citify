# Phase F v0.3.1 — Reinfolib 統合仕様書 (45 自治体 × 8 API、§2 機械検証 patch)

> 国土交通省「不動産情報ライブラリ」(reinfolib.mlit.go.jp) の **8 個の Web API** を統合し、`tier1_supplements.csv` is_active=true の **45 自治体**の街ダッシュボードに「住居・防災・子育て・医療・教育・移住」軸の客観統計を追加する。

- **Owner**: Yuji
- **Status**: Draft v0.3.1 (v0.3 Reviewer Critical #1 を機械集計で patch、残り中・低指摘は Review Punchlist として保留)
- **作成日**: 2026-05-27
- **位置付け**: Phase D MVP の延長、Plan A の客観統計補強 (Should、AI Agent 要素なし)
- **前バージョン**: v0.1 (`PHASE_F_REINFOLIB.md`、2 API)、v0.2 (`PHASE_F_REINFOLIB_v0.2.md`、11 API、Critical fact error)、v0.3 (`PHASE_F_REINFOLIB_v0.3.md`、§2 fact error)

---

## 1. 目的

Citify の街ダッシュボードに、Phase D の人口統計に並ぶ **6 軸の客観レイヤー**を追加。

> 本機能は **AI Agent ではない** が、A-3 街ダッシュボード (Plan A 本筋) の信頼性を底上げする客観統計レイヤーとして、ハッカソン審査軸 4 (実用性・体験価値) の補強要素として位置付ける。

Phase A で press_rss 動作確認済の 45 自治体に絞ることで、「**議題 (press_rss) × 統計 (e-Stat + Reinfolib)** が両方揃った街ダッシュボード」という体験完成度を優先する。

## 2. スコープ

### 採用 API (8 個、v0.2 から GIS 3 本を v3 降格)

| 関心軸 | API | 内容 | 提示形式 (UI) |
|---|---|---|---|
| 住居 | XIT001 | 不動産取引価格 | 中古マンション中央値 (万円) |
| 住居 | XPT002 | 地価公示 | 5 年変動率 (%、住宅地) |
| **防災** | XGT001 | 指定緊急避難場所 | 自治体内施設数 + 公式ハザードマップ link |
| 移住・人口 | XKT013 | 将来推計人口 250m メッシュ | 2050 年予測 vs 2020 比 |
| 移住・人口 | XKT015 | 駅別乗降客数 | 主要 3 駅の規模 |
| 子育て | XKT007 | 保育園・幼稚園 | 万人あたり施設数 |
| 医療 | XKT010 | 医療機関 | 万人あたり施設数 |
| 教育 | XKT004 + XKT005 | 小・中学校区 | 学校数 (UI なし、データ蓄積のみ) |

### 対象自治体 (Reviewer v0.3 Critical #1 を機械集計で patch)

**45 自治体 — `infra/seed/tier1_supplements.csv` で `is_active=true` の全エントリ**

**抽出コマンド (実装時の入力リストもこれを使用)**:
```bash
awk -F',' 'NR>1 && $8=="true" {print $1}' infra/seed/tier1_supplements.csv | sort -u
```

**実行結果 (2026-05-27 時点、計 45 件)**:

```text
01000  北海道          (都道府県, press_rss)
01100  札幌市          (政令市, voices_asp)        ← scraper_type=voices_asp、press_rss URL なし
01213  苫小牧市        (中核市, press_rss)
02000  青森県          (都道府県, press_rss)
04000  宮城県          (都道府県, press_rss)
07000  福島県          (都道府県, press_rss)
08000  茨城県          (都道府県, press_rss)
09000  栃木県          (都道府県, press_rss)
10000  群馬県          (都道府県, press_rss)
11000  埼玉県          (都道府県, press_rss)
12000  千葉県          (都道府県, press_rss)
12203  船橋市          (中核市, press_rss)
12217  柏市            (中核市, press_rss)
14000  神奈川県        (都道府県, press_rss)
14130  川崎市          (政令市, press_rss)
14150  相模原市        (政令市, press_rss)
15000  新潟県          (都道府県, press_rss)
15100  新潟市          (政令市, press_rss)
17000  石川県          (都道府県, press_rss)
19000  山梨県          (都道府県, press_rss)
20202  松本市          (中核市, press_rss)
22000  静岡県          (都道府県, press_rss)
22203  沼津市          (中核市, press_rss)
23000  愛知県          (都道府県, press_rss)
23201  豊橋市          (中核市, press_rss)        ← Phase A publish empty (RSS 在庫 0)
24202  四日市市        (中核市, press_rss)
26100  京都市          (政令市, press_rss)
27100  大阪市          (政令市, kaigiroku)        ← scraper_type=kaigiroku、press_rss URL なし
27140  堺市            (政令市, press_rss)
29201  奈良市          (中核市, press_rss)
32000  島根県          (都道府県, press_rss)
33000  岡山県          (都道府県, press_rss)
33100  岡山市          (政令市, press_rss)
34000  広島県          (都道府県, press_rss)
34100  広島市          (政令市, press_rss)
38201  松山市          (中核市, press_rss)
40000  福岡県          (都道府県, press_rss)
40100  北九州市        (政令市, press_rss)
40130  福岡市          (政令市, press_rss)
42202  佐世保市        (中核市, press_rss)
43000  熊本県          (都道府県, press_rss)
43100  熊本市          (政令市, press_rss)
44201  大分市          (中核市, press_rss)
46000  鹿児島県        (都道府県, press_rss)
46201  鹿児島市        (中核市, press_rss)        ← Phase A publish empty (RSS 在庫 0)
```

**内訳の機械検証** (`awk` 集計):

| 区分 | code パターン | 件数 | 例 |
|---|---|---|---|
| 都道府県 | XX000 (XX!=00) | **21** | 北海道, 青森, 宮城... |
| 政令市 | XX100 / XX130 / XX140 / XX150 | **12** | 札幌, 横浜, 川崎, 大阪... |
| 中核市/特別区 | 上記以外の 5 桁 | **12** | 苫小牧, 船橋, 柏, 松本... |
| **合計** | — | **45** | — |

**scraper_type 別** (Phase F は reinfolib データ取得が主目的で scraper_type 不問):

| scraper_type | 件数 | 補足 |
|---|---|---|
| press_rss | **43** | Phase A publish-all 動作確認済 (うち 2 件 empty: 23201/46201) |
| voices_asp | 1 | 01100 札幌市 (Phase A 対象外、scraper_type 別) |
| kaigiroku | 1 | 27100 大阪市 (Phase A 対象外、scraper_type 別) |

> **定義の明確化**: Phase F のスコープは「scraper_type 不問、is_active=true な 45 自治体」。reinfolib API は scraper パイプラインと独立に動くため、議事録 scraper の種類は本フェーズに影響しない。Phase A `publish-all` 動作確認済 = press_rss 限定 43 件は **参考情報**で、Phase F の対象選定基準ではない。

**前提タスク (Phase F 着手前)**:
- [x] §2 対象自治体リストを `tier1_supplements.csv` 機械集計で確定 (2026-05-27 完了)
- [ ] master.csv の tier 体系見直しは **本仕様書スコープ外** (将来別タスク)

### スコープ外 (Phase F v2/v3 以降に保留)

- **v2 候補**: GIS API 3 本 (XKT026 洪水 / XKT028 津波 / XKT029 土砂) — Reviewer #4 の工数膨張リスクで降格
- **v3 候補**: 残り 22 API (図書館 / 福祉施設 / 用途地域 / 都市計画道路 / 災害履歴 等)
- **本仕様書スコープ外**:
  - 物件単位の地図ピン (個人特定リスク)
  - 賃料データ (本 API 群では取得不可)
  - 全国 1795 自治体への拡張
  - master.csv の tier 体系見直し

## 3. 利用規約 verify (Reviewer v0.1 #2 対応、v0.2 から継続)

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
| 形式 | JSON |

### 4.2 価格系 (2 API)

| API | パラメータ | 整備範囲 | Citify 加工 |
|---|---|---|---|
| **XIT001** 取引価格 | `year` + `quarter` + `city` (5桁) | 2005Q3〜 | 直近 4Q の **中古マンション中央値** (`Type=中古マンション等`)、サンプル数 (n) を併記 |
| **XPT002** 地価公示 | `year` + `city` (5桁) | 1995〜 | **5 年変動率** = **2020 と 2024 両方に存在する**同一 `StandardLandNumber` (inner join 相当、片方欠損は除外) の住宅地のみ、変動率の中央値 |

> Reviewer v0.1 #4 完全反映 (Reviewer v0.2 #7 で指摘された「新規/廃止地点除外」を `inner join 相当、片方欠損は除外` で明示)。

**政令市の区単位データ可否 (Reviewer v0.2 #8 対応)**: 着手前に **30 分以内で sample call** を実施し、`XIT001?city=27127&year=2024&quarter=3` (大阪市北区) が成功するか検証。

- 成功 → 政令市の区も対象に含める
- 失敗 → 親市コード (例: 27100 大阪市) のみで集計、§2 対象リストから区を除外
- sample 結果は本仕様書の改訂履歴に記録

### 4.3 防災系 (1 API、GIS 3 本は v2 降格)

| API | パラメータ | Citify 加工 |
|---|---|---|
| **XGT001** 指定緊急避難場所 | `city` | 自治体内**施設数** (万人あたり) + 公式ハザードマップ link |

**公式ハザードマップ link の解決方針 (Reviewer v0.2 #9 対応)**:
- 国土地理院 ハザードマップポータルサイトの自治体検索 URL を共通フォーマットで生成
- フォーマット: `https://disaportal.gsi.go.jp/hazardmapportal/hazardmap/maps/index.html?ll=<lat>,<lng>&z=12`
- 自治体中心座標は `infra/seed/municipality_master.csv` に新規列 `center_lat` / `center_lng` を追加して保持 (master.csv 拡張は前提タスク)
  - もしくは XGT001 レスポンスの避難所平均座標を使用 (前提タスク不要)
- 解決不能時は generic URL `https://disaportal.gsi.go.jp/` を fallback

倫理ガード (防災):
- 「危険な街」「住むべきでない」などのテキスト一切なし
- 「避難所 N か所」の客観事実のみ
- カード下に「**避難計画は自治体の公式ハザードマップを確認してください**」と link 併記 (Must)

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
  ├─ client.py           # httpx AsyncClient + Ocp-Apim-Subscription-Key + rate_limit_sec
  ├─ parsers/
  │   ├─ __init__.py
  │   ├─ xit001.py       # 中古マンション中央値集計
  │   ├─ xpt002.py       # 5 年地価変動率 (同一標準地点 inner join 中央値)
  │   ├─ xgt001.py       # 避難所カウント
  │   ├─ xkt013.py       # 将来推計人口
  │   ├─ xkt015.py       # 駅別乗降客数
  │   ├─ xkt007.py       # 保育園・幼稚園カウント
  │   ├─ xkt010.py       # 医療機関カウント
  │   └─ xkt004_005.py   # 学校区カウント
  ├─ schema.py           # Pydantic: RealEstateStats (1 自治体 1 record、8 fields の値)
  ├─ __main__.py         # CLI: fetch-all, load-bq, dry-run, sample-call
  └─ tests/
      ├─ test_client.py
      ├─ test_parsers_xit001.py ... (各 parser ごと)
      └─ fixtures/                # 各 API の固定 JSON
```

**Pub/Sub 不使用** (Reviewer v0.1 #6 対応): reinfolib は 1 自治体 1 record の集計値で時系列 publish の意味が薄いため、Phase D `load_estat_stats.py` パターン (NDJSON + WRITE/MERGE) を踏襲。

**Cloud Run Job として実装するか否か (Reviewer v0.2 #3 対応)**:
- **45 自治体 × 8 API × 1 req/sec = 360 req = 6 分**で完結するため、Cloud Run Job は**作らない**
- ローカル CLI 実行 + BQ 投入のみ。月 1 回手動 refresh で十分
- 将来 Cloud Run Job 化する場合は既存 workers の `timeout="3540s"` パターンに揃える

```
apps/api/scripts/
  └─ load_reinfolib_stats.py     # MERGE 構文で reinfolib 由来列のみ UPDATE

apps/api/main.py
  └─ MunicipalityStats モデルに 13 fields 追加 + _fetch_municipality_stats で同時取得
     (e-Stat と同じ municipality_stats テーブルから 1 query で取得、JOIN なし)

apps/web/src/lib/api.ts
  └─ MunicipalityStatsSchema に 13 fields 追加

apps/web/src/app/cities/[code]/page.tsx
  └─ StatsCards (Phase D 6 カード) + RealEstateCards (3) + DisasterCards (1) +
     ChildcareCards (2) + DemographicsCards (2) を sectioned で表示
```

## 6. BQ スキーマ拡張

既存 `citify_curated.municipality_stats` に **追加 13 列** (v0.2 の 19 列から GIS 由来 6 列を削除):

| 列名 | 型 | NULL | 由来 API | 説明 |
|---|---|---|---|---|
| `used_apartment_median_price_man_yen` | INTEGER | YES | XIT001 | 中古マンション中央値 (万円) |
| `used_apartment_sample_size` | INTEGER | YES | XIT001 | サンプル数 (n<10 は UI 非表示) |
| `landprice_residential_yen_per_m2` | INTEGER | YES | XPT002 | 住宅地平均地価 |
| `landprice_change_pct_5yr` | FLOAT | YES | XPT002 | 5 年変動率 (中央値) |
| `landprice_baseline_year` | INTEGER | YES | XPT002 | 比較ベース年 |
| `landprice_latest_year` | INTEGER | YES | XPT002 | 最新年 |
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

合計: **既存 16 列 + 16 列 = 32 列** (PoC レベルで許容、将来別テーブル分離は Could)

**MERGE 構文 (Reviewer v0.2 #5 対応)**:
- 前段で **e-Stat ロードが先行している前提**を Must 受け入れ条件に明示
- 新規 reinfolib-only 自治体の挿入は不要 (Phase D で 1794 自治体全部 INSERT 済)
- そのため `WHEN NOT MATCHED THEN INSERT` 分岐を削除し、**UPDATE-only** を強制

```sql
MERGE INTO citify_curated.municipality_stats T
USING (SELECT * FROM tmp_reinfolib_load) S
ON T.municipality_code = S.municipality_code
WHEN MATCHED THEN UPDATE SET
  used_apartment_median_price_man_yen = S.used_apartment_median_price_man_yen,
  ... (16 列分)
  reinfolib_loaded_at = CURRENT_TIMESTAMP();
-- WHEN NOT MATCHED は意図的に書かない (e-Stat 行が全自治体に存在する前提)
```

## 7. API キー管理

### 7.1 ローカル

`.env.local` (gitignore 済) に:
```bash
REINFOLIB_API_KEY=<API_KEY>
```

### 7.2 本番

Terraform で Secret Manager:
```hcl
resource "google_secret_manager_secret" "reinfolib_api_key" {
  secret_id = "citify-reinfolib-api-key"
  replication { auto {} }
}
```

値は `gcloud secrets versions add citify-reinfolib-api-key --data-file=-` で手動投入。

ローカル CLI 実行のみで Cloud Run 不要なので、Cloud Run env 設定は当面不要。将来 Cloud Run Job 化したら secret_key_ref で参照。

### 7.3 漏洩防止 (Reviewer v0.2 #2 対応で CI gating 追加)

**Must 受け入れ条件**:
- [ ] ローカル: pre-commit hook `scripts/check-secrets.sh` で `Ocp-Apim-Subscription-Key` / `REINFOLIB_API_KEY=<value>` パターンを grep ブロック
- [ ] **CI: GitHub Actions に `gitleaks/gitleaks-action@v2` を追加** (`.github/workflows/lint.yml` に新ジョブ `secret-scan`)
  - pre-commit は `--no-verify` で bypass 可能なので、CI gating で防御
  - ruleset で Reinfolib API キーパターン (32 桁 hex) を明示
- [ ] `.env.local` 内容が `git status -uall` に出ないことを CI で確認

## 8. Frontend 統合

### 8.1 街ダッシュボード — 5 セクション構成 (v0.2 の 4 セクションから防災を 1 カードに縮小)

```
┌──────────────────────────────────────────────────┐
│ 📊 街のかたち (客観統計)                          │
├──────────────────────────────────────────────────┤
│ 人口・年齢構成 (Phase D): 既存 6 カード           │
├──────────────────────────────────────────────────┤
│ 🏠 住居 (Phase F)                                  │
│   中古マンション中央値 / 地価変動 5 年              │
├──────────────────────────────────────────────────┤
│ 🌊 防災 (Phase F)                                  │
│   指定緊急避難場所 N か所                          │
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

### 8.2 倫理ガード UI (Reviewer v0.1 + v0.2 完全反映)

| ガード | 実装 |
|---|---|
| サンプル不足 (n<10) | カード自体を非描画 |
| 価値判断 NG | 数値のみ、「安い/高い/危険」等のテキスト禁止 |
| 防災情報の煽り回避 | 避難所カード下に「公式ハザードマップ確認」link (Must) |
| 出典明示 | セクション header に出典 link、bottom に「Citify 集計値」 |
| 「国作成と誤認」回避 | 「不動産情報ライブラリ (国土交通省) をもとに Citify 編集・加工」を出典に明記 |
| レスポンシブ | sm:1col / md:2col / lg:4col の grid、セクションは縦並びで崩れない |

## 9. 受け入れ条件

### Must (Phase F v1 として実装、これが全部 green で merge 可)

- [ ] `scrapers/reinfolib/__main__.py sample-call --city 13104` で全 8 API の sample call が 200 OK (政令市区単位対応の検証含む)
- [ ] `scrapers/reinfolib/__main__.py fetch-all --munis-from infra/seed/tier1_supplements.csv` で **45 自治体 × 8 API** の JSON が取れる (6 分で完了)
- [ ] `load_reinfolib_stats.py` で BQ municipality_stats に **16 列**の値が UPDATE される (e-Stat 16 列は破壊しない)
- [ ] BFF `/v1/cities/13104` レスポンスの `stats` に 13 新 fields が含まれる (zod schema 一致)
- [ ] Web `/cities/13104` に **5 セクション** (人口/住居/防災/子育て・医療/人口・移動) が描画される
- [ ] サンプル不足 (n<10) の自治体ではカードが非描画 (UI クラッシュなし)
- [ ] 出典に「不動産情報ライブラリ (国土交通省)」と「Citify 編集・加工」が表示される
- [ ] 防災カード下に「公式ハザードマップ確認」link が表示される
- [ ] **CI keyleak scanner**: `.github/workflows/lint.yml` に `gitleaks-action` ジョブが追加され、本 PR で漏洩がないことを確認
- [ ] ローカル pre-commit hook: `scripts/check-secrets.sh` が動作
- [ ] **テスト 22 件以上** (Reviewer v0.2 #10 反映):
  - 各 parser の正常系 8 + 異常系 (n<10 / 不正レスポンス) 8 + client 共通 (401/timeout/rate-limit) 3 + 5 年地価 inner join (新規/廃止除外) 3 = **22 件**
- [ ] ruff check/format + terraform fmt + next build が全 pass

### Should

- [ ] サンプル数 / 算定年度を API レスポンス含めて UI に表示 (n=45 件 / 2020→2024 等)
- [ ] 政令市の区単位データが取れない場合の親市集計 fallback ロジック
- [ ] API call 失敗時の graceful degradation (1 API 失敗でも他の 7 API は正常 UPDATE)

### Won't (本フェーズではやらない)

- GIS API 3 本 (XKT026/028/029) → Phase F v2 候補
- 残り 22 API → Phase F v3 候補
- 物件単位の地図ピン
- 賃料データ
- 全国 1795 自治体
- Cloud Run Job 化 (ローカル CLI で月 1 手動 refresh)

## 10. 工数見積もり (Reviewer v0.2 #4 で GIS Drop により圧縮)

| 工程 | 時間 |
|---|---|
| API キー Secret Manager 登録 (手動) | 5 分 |
| 政令市区単位 sample call 検証 | 30 分 |
| `scrapers/reinfolib/client.py` | 2 h |
| 8 個の parser 実装 (各 1h、GIS なしで単純 JSON 解析) | 8 h |
| `scrapers/reinfolib/__main__.py` CLI (fetch-all / load-bq / sample-call) | 2 h |
| pytest fixtures (8 API の sample JSON) + unit test 22 件 | 5 h |
| `apps/api/scripts/load_reinfolib_stats.py` (MERGE UPDATE-only) | 2 h |
| BQ schema Terraform 更新 + apply | 1 h |
| `apps/api/main.py` MunicipalityStats 拡張 (13 fields) | 1 h |
| `apps/web/src/lib/api.ts` zod schema 拡張 | 0.5 h |
| `cities/[code]/page.tsx` 5 セクション StatsCards + 倫理 UI + レスポンシブ | 3 h |
| pre-commit hook `scripts/check-secrets.sh` | 0.5 h |
| **CI keyleak scanner (`gitleaks-action` 追加)** | 0.5 h |
| ruff/format/test 通し動作確認 | 1 h |
| **合計** | **約 27 h (3.5 日)** |

> v0.2 の 36h から **GIS 3 本 Drop で 9h 削減** + Cloud Run Job 動作確認削除で 1.5h 削減、CI keyleak 追加で 0.5h 追加 → **約 27 h**。

## 11. リスクと緩和

| リスク | 影響 | 緩和策 |
|---|---|---|
| 政令市の区単位データが無い | 中 | **着手前必須**: 30 分以内で sample call、無ければ親市集計 fallback (§4.2) |
| サンプル不足の自治体が多い | 高 | n<10 は UI 非表示、45 自治体中 サンプル豊富な top 30 程度しか描画されない可能性あり (許容) |
| API キー漏洩 | 高 | Secret Manager + pre-commit + **CI gitleaks** の三重防衛 |
| **Plan A 本筋の遅れ** (Reviewer v0.1 #1) | **高** | 6/15 monitoring point 設置 (§12)、A-5 dev で 1 自治体 end-to-end pass 確認、未達なら Phase F v2/v3 を Drop |
| 利用規約変更 | 低 | §3 に確認日 + URL 明記、規約改定時に再確認 |
| 45 自治体に master.csv の `tier`/`is_active` が古い | 中 | tier1_supplements.csv の `municipality_code` を直接入力リストに使用 (master.csv 拡張は別タスク) |

## 12. 実装着手の前提 (Reviewer v0.1 #1 + v0.2 #6 完全反映)

- [x] 仕様書 v0.3.1 が作成された (§2 機械集計 patch 済)
- [x] v0.3 Reviewer 中・低指摘は Review Punchlist (§13) として保留、実装 PR で吸収
- [ ] ユーザー承認
- [ ] 政令市区単位 sample call 結果が v0.3.1 改訂履歴に記録される (着手前 30 分以内)

### 6/15 monitoring point (定量基準、Reviewer v0.2 #6 反映)

以下のいずれかを満たさない場合、**Phase F v2 (GIS) を Drop**:

- [ ] **A-5 translator が dev 環境で press_rss 由来 speech を 1 自治体分 end-to-end (Pub/Sub → BQ) で pass**
- [ ] **A-6 relevance worker が dev 環境で 80% 設計実装済 (Phase Y 5 ペルソナ fan-out)** — *既に完了確認*
- [ ] **Phase A press_rss 1038 件が BQ scored_speeches に投入完了 (今走行中)**

最後の条項 (Phase A press_rss BQ 投入) が今日中に完了見込み。これが完了すれば 6/15 monitoring 基準のうち 2 つを既に達成済となる。

## 13. Review Punchlist (実装 PR で吸収)

v0.3 Reviewer の中・低指摘で本仕様書本体に反映していない項目。実装着手時に該当 PR 内で対応する。

| # | 観点 | 指摘 | 重要度 | 実装時の対応 |
|---|---|---|---|---|
| P1 | §4.3 ハザードマップ link | 自治体中心座標の取得元が「master 拡張 / 避難所平均 / generic fallback」3 案併記で実装時に blocker | 高 | **v1 は XGT001 避難所平均座標を採用** (前提タスク不要)。実装時にこれを `parsers/xgt001.py` で計算 |
| P2 | §6 schema 列数 | 「追加 13 列」「14 fields」「16 列」「19 列」が文中混在 (v0.2 から残った揺れ) | 中 | **§6 表を SSoT** とし、実装時に main.py/zod schema で 16 列を実装 (used_apartment×2 + landprice×4 + shelter×1 + pop×2 + station×1 + childcare/medical×2 + school×2 + source/loaded_at×2) |
| P3 | §12 monitoring 達成可能性 | 「A-5 dev pass」を BQ クエリベースに verify | 中 | 実装 PR で `SELECT COUNT(*) FROM scored_speeches WHERE speech_id LIKE 'press:%'` ≥ 1 を check 条件に |
| P4 | §5 Cloud Run Job 降格の維持 | ローカル CLI 月 1 手動 refresh はハッカソン後忘却リスク | 中 | **ハッカソン提出 (7/10) 後は維持しない**を明記。提出後 1 週間以内に Cloud Scheduler 化を Phase F v2 で検討 |
| P5 | §9 Must テストカウント詳細 | 「parser 個別 + client 共通」内訳をテストファイル名レベルまで具体化 | 低 | 実装時に `test_parsers_xit001.py` 等の 8 ファイルで正常 1 + 異常 1 ずつ + `test_client.py` で 3 ケース + `test_5yr_inner_join.py` で 3 ケース |
| P6 | §改訂履歴の v0.2 行 | 改訂履歴の v0.2 行に v0.1 のレビュー判定が混入していた (v0.3 で修正済) | 低 | (v0.3.1 で再確認、問題なし) |

## 改訂履歴

- 2026-05-27 v0.1 Draft 作成 — 2 API スコープ。Reviewer 判定 Needs Improvement、高指摘 4 件 (優先順位 / 利用規約 / 対象自治体 / 5 年算定)
- 2026-05-27 v0.2 Draft 作成 — v0.1 高指摘 4 件反映 + ユーザー要求で 11 API 拡張。Reviewer 判定 Needs Improvement、Critical 1 件 (対象自治体 105 件は master.csv 未存在) + 高 2 件 (CI keyleak / GIS 工数)
- 2026-05-27 v0.3 Draft 作成 — v0.2 Critical/高 完全反映:
  - 対象自治体を Phase A 動作確認済 45 自治体に縮小
  - GIS API 3 本を v2 降格 → 8 API スコープ
  - CI gitleaks scanner を Must に追加
  - Cloud Run Job 化を Won't に降格 (ローカル CLI で月 1 手動 refresh)
  - 6/15 monitoring point に定量基準を明記
  - 工数 36h → 27h (3.5 日)
  - Reviewer 再判定 Needs Improvement、新 Critical 1 件 (§2 「45」と SQL 「43」の不整合)
- 2026-05-27 v0.3.1 Draft 作成 — v0.3 Critical 1 件を機械集計 patch:
  - §2 を `awk` 機械集計ベースに刷新 (45 件、都道府県 21 + 政令市 12 + 中核市/特別区 12 検証済)
  - scraper_type 別内訳 (press_rss 43 + voices_asp 1 + kaigiroku 1) を明示
  - 「Phase A publish-all 動作確認済 = press_rss 限定 43」と「Phase F スコープ = is_active=true 45」を区別
  - 残り Reviewer 中・低指摘 (P1-P6) を §13 Review Punchlist に集約 → 実装 PR で吸収

---

## v0.4 — 全国 1889 自治体への BQ MERGE (2026-05-30 実施、TASK-FV4MERGE)

> v0.3.1 までの対象 **45 自治体** から、Phase F v4 fetch-all で取得した **全国 9 region 別 CSV (計 1889 自治体)** に拡張し、`municipality_stats` へ一括 MERGE。「議題 × 統計が揃った街ダッシュボード」を全国規模で実現し、デモのハリボテ感を除去。

### 入力データ

`infra/seed/reinfolib_normalized_{hokkaido_tohoku,kanto,koshinetsu,hokuriku,tokai,kinki,chugoku,shikoku,kyushu_okinawa}.csv` の 9 ファイル (18 列ヘッダー同一、計 1889 行、region 跨ぎ重複コードなし)。

### スクリプト拡張 (`apps/api/scripts/load_reinfolib_stats.py`)

- `--input` を `nargs="+"` 化し、9 region CSV を **1 回の MERGE** で処理 (新規スクリプトは作らず最小拡張)
- `load_normalized_csvs(paths)` を追加: 複数 CSV を結合、同一 `municipality_code` は後勝ち (warning 付き)
- `main()` の入力存在チェックを list 対応のループに修正
- `--dry-run` に **派生 15 列の非 None 件数集計**を追加 (全 None 上書きによる既存値消失がないことの定量確認)
- 潜在バグ修正: 空 `municipality_code` 行が `"".zfill(5)="00000"` (国会コード) に化けて混入する問題を、zfill を空チェック後に回すことで解消
- unit test `apps/api/tests/test_load_reinfolib_stats.py` を新規追加 (6 件: 型変換 / None化 / zfill / 複数結合 / 後勝ち dedup / 空行 skip)

### MERGE 実行結果 (2026-05-30)

| 指標 | MERGE 前 | MERGE 後 |
|---|---|---|
| `total_rows` | 1794 | **1794** (UPDATE-only、INSERT/DELETE なし) |
| `reinfolib_filled` (`reinfolib_loaded_at IS NOT NULL`) | 45 | **1707** |
| `num_dml_affected_rows` | — | **1704** |

- CSV 1889 のうち **1704 がテーブル (1794 行) と MATCH** し UPDATE。差分 ~185 コードは `municipality_stats` に行が存在せず未 MATCH (UPDATE-only の仕様どおり skip、新規 INSERT は別タスク)
- 派生列の充足: emergency_shelter 1889/1889、population 1836、medical 1810、childcare 系 1693、apartment 価格 818
- spot check: 13104 新宿 / 27100 大阪 / 47201 那覇 / 08000 茨城 / 01100 札幌 すべて reinfolib 値あり

### 既知の課題 (フォローアップ)

- **population_2025/2050 の異常値**: 13104 (新宿区) で `population_2025_estimated=21,905,800` 等、実人口を大きく超える値。XKT013 250m メッシュ集計のバウンディングボックスが広すぎる fetch/normalize 由来の問題 (本 MERGE は CSV を忠実に反映)。**Phase F v4 fetch-all 側で要修正** (このまま UI 表示するとハリボテ感が増すため)
- 未 MATCH ~185 コードの新規 INSERT は e-Stat 行整合確認の上で別タスク
