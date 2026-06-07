# ミニプラン: TASK-CITYDATA — 街カルテ指標拡充 (SSDS 8指標追加)

## 概要
- **タスクID**: TASK-CITYDATA(TASK-FISCAL の拡張、設計B 派生)
- **目的**: 街の状況把握に効く指標を SSDS(00200502)から追加取得し街カルテに表示。
  併せて医療施設数4909件(reinfolibスケールずれ)を SSDS の信頼値に置換。
- **完了条件**: 8指標が municipality_stats に入り、/cities/[code] に「街の詳細データ」として表示。pytest/tsc/build green。

## 追加8指標 (列名 / 計算 / SSDSコード)
| 列 | 計算 | コード(statsDataId) |
|---|---|---|
| `doctors_per_100k` (FLOAT) | 医師数 ÷ 総人口 × 100000 | I6100 / A1101 (020209/020201) |
| `ssds_hospital_count` (INT) | 病院数(直値) | I5101 (020209) |
| `unemployment_rate_pct` (FLOAT) | 完全失業者 ÷ 労働力人口 × 100 | F1107 / F1101 (020206) |
| `tertiary_industry_pct` (FLOAT) | 第3次産業就業者 ÷ 就業者数 × 100 | F2221 / F1102 (020206) |
| `dwelling_area_sqm` (FLOAT) | 1住宅当たり延べ面積(直値) | H2130 (020208) |
| `day_night_pop_ratio` (FLOAT) | 昼夜間人口比率(直値) | A6108 (020201) |
| `school_count` (INT) | 小学校 + 中学校(合算) | E2101 + E3101 (020205) |
| `nursery_children` (INT) | 保育所等在所児数(詳細票、直値) | J2506 (020210) |
+ メタは既存 ssds_data_year/source/loaded_at を流用。

## 作業ステップ
1. [ ] `ssds_config.json` に raw 項目追加(hospitals/doctors/labor_force/unemployed/employed/tertiary/dwelling_area/day_night/elementary/junior/nursery、population は既存)
2. [ ] `fetch_ssds_indicators.py` cmd_fetch: 上記8列を計算して CSV 出力(派生計算を追加)
3. [ ] fetch 実行 → `infra/seed/ssds_indicators_normalized.csv` 再生成(財政5 + 新8 = 13指標列)
4. [ ] `infra/env/dev/main.tf` municipality_stats に8列追加(fmt)
5. [ ] `load_ssds_stats.py` に8列の parse + schema + MERGE 追加(+test)
6. [ ] `apps/api/main.py` MunicipalityStats + city SQL に8列、api.ts schema 追加
7. [ ] 街カルテ /cities に「街の詳細データ」セクション。医療施設数4909は ssds_hospital_count/doctors に置換表示
8. [ ] 検証(ruff/pytest/tsc/build)

## デプロイ (ユーザー)
commit/push → terraform apply(列追加)→ load_ssds_stats(MERGE)→ 自動API/webデプロイ

## リスク
| リスク | 対策 |
|---|---|
| カバレッジ欠損(住調・福祉系は標本/未収録あり) | graceful null。値ある自治体のみ表示 |
| 派生の分母0/欠損 | None ガード(財政の per-capita と同方式) |
| STATUS=2 を異常扱い | fetch の _api_call は 0/1/2 を正常に(堅牢化) |
| 列増で loader/SQL 修正漏れ | 13指標を1リストで管理しテスト |
