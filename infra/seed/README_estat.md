# infra/seed/ — e-Stat 統計データ準備手順

Plan A Phase D 「街ダッシュボードに客観数値を載せる」で BQ `citify_curated.municipality_stats` テーブルに投入する CSV の準備手順。

## ゴール

`municipality_stats_normalized.csv` を 1 本作る。これを `apps/api/scripts/load_estat_stats.py` に渡せば BQ 投入完了。

## 正規化 CSV の期待列

```csv
municipality_code,municipality_name,prefecture,population_total,population_15_29,population_65_plus,population_2015,households_total,births_annual,data_year,source_url
01100,札幌市,北海道,1973395,310452,512345,1952356,930512,12345,2020,https://www.e-stat.go.jp/...
```

| 列 | 必須 | 説明 |
|---|---|---|
| `municipality_code` | ✓ | 5 桁 zero-pad (例: `01100`) |
| `municipality_name` | ✓ | 自治体名 |
| `prefecture` | ✓ | 都道府県名 (例: `北海道`) |
| `population_total` | — | 総人口 (2020 国勢調査) |
| `population_15_29` | — | 15-29 歳人口 (5 歳階級 3 つ合算) |
| `population_65_plus` | — | 65+ 人口 |
| `population_2015` | — | 2015 国勢調査人口 |
| `households_total` | — | 総世帯数 (2020) |
| `births_annual` | — | 年間出生数 (2023 人口動態) |
| `data_year` | — | 主データ年 (通常 2020、欠損なら自動 2020) |
| `source_url` | — | 引用元 URL |

派生指標 (`youth_share_pct` / `elderly_share_pct` / `population_change_pct` / `birth_rate_per_1000`) は **ロード時に自動計算**するので CSV に含めなくて良い。

## 元データ (e-Stat 統計表)

### 国勢調査 2020 (主データ)

- **統計表**: 「令和2年国勢調査 人口等基本集計 (男女・年齢・配偶関係,世帯の構成,住居の状態など)」
- **e-Stat URL**: <https://www.e-stat.go.jp/stat-search/files?tstat=000001136464>
- **取得方法**:
  1. e-Stat → 「データベース」→「国勢調査」→「令和2年国勢調査」→「人口等基本集計」
  2. 「市区町村別」の「年齢(5歳階級),男女別人口」CSV を DL
  3. 別に「世帯」CSV (世帯総数) を DL

### 国勢調査 2015 (5 年前比較用)

- **統計表**: 「平成27年国勢調査 人口等基本集計」 (人口総数のみで OK)
- **e-Stat URL**: <https://www.e-stat.go.jp/stat-search/files?tstat=000001080615>

### 人口動態調査 2023 (出生数)

- **統計表**: 「人口動態調査 (人口動態統計) 確定数 出生 都道府県別・市区町村別 出生数」
- **e-Stat URL**: <https://www.e-stat.go.jp/stat-search/files?tstat=000001028897>

## 準備フロー (推奨: pandas)

```python
# 任意の Jupyter Notebook or scratch script で
import pandas as pd

# 1) 国勢調査 2020 から人口・年齢階級・世帯を読む
census_2020 = pd.read_csv("FEH_00200521_*.csv", encoding="cp932", header=N)
# → 5歳階級カラム から 15-29 を合計、65+ を合計

# 2) 国勢調査 2015 から 2015 人口を読む
census_2015 = pd.read_csv(...)

# 3) 人口動態 2023 から出生数を読む
births = pd.read_csv("FEH_00450011_*.csv", encoding="cp932", ...)

# 4) municipality_code で merge
df = census_2020.merge(census_2015[["municipality_code", "population_2015"]], on="municipality_code", how="left")
df = df.merge(births[["municipality_code", "births_annual"]], on="municipality_code", how="left")

# 5) 列名を期待 schema に揃えて出力
df[[
    "municipality_code", "municipality_name", "prefecture",
    "population_total", "population_15_29", "population_65_plus",
    "population_2015", "households_total", "births_annual",
    "data_year", "source_url",
]].to_csv("infra/seed/municipality_stats_normalized.csv", index=False)
```

## BQ 投入

```bash
cd apps/api

# ドライラン (先頭 3 件 + 派生指標を確認)
.venv/bin/python -m scripts.load_estat_stats \
    --input ../../infra/seed/municipality_stats_normalized.csv \
    --dry-run

# 本投入 (WRITE_TRUNCATE で全件入れ替え)
.venv/bin/python -m scripts.load_estat_stats \
    --input ../../infra/seed/municipality_stats_normalized.csv \
    --project citify-dev \
    --dataset citify_curated \
    --table municipality_stats
```

## 検証クエリ

```sql
-- 人口上位 10 件 (sanity check)
SELECT municipality_code, municipality_name, prefecture, population_total, youth_share_pct
FROM `citify-dev.citify_curated.municipality_stats`
ORDER BY population_total DESC
LIMIT 10;

-- 若者比率上位 10 件
SELECT municipality_code, municipality_name, youth_share_pct, population_total
FROM `citify-dev.citify_curated.municipality_stats`
WHERE population_total > 50000
ORDER BY youth_share_pct DESC
LIMIT 10;
```

## 倫理メモ

- 統計は **公開データの再配布ではなく、自治体ダッシュボード表示用の参照値**として利用
- 派生指標 (出生率等) は `source_url` で元統計に必ず誘導
- 国勢調査の細かいセル (例: 100 人未満の階級) を秘匿化する必要はない (e-Stat 配布時点で集計済)
