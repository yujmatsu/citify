# Phase F — Reinfolib 統合仕様書 (不動産情報ライブラリ)

> 国土交通省「不動産情報ライブラリ」(reinfolib.mlit.go.jp) の Web API を統合し、街ダッシュボードに「住居・移住」軸の客観統計を 2 カード追加する。

- **Owner**: Yuji
- **Status**: Draft (実装前レビュー待ち)
- **作成日**: 2026-05-27
- **位置付け**: Phase D MVP の延長、Plan A の客観統計補強
- **優先度**: Should (Plan A 本筋の議事録翻訳には貢献しないが、街ダッシュボードの差別化要素)

---

## 1. 目的

Citify の街ダッシュボードに、人口・年齢構成 (Phase D) に並ぶ「**住める街か？**」を表現する数値を追加する。

具体的には:

- 中古マンション取引価格中央値 → 「この街、住むなら ¥XX 万」
- 地価 5 年変動率 → 「街の値段が上がっている/横ばい」

これにより若者ユーザーの「移住を考えるとき最初に気になる」要素 (人口 × 年齢 × 価格 × 地価動向) が同一画面で揃う。

## 2. スコープ

### MVP (Phase F v1)

- **対象 API**: XIT001 (取引価格) + XPT002 (地価公示)
- **対象自治体**: docs/FEATURES.md 受け入れ条件で **未定** (承認時に決定。Recommendation: 80 自治体 = 政令市 + 中核市 + 23区)
- **更新頻度**: 月次 (Reinfolib 自体は四半期更新だが、Citify は月 1 回手動 refresh で十分)
- **時系列**: 直近 4 四半期の中央値 (= 直近 1 年間の集計値、サンプル数で信頼性表示)

### スコープ外 (Phase F v2 以降)

- 詳細物件単位の地図ピン (個人特定リスク)
- 災害ハザードレイヤー (Phase F-Hazard として別タスク)
- 学校・医療施設位置 (e-Stat と重複)
- 賃料 (Reinfolib では取得不可、別ソース必要)

## 3. データソース仕様

### 3.1 XIT001 — 不動産取引価格情報 API

| 項目 | 値 |
|---|---|
| URL | `https://www.reinfolib.mlit.go.jp/ex-api/external/XIT001` |
| Method | GET |
| 認証ヘッダ | `Ocp-Apim-Subscription-Key: <API_KEY>` |
| 必須パラメータ | `year` (YYYY) + `quarter` (1-4) + `city` (5桁市区町村コード) または `area` (2桁都道府県) |
| 任意 | `priceClassification` (01=取引価格 / 02=成約価格), `language` (ja/en) |
| 整備範囲 | 2005 Q3 以降 |
| レート制限 | 明示なし、1 req/sec で運用 |

**主要レスポンスフィールド** (1 取引 = 1 record):

```json
{
  "Type": "中古マンション等",
  "TradePrice": "32000000",         // 取引総額 (円)
  "Area": "65",                       // 面積 (㎡)
  "UnitPrice": "492000",              // ㎡単価 (円/㎡)
  "Prefecture": "東京都",
  "Municipality": "新宿区",
  "DistrictName": "...",
  "Period": "2024年第3四半期",
  "BuildingYear": "平成12年",
  "Structure": "RC",
  "Purpose": "住宅",
  "Renovation": "未改装"
}
```

### 3.2 XPT002 — 地価公示・地価調査 API

| 項目 | 値 |
|---|---|
| URL | `https://www.reinfolib.mlit.go.jp/ex-api/external/XPT002` |
| Method | GET |
| 認証ヘッダ | 同上 |
| 必須パラメータ | `year` (YYYY) + `area` (2桁都道府県) または `city` (5桁) |

**主要レスポンスフィールド**:

```json
{
  "StandardLandNumber": "...",
  "Price": "350000",                  // 円/㎡
  "Year": "2024",
  "UseCategory": "住宅地",            // 住宅地 / 商業地 / 工業地 etc
  "Prefecture": "...",
  "Municipality": "..."
}
```

5 年変動率は本 API では取得できない → 5 年分 (`year=2020..2024`) を別途取得して計算。

## 4. アーキテクチャ

```
新規ディレクトリ: scrapers/reinfolib/
  ├─ __init__.py
  ├─ client.py     # httpx AsyncClient + Ocp-Apim-Subscription-Key + rate_limit_sec
  ├─ parser.py     # JSON → (1) 中古マンション中央値, (2) 地価平均
  ├─ schema.py     # Pydantic: RealEstateStats (1 自治体 1 record)
  ├─ __main__.py   # CLI: fetch-prices, fetch-landprice, load-bq, all
  └─ tests/
      ├─ test_client.py
      ├─ test_parser.py
      └─ fixtures/                # API response の固定 JSON

apps/api/scripts/
  └─ load_reinfolib_stats.py     # 既存 municipality_stats を ALTER して BQ 投入

apps/api/main.py
  └─ MunicipalityStats モデルに 5 フィールド追加 + _fetch_municipality_stats で同時取得

apps/web/src/lib/api.ts
  └─ MunicipalityStatsSchema に 5 フィールド追加

apps/web/src/app/cities/[code]/page.tsx
  └─ StatsCards に「🏠 中古マンション中央値」「📍 地価変動 (5 年)」を追加
  └─ 出典セクションに「+ 不動産情報ライブラリ」併記
```

## 5. BQ スキーマ拡張

既存 `citify_curated.municipality_stats` テーブルに 5 列追加:

| 列名 | 型 | NULL | 説明 |
|---|---|---|---|
| `used_apartment_median_price_man_yen` | INTEGER | YES | 中古マンション中央値 (万円)、過去 4 四半期集計 |
| `used_apartment_sample_size` | INTEGER | YES | サンプル数 (n<10 は表示しない閾値) |
| `landprice_residential_yen_per_m2` | INTEGER | YES | 住宅地平均地価 (円/㎡) |
| `landprice_change_pct_5yr` | FLOAT | YES | 住宅地 5 年変動率 (例: 2.3) |
| `reinfolib_source_url` | STRING | YES | 出典 URL (https://www.reinfolib.mlit.go.jp/) |

Terraform `google_bigquery_table.municipality_stats` の schema を更新 + 派生指標は `apps/api/scripts/load_reinfolib_stats.py` で計算。

ロード方式: WRITE_TRUNCATE で全件入れ替え (Phase D 同じパターン)。実行時は既存 e-Stat 値もマージして上書き (e-Stat ロード後に reinfolib ロードする順序、または同一スクリプトで両方ロード)。

→ **推奨**: 既存 `load_estat_stats.py` を拡張せず、別スクリプト `load_reinfolib_stats.py` で `MERGE` 構文を使い、reinfolib 由来 5 列のみ UPDATE する。

## 6. API キー管理 (新パターン導入)

### 6.1 ローカル開発

`apps/api/.env.local` (gitignore 済) に以下を追記:

```bash
REINFOLIB_API_KEY=<API_KEY>
```

`scrapers/reinfolib/client.py` で `os.getenv("REINFOLIB_API_KEY")` で読む。未設定なら起動時に明確なエラー。

### 6.2 本番 (Cloud Run / Cloud Run Job)

Secret Manager に Secret を作成:

```hcl
# infra/env/dev/main.tf
resource "google_secret_manager_secret" "reinfolib_api_key" {
  secret_id = "citify-reinfolib-api-key"
  replication {
    auto {}
  }
}
# Secret の version (= 実際の API キー値) は terraform では設定せず、ユーザーが手動で:
#   gcloud secrets versions add citify-reinfolib-api-key --data-file=- <<< "$API_KEY"
```

Cloud Run Job (workers) または Cloud Run service (api) の env で `secret_key_ref`:

```hcl
env {
  name = "REINFOLIB_API_KEY"
  value_source {
    secret_key_ref {
      secret  = google_secret_manager_secret.reinfolib_api_key.secret_id
      version = "latest"
    }
  }
}
```

runtime SA に `roles/secretmanager.secretAccessor` 付与は既存設定で OK (Phase 1 で `citify_api_runtime` に付与済)。

### 6.3 git への混入防止

- `.env.local` は既に `.gitignore` 済を確認
- pre-commit hook で `Ocp-Apim-Subscription-Key:` または典型的なキー文字列パターンを grep する hook を `scripts/check-secrets.sh` として追加 (オプション)

## 7. Frontend 統合

### 7.1 街ダッシュボードの StatsCards

既存 6 カードの後に 2 カード追加:

```
┌─────────────────────────────────────────────────────────────┐
│ 📊 街のかたち (客観統計)                       出典: e-Stat + 不動産情報ライブラリ │
├──────────────┬──────────────┬──────────────┬──────────────┤
│ 総人口       │ 15-29 歳比率 │ 5 年人口変動  │ 高齢化率 65+ │
│ 197 万人     │ 14.2%        │ -1.5%        │ 27.4%        │
├──────────────┼──────────────┼──────────────┼──────────────┤
│ 総世帯数     │ 出生率        │ 🏠 中古マンション   │ 📍 地価変動 (5年) │
│ 92 万        │ 6.5          │ ¥3,200 万           │ +2.3% (住宅地)    │
│ 2020 年       │ 人口千対 2023 │ n=45 件, 2024 年    │ 2020→2024         │
└──────────────┴──────────────┴──────────────┴──────────────┘
```

### 7.2 倫理ガードの UI 実装

| 規約 | UI 実装 |
|---|---|
| n<10 のサンプル不足は非表示 | カード自体を描画しない (`if (stats.used_apartment_sample_size >= 10)`) |
| 「安い/高い」評価 NG | カード下に注釈 `「街選びの参考値です。価値判断は含みません」` 一文 |
| 出典明示 | 「街のかたち」セクション header に出典 link を併記、カード bottom に小さく「Citify 集計値」表記 |
| 「国が作成したかのような態様」回避 | 出典 link に「不動産情報ライブラリ (国土交通省) をもとに Citify 編集・加工」を明記 |

## 8. 受け入れ条件

### Must

- [ ] `scrapers/reinfolib/__main__.py fetch-prices --city 13104 --year 2024` で新宿区の直近 4Q 中古マンション JSON が取れる
- [ ] `scrapers/reinfolib/__main__.py load-bq --munis ...` で BQ municipality_stats が 5 列更新される
- [ ] BFF `/v1/cities/13104` レスポンスの `stats` に新 5 フィールドが含まれる (Pydantic schema 更新済)
- [ ] Web `/cities/13104` の StatsCards に 2 カードが描画される (サンプル不足時は非描画)
- [ ] 出典に「不動産情報ライブラリ (国土交通省)」と link が表示される
- [ ] pytest scrapers/reinfolib/tests/ で fixture を使った unit test が 5 件以上 pass
- [ ] ruff check / format / terraform fmt / next build が全部 pass

### Should

- [ ] サンプル数 n=10 未満は API レスポンスで `null`、UI で「データ不足」表示
- [ ] API call 失敗時はログに残し、既存 e-Stat 値は壊さない (graceful degradation)
- [ ] BQ ロードは MERGE 構文で reinfolib 由来 5 列のみ更新 (e-Stat 列を壊さない)

### Won't (今フェーズではやらない)

- 物件単位の地図ピン
- 賃料データ
- ハザードマップ重ね合わせ
- 詳細価格推移グラフ (ダッシュボードは中央値 1 点のみ)

## 9. 工数見積もり

| 工程 | 時間 |
|---|---|
| API キー Secret Manager 登録 (手動) | 5 分 |
| `scrapers/reinfolib/client.py` 実装 | 2 h |
| `scrapers/reinfolib/parser.py` 実装 (中央値集計含む) | 2 h |
| `scrapers/reinfolib/__main__.py` CLI 実装 | 2 h |
| pytest fixtures + unit test | 2 h |
| `apps/api/scripts/load_reinfolib_stats.py` (MERGE) | 2 h |
| BQ schema Terraform 更新 + apply | 1 h |
| `apps/api/main.py` MunicipalityStats モデル拡張 | 1 h |
| `apps/web/src/lib/api.ts` zod schema 拡張 | 0.5 h |
| `cities/[code]/page.tsx` StatsCards 拡張 + 倫理 UI | 2 h |
| ruff/format/test 通し動作確認 | 1 h |
| **合計** | **15.5 h (約 2 日)** |

## 10. リスクと緩和

| リスク | 影響 | 緩和策 |
|---|---|---|
| API レート制限が運用上厳しい (1 req/sec でも 80 自治体 × 4Q × 2 API = 640 req = 10 分) | 中 | 1 自治体 × 1 リクエスト で並列なし、深夜実行、Cloud Run Job で 1 回完結 |
| 政令市の区単位データが無い (市単位のみ) | 中 | 1 件 sample call で確認、無ければ親市コードに集約 (例: 13101 → 13100) |
| サンプル不足の自治体が多い (地方は売買が少ない) | 高 | n<10 は UI で非表示、ダッシュボードに「データ蓄積中」と表示 |
| API キー漏洩 | 高 (アカウント停止リスク) | Secret Manager 必須、git 不混入、pre-commit hook で防衛 |
| 利用規約変更 (再配布制限の追加等) | 低 | 出典明示 + Citify 集計値表記で常に compliance、規約改定時に再確認 |

## 11. 着手判断

- [ ] **承認後に着手** (この仕様書をユーザーがレビュー → 承認)
- [ ] 着手タイミング: Phase A (press_rss) と Phase E (RSS probe) の完了を待つ or 並行
- [ ] 並行で進める場合は worker Job 走行中に着手可能 (CPU 競合なし)

## 改訂履歴

- 2026-05-27 v0.1 Draft 作成 (実装前レビュー待ち)
