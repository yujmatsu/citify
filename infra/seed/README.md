# infra/seed/ — Citify 自治体マスタ初期データ

Citify が使う自治体マスタの初期 CSV と、それを再生成するスクリプトを格納します。

## ファイル

| ファイル | 説明 |
|---|---|
| `municipality_master.csv` | 1,795 自治体 + 国会 1 件 = 1,796 行 (ヘッダ含む) のマスタ。**自動生成、直接編集禁止** |
| `build_municipality_master.py` | 総務省 Excel + supplements CSV からマスタ CSV を生成するスクリプト |
| `tier1_supplements.csv` | **手動メンテ**。Tier 1 自治体の `scraper_type` / `scraper_base_url` 等を上書き |
| `README.md` | このファイル |

## データソース構成 (Phase 2 以降)

```
総務省 xlsx (R6.1.1, 1794 行)
       ↓ Phase 1: 全部 unknown / tier=3 デフォルト
       ↓
tier1_supplements.csv (手動メンテ, ~30 行)
       ↓ municipality_code 一致で上書き
       ↓ scraper_type / scraper_base_url / tenant_id / tier 等
       ↓
[+ KOKKAI_RECORD] (script 内ハードコード, 1 行)
       ↓
municipality_master.csv (最終, 1796 行)
```

**設計原則**: 総務省 base data の更新と、手動 supplements の更新を独立管理。Git diff も supplements だけ追いやすい。

## 出典

### 総務省「全国地方公共団体コード」
- 公式 URL: <https://www.soumu.go.jp/denshijiti/code.html>
- 採用バージョン: **R6.1.1 (2024-01-01) 時点**
- ライセンス: 政府標準利用規約（第 2.0 版）

### tier1_supplements.csv
- 内容: Citify が Tier 1 として対応予定の自治体の scraper 情報
- 出典: Week 0 構造調査(`docs/scrapers/kaigiroku_net_recon.md`) + WebSearch によるベンダ特定
- 更新頻度: Week 2-5 で `is_active` を順次 true 化、追加自治体は Phase 3 で

## 再生成手順

```bash
# 1. 総務省サイトから Excel をダウンロード(R6.1.1 版を使用中)
#    https://www.soumu.go.jp/denshijiti/code.html

# 2. WSL 内に配置
mkdir -p /tmp/citify-week0/soumu
mv ~/Downloads/000925835.xlsx /tmp/citify-week0/soumu/

# 3. スクリプト実行 (supplements は自動で同階層を見る)
python infra/seed/build_municipality_master.py \
    --input /tmp/citify-week0/soumu/000925835.xlsx \
    --output infra/seed/municipality_master.csv

# 4. 結果確認
wc -l infra/seed/municipality_master.csv         # 1796 を期待
grep -c "^13" infra/seed/municipality_master.csv  # 東京都の市区町村数
```

## スキーマ (13 カラム、`DATA_SOURCES.md §10.2` 準拠 + Phase 2 拡張)

| カラム | 型 | 概要 |
|---|---|---|
| `municipality_code` | str(5) | 自治体コード (例: `13112`=世田谷区、`00000`=国会) |
| `name` | str | 表示用名称 (市区町村名、都道府県全体行は都道府県名) |
| `prefecture` | str | 都道府県名 |
| `kana` | str | カナ (全角化済、例: `セタガヤク`) |
| `population` | str (int) | 人口 (Phase 3 で e-Stat と統合予定) |
| `scraper_type` | str | 後述の 7 種類のいずれか |
| `scraper_base_url` | str | **新規 (Phase 2)**。スクレイピング開始 URL |
| `tenant_id` | str | kaigiroku.net SPA 系で使用、それ以外は空 |
| `press_rss_url` | str | プレスリリース RSS URL (Phase 3) |
| `opendata_url` | str | オープンデータポータル URL (Phase 3) |
| `tier` | str (int) | `1` 実装目標 / `2` 拡張対象 / `3` 余力時 |
| `is_active` | str (bool) | `true` 実装済 / `false` 計画中 |
| `notes` | str | 補足タグ、複数値は `; ` で結合 |

### scraper_type の値 (7 種)

| 値 | 系列 | 採用例 | 実装計画 |
|---|---|---|---|
| `kokkai` | 国会会議録 API | 国会 (00000) | Week 1 (A-3) |
| `kaigiroku` | **DiscussNet SPA** (Playwright 必須) | 横浜・大阪・岡山・荒川区など 7 件 | Week 2 (A-4 Plan A) |
| `voices_asp` | **voices/g07v_search.asp 系** (BeautifulSoup) | 港・台東・世田谷・札幌など 8 件 | Week 3-4 新規タスク |
| `db_search` | **DB-Search** (`*.dbsr.jp`) | 千代田・文京・江東・品川 など 4 件 | Week 5 (B-6) |
| `kensakusystem_legacy` | kensakusystem.jp 旧 HTML4 | 目黒・豊島・葛飾 など 3 件 | Phase 3 判断(優先度低) |
| `custom` | 自治体独自系 | 中央・大田・渋谷・中野・練馬 など | Week 6+ or Won't |
| `unknown` | 未調査 | 全 1,748 件のうち未補完 + 不明 23 区 5 件 | デフォルト |

### Tier 定義 (Phase 2 で再解釈)

- **Tier 1**: Citify が**実装目標とする**自治体(東京 23 区 + 政令市 + 国会 = ~44 件)
- **Tier 2**: Week 5 拡張対象 (中核市・主要地方都市、150-300 件)
- **Tier 3**: 余力時 / 対応予定なし

`tier` と `scraper_type` と `is_active` は **3 軸独立**:
- `tier`: 対応予定の優先度
- `scraper_type`: ベンダ種別
- `is_active`: 実装済か

## Phase 計画

| Phase | 期間 | スコープ |
|---|---|---|
| Phase 1 (完了) | Week 0 Day 1 (2026-05-19) | 骨組み 1,796 行を自動生成 |
| **Phase 2 (現在)** | Week 0 Day 2 (2026-05-20) | tier1_supplements.csv で 30 自治体補完、scraper_base_url カラム追加、Tier 再定義 |
| Phase 3 | Week 1-5 | 不明 23 区(5 件) の調査、Tier 2 拡張 (200 自治体)、人口統計の統合 |

## supplements の更新方針

- 新規自治体追加 → `tier1_supplements.csv` に行追加 → 再ビルド
- scraper 実装完了 → `is_active` を `false` → `true` に変更 → 再ビルド
- ベンダ判明・URL 確定 → 該当行を編集 → 再ビルド

## 検収項目 (Phase 2)

- [ ] `wc -l infra/seed/municipality_master.csv` が **1796**
- [ ] `validate()` 出力で「supplements 適用: **30 件**」「マッチ不能: **0 件**」
- [ ] scraper_type 別カウントで `kaigiroku: 7`, `voices_asp: 8`, `db_search: 4`, `kensakusystem_legacy: 3`, `custom: 5`, `unknown: 1748`(残り全部)
- [ ] `grep "^13118," infra/seed/municipality_master.csv` で荒川区が `kaigiroku` / `https://ssp.kaigiroku.net/tenant/arakawa`
- [ ] `grep "^00000," infra/seed/municipality_master.csv` で国会の `is_active=true`
