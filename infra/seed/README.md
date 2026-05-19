# infra/seed/ — Citify 自治体マスタ初期データ

Citify が使う自治体マスタの初期 CSV と、それを再生成するスクリプトを格納します。

## ファイル

| ファイル | 説明 |
|---|---|
| `municipality_master.csv` | 1,795 自治体 + 国会 1 件 = 1,796 行 (ヘッダ含む) のマスタ |
| `build_municipality_master.py` | 総務省 Excel から CSV を生成するスクリプト |
| `README.md` | このファイル |

## 出典

総務省「全国地方公共団体コード」

- 公式 URL: <https://www.soumu.go.jp/denshijiti/code.html>
- 採用バージョン: **R6.1.1 (2024-01-01) 時点** (Phase 1 初版)
- ライセンス: 政府標準利用規約（第 2.0 版）

> Phase 2 以降で最新版に差し替える場合は、同じスクリプトで再生成可能（ヘッダ・シート名が同一である限り）。

## 再生成手順

```bash
# 1. 総務省サイトから最新の Excel をダウンロード
#    https://www.soumu.go.jp/denshijiti/code.html
#    → 「都道府県コード及び市区町村コード」を保存

# 2. WSL 内に配置
mkdir -p /tmp/citify-week0/soumu
mv ~/Downloads/000925835.xlsx /tmp/citify-week0/soumu/

# 3. スクリプトを実行
python infra/seed/build_municipality_master.py \
    --input /tmp/citify-week0/soumu/000925835.xlsx \
    --output infra/seed/municipality_master.csv

# 4. 結果を確認
wc -l infra/seed/municipality_master.csv         # 1796 を期待
head -5 infra/seed/municipality_master.csv
grep -c "prefecture_aggregate" infra/seed/municipality_master.csv  # 47 を期待
```

## スキーマ

`DATA_SOURCES.md §10.2` 準拠。

| カラム | 型 | Phase 1 の埋め方 | 説明 |
|---|---|---|---|
| `municipality_code` | str(5) | 総務省 6 桁の頭 5 桁 | 自治体コード (例: `13112`= 世田谷区、`00000`=国会) |
| `name` | str | 市区町村名、都道府県全体行は都道府県名 | 表示用名称 |
| `prefecture` | str | 都道府県名 | — |
| `kana` | str | 全角化済 (NFKC 正規化) | 例: `セタガヤク` |
| `population` | str (int) | 空文字 | Phase 2 で e-Stat と統合予定 |
| `scraper_type` | str | `unknown` (国会のみ `kokkai`) | `kokkai`/`kaigiroku`/`db_search`/`unknown`/`none` |
| `tenant_id` | str | 空文字 | kaigiroku.net の tenant ID (Phase 2 で補完) |
| `press_rss_url` | str | 空文字 | プレスリリース RSS URL (Phase 2) |
| `opendata_url` | str | 空文字 | オープンデータポータル URL (Phase 3) |
| `tier` | str (int) | `3` (国会のみ `1`) | `1` 最優先 / `2` Week 5 拡張 / `3` 余力時 |
| `is_active` | str (bool) | `false` (国会のみ `true`) | スクレイピング対象か |
| `notes` | str | 都道府県全体行は `prefecture_aggregate` | 補足タグ |

## Phase 計画

| Phase | 期間 | スコープ |
|---|---|---|
| **Phase 1** (本実装) | Week 0 | 1,796 行を自動生成。Tier=3 / scraper_type=unknown で固定 |
| Phase 2 | Week 0-1 末 or Week 5 | Tier 1 自治体 50 件を手動補完 (`tenant_id`, `press_rss_url`, `scraper_type`) |
| Phase 3 | Week 5 | Tier 2/3 拡張 (200〜500 自治体)、人口統計の統合 |

## 検収項目（Phase 1）

スクリプト実行後、以下を満たせば合格:

- [ ] `wc -l` の結果が **1796**
- [ ] 1 行目が CSV ヘッダ、2 行目が `00000,国会,...`
- [ ] `grep -c "prefecture_aggregate"` が **47**
- [ ] `head -10` で全 `municipality_code` が **5 桁ゼロパディング**
- [ ] 文字化けなし（カナが全角になっている: `ホッカイドウ` であって `ﾎｯｶｲﾄﾞｳ` でない）
