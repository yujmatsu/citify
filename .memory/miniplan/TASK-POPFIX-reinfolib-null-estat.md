# ミニプラン: reinfolib population 異常値の NULL化 + e-Stat 採用 (TASK-POPFIX)

## 概要

- **タスク ID**: TASK-POPFIX
- **目的**: XKT013 (z=11 50km四方メッシュ合算) 由来の `population_2025/2050_estimated` /
  `population_change_2025_2050_pct` が全国 88% で実人口の 2倍超 (最悪 2870倍) という異常値。
  デモのハリボテ感を除去するため、これらを **NULL化** し、表示・分析は **正確な e-Stat**
  (`population_total` / `population_change_pct`) に張り替える。
- **ユーザー承認**: AskUserQuestion で「Option B: 異常列をNULL化+e-Stat採用」を選択済
- **完了条件**:
  - BQ `municipality_stats` の reinfolib population 3 列が全行 NULL
  - `load_reinfolib_stats.py` が当該 3 列を二度と書き込まない (durability)
  - heatmap「税」「移住」軸が e-Stat `population_change_pct` に張り替わり空にならない
  - Concierge の成長フィルタ・表示が e-Stat `population_change_pct` を使用
  - city ダッシュボードの「2050年予測人口」カードは NULL で自動非表示 (改修不要)、総人口は e-Stat 継続表示
  - 全 backend regression green + 関連テスト更新
- **想定工数**: 2h (Reviewer 指摘で main.py/prompt/demo_concierge/frontend 追加)

## 調査で確定した事実

| 事実 | 値 |
|---|---|
| reinfolib pop が e-Stat の 2倍超 | 1467/1662 (88%)、最悪 14402 で 2870倍 |
| e-Stat `population_total` 充足 | 1787/1794 (正確、総人口表示に使用中) |
| e-Stat `population_change_pct` 充足 | 1782/1794、外れ値は福島被災 3 件のみ (実データ) |
| UI 2050カード | 両値 non-null の時のみ表示 → NULL で自動非表示 (改修不要) |
| heatmap で broken列使用 | 「税」「移住」軸 = `population_change_2025_2050_pct` |
| concierge で broken列使用 | 成長フィルタ(L84) + 表示(L122/142/166/185) + schema(L84) |

## 設計

### 1. BQ NULL化 (一度きりの UPDATE)

```sql
UPDATE `citify-dev.citify_curated.municipality_stats`
SET population_2025_estimated = NULL,
    population_2050_estimated = NULL,
    population_change_2025_2050_pct = NULL
WHERE TRUE;
```

### 2. load_reinfolib_stats.py — durability (3列を恒久的に書かない)

- `_REINFOLIB_COLUMNS` から 3 列を除外 (コメントで XKT013 廃止理由を明記)
- `load_normalized_csv` の row dict から `population_2025_estimated/2050/change` を除外
- `write_to_bq` の schema (SchemaField 3つ) + MERGE SET 3行を削除
- dry-run の派生列集計から population 系を除外
- → CSV にこれらの列が残っていても **無視** される (再 MERGE で異常値が戻らない)
- test_load_reinfolib_stats: population 列を assert しないよう更新

### 3. heatmap 系 — e-Stat 張り替え (Reviewer Critical/High 反映、3ファイル同時必須)

- **heatmap_advisor/main.py**: 「税」「移住」の HeatmapMetricSpec を
  `column="population_change_pct"`, `label_ja="人口増減率 (直近国勢調査)"` に張り替え
- **apps/api/main.py (Critical#1)**: heatmap `allowed_columns` allowlist の
  `population_change_2025_2050_pct` → `population_change_pct` に張り替え
  (放置すると新 column が allowlist に無く **ValueError で heatmap が落ちる**)
- **heatmap_advisor/prompts/system.py (High#3) L69**: LLM 提示の利用可能 column 説明を
  `population_change_pct (人口増減率、直近国勢調査)` に更新 (旧名だと LLM が NULL 列を選ぶ)
- test_advisor: column 名参照を更新

### 4. concierge 系 — e-Stat 張り替え (Reviewer High#4 反映)

- **tools.py**: `population_change_2025_2050_pct` → `population_change_pct` に全置換
  (SQL SELECT / WHERE フィルタ L84 / 表示 L122,142,185 / candidate マッピング L166)。
  併せて未使用の `population_2025_estimated/2050_estimated` を SELECT から除去 (Medium#6)
- **schema.py `MunicipalityCandidate`**: フィールド名 `population_change_2025_2050_pct`
  → `population_change_pct` にリネーム
- **agents/demo_concierge.py (High#4) L160/173/190**: `MunicipalityCandidate(...)` の
  kwarg 名を `population_change_pct` にリネーム (放置で TypeError、デモ起動不能)
- **frontend (High#5)**: `apps/web/src/lib/api.ts` の Candidate schema (L381) を
  `population_change_pct` にリネーム。MunicipalityStats 側 (L312-314) は API が旧名 null を
  返すため残置可 (整合性のため方針明記)
- test_tools: 参照更新

### 5. apps/api/main.py City Dashboard (Reviewer Critical#2)

- `get_stats` の SELECT (L615-640) / マッピング (L674-676) / `MunicipalityStats` モデル
  (L519-525) は 3 列を引き続き serve するが、NULL化後は **null を返すだけで動作は壊れない**。
- 最小対応: 残置 (null 返却) で OK と明記。2050カード (page.tsx L334-345) は両列 null で自動非表示。
- (任意 clean: SELECT/モデルからも 3 列除去 — 本タスクでは残置)

### 6. UI city ダッシュボード

- 改修不要 (NULL で 2050カード自動非表示)。確認のみ。

## 作業ステップ

### Phase 1 (75分): コード修正 + テスト
1. [ ] load_reinfolib_stats.py: 3列除外 (schema/parse/MERGE/dry-run)
2. [ ] test_load_reinfolib_stats.py 更新
3. [ ] heatmap_advisor/main.py: 税・移住 を population_change_pct に張り替え
4. [ ] **apps/api/main.py heatmap allowlist** を population_change_pct に張り替え (Critical#1)
5. [ ] **heatmap_advisor/prompts/system.py L69** の column 説明更新 (High#3)
6. [ ] test_advisor.py 更新
7. [ ] concierge tools.py + schema.py: population_change_pct に張り替え/リネーム
8. [ ] **agents/demo_concierge.py** の kwarg リネーム (High#4)
9. [ ] test_tools.py 更新 + frontend api.ts (Candidate L381) + cities page.tsx 追従

### Phase 2 (20分): BQ NULL化 + 検証
10. [ ] UPDATE で 3列 NULL化 (SSL_CERT_FILE + sandbox off)
11. [ ] 検証: 3列の non-null 件数が 0、population_total/change_pct は不変
12. [ ] heatmap endpoint smoke (税/移住 で 200 + 非空) で allowlist 落ちが無いことを確認 (Medium#7)

### Phase 3 (25分): docs + regression + commit
10. [ ] docs/PHASE_F_REINFOLIB_v0.3.1.md v0.4 節に「population は e-Stat を SSoT 化、reinfolib XKT013 は廃止」追記
11. [ ] docs/AGENT_PROMPTS.md heatmap 節の指標表を更新
12. [ ] ruff format/check + 全 backend regression
13. [ ] 推奨 commit 提示

## 成果物
- [ ] apps/api/scripts/load_reinfolib_stats.py (3列除外)
- [ ] apps/api/tests/test_load_reinfolib_stats.py (更新)
- [ ] agents/heatmap_advisor/main.py + tests (張り替え)
- [ ] agents/concierge/tools.py + schema.py + tests (張り替え)
- [ ] apps/web/src/lib/api.ts (concierge field 名追従、必要なら)
- [ ] BQ 3列 NULL化
- [ ] docs 2 ファイル更新

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| concierge schema rename で frontend 型ズレ | concierge UI 崩れ | api.ts の concierge candidate schema を同時更新、grep で漏れ確認 |
| e-Stat population_change_pct の福島 3 外れ値 | heatmap 色スケール歪み | 実データなので許容。heatmap は percentile 正規化なら影響軽微。気になれば後続で clamp |
| XKT013 fetch (scrapers/reinfolib) が孤児化 | 死にコード | 本タスクでは fetch コードは残す (削除は別タスク)。docs に廃止明記 |
| BQ UPDATE の取り消し | 不可逆 | population_2025/2050 は元々 reinfolib 由来で再生成可能 (CSV に原値あり)。e-Stat 列は触らない |

## Out of Scope
- XKT013 parser の SHICODE 絞り込み修正 + 再 fetch (将来 2050 予測を正しく復活させる別タスク)
- 福島 3 外れ値の clamp/winsorize
- scrapers/reinfolib/parsers/xkt013.py 自体の削除
