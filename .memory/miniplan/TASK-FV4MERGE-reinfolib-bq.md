# ミニプラン: Phase F v4 — Reinfolib 全国 9 region CSV を BQ municipality_stats に MERGE

## 概要

- **タスク ID**: TASK-FV4MERGE
- **目的**: Phase F v4 fetch-all で生成した全国 9 region 別 `reinfolib_normalized_*.csv` (計 1889 自治体)
  を BQ `citify-dev.citify_curated.municipality_stats` に MERGE UPDATE し、街ダッシュボード /
  ヒートマップの reinfolib 客観統計を 45 自治体 → 全国規模に拡張。「ハリボテ感」除去の一環。
- **完了条件**:
  - 9 region CSV (1889 行) が 1 回の MERGE で BQ に反映される
  - e-Stat 由来列・既存データを破壊しない (UPDATE-only 維持)
  - MERGE 前後の `reinfolib_loaded_at IS NOT NULL` 件数で反映行数を検証
  - 既存スクリプトの後方互換を保つ (単一 CSV 入力も従来通り動作)
  - load_reinfolib_stats の unit test を新規追加 (現在テストなし)
- **想定工数**: 1-1.5h

---

## 設計

### 方針: 既存 `load_reinfolib_stats.py` を複数 CSV 入力対応に最小拡張

既存スクリプトは完成度が高く UPDATE-only MERGE / 一時テーブル経由 / v3 全列対応済。
**新規スクリプトは作らず**、`--input` を `nargs="+"` 化して 9 ファイルを 1 回の MERGE で処理する。

```python
# Before
parser.add_argument("--input", type=Path, default=Path("infra/seed/reinfolib_normalized.csv"))

# After
parser.add_argument(
    "--input", type=Path, nargs="+",
    default=[Path("infra/seed/reinfolib_normalized.csv")],
    help="1 つ以上の normalized CSV (複数指定で結合してから MERGE)",
)
```

`load_normalized_csv` を複数ファイル対応にする薄いラッパー追加:

```python
def load_normalized_csvs(paths: list[Path]) -> list[dict[str, object]]:
    """複数 CSV を読み結合。同一 municipality_code は後勝ち (warning 付き)。"""
    merged: dict[str, dict[str, object]] = {}
    for p in paths:
        for row in load_normalized_csv(p):
            code = row["municipality_code"]
            if code in merged:
                logger.warning("duplicate municipality_code=%s (後勝ち) file=%s", code, p)
            merged[code] = row
    return list(merged.values())
```

`main()` は `load_normalized_csvs(args.input)` を呼ぶよう変更 (単一指定でも list で来るので互換)。

**Reviewer High #1 反映**: `main()` の入力存在チェックは現状 `args.input.exists()` だが、
`nargs="+"` で `args.input` は **list になり `.exists()` で AttributeError**。ループに修正:

```python
missing = [p for p in args.input if not p.exists()]
if missing:
    logger.error("input CSV not found: %s", missing)
    return 1
```

### 実行コマンド (9 region 一括)

```bash
cd apps/api
.venv/bin/python -m scripts.load_reinfolib_stats \
  --input ../../infra/seed/reinfolib_normalized_hokkaido_tohoku.csv \
          ../../infra/seed/reinfolib_normalized_kanto.csv \
          ../../infra/seed/reinfolib_normalized_koshinetsu.csv \
          ../../infra/seed/reinfolib_normalized_hokuriku.csv \
          ../../infra/seed/reinfolib_normalized_tokai.csv \
          ../../infra/seed/reinfolib_normalized_kinki.csv \
          ../../infra/seed/reinfolib_normalized_chugoku.csv \
          ../../infra/seed/reinfolib_normalized_shikoku.csv \
          ../../infra/seed/reinfolib_normalized_kyushu_okinawa.csv \
  --project citify-dev --dataset citify_curated --table municipality_stats \
  [--dry-run]
```

### 実行フロー (データ破壊防止のため段階実行)

1. **dry-run**: `--dry-run` で 1889 行パース + 先頭 3 行確認 (BQ 書き込みなし)
2. **MERGE 前 count**: `SELECT COUNTIF(reinfolib_loaded_at IS NOT NULL)` を記録
3. **本実行**: MERGE UPDATE → `num_dml_affected_rows` をログ確認
4. **MERGE 後 count**: 再度 count、増分が想定 (~1794 MATCH 分) と一致するか検証
5. **spot check**: 主要自治体 (13104 新宿 / 08000 茨城 / 47201 那覇) の値が入ったか確認

---

## 作業ステップ

### Phase 1 (30 分): スクリプト拡張 + テスト

1. [ ] `load_reinfolib_stats.py` の `--input` を `nargs="+"` 化
2. [ ] `load_normalized_csvs` ラッパー追加 (後勝ち dedup + warning)
3. [ ] `main()` を複数入力対応に変更
4. [ ] `apps/api/tests/test_load_reinfolib_stats.py` 新規:
   - 単一 CSV パース (int/float/str/None 変換)
   - 複数 CSV 結合
   - 重複 code 後勝ち
   - `municipality_code` zfill(5)

### Phase 2 (30 分): BQ MERGE 実行 + 検証

5. [ ] BQ 接続確認 (現在ハング中 → 復旧後に実施)
6. [ ] dry-run で 1889 行を確認 + **15 派生列 (population/medical/childcare 等) の非 None 件数を集計** (Reviewer High #2: 全 None 上書きでないこと、列が CSV に実在することを定量確認。※ヘッダー調査では 18 列に全て存在確認済)
7. [ ] MERGE 前 count 記録 (`COUNTIF(reinfolib_loaded_at IS NOT NULL)`)
8. [ ] 本 MERGE 実行 → **`num_dml_affected_rows` を主指標**に確認 (期待値 ≒ 1794 = 全テーブル行が touch される。Reviewer Medium)
9. [ ] MERGE 後 count + spot check (13104 新宿 / 08000 茨城 / 47201 那覇)
10. [ ] **冪等性確認**: 2 回目 MERGE で後 count 不変 (Reviewer Medium、任意)
11. [ ] 未 MATCH コード集計 (CSV 1889 − MATCH 件数 ≈ 95、想定内か確認)

### Phase 3 (15 分): docs + commit

12. [ ] `docs/PHASE_F_REINFOLIB_v0.3.1.md` に **v0.4 節を追記** (Reviewer Low: 新節追記で確定。「全国 1889 自治体へ拡張、9 region 一括 MERGE、複数 CSV 入力対応」)
13. [ ] `ruff format/check` + 全 backend regression
14. [ ] 推奨 commit 提示 (人間が実行)

---

## 成果物

- [ ] `apps/api/scripts/load_reinfolib_stats.py` 修正 (複数入力対応)
- [ ] `apps/api/tests/test_load_reinfolib_stats.py` 新規 (4+ test)
- [ ] BQ `municipality_stats` の reinfolib 列が全国規模で UPDATE される
- [ ] docs 追記

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| CSV 1889 vs テーブル 1794 行で ~95 コードが未 MATCH | 一部 reinfolib データが反映されない | UPDATE-only は仕様 (docs v0.3.1 §「e-Stat 行が全自治体に存在前提」)。未 MATCH コードを MERGE 後にログ集計し、想定内か確認。必要なら別途 INSERT 検討 (本タスク scope 外) |
| BQ 接続が現在ハング | MERGE 実行不可 | 環境問題 (ADC refresh / WSL network)。復旧確認後に Phase 2 実施。ユーザー shell での実行も選択肢 |
| MERGE で e-Stat 列破壊 | データロスト | UPDATE SET は reinfolib 17 列のみ列挙、e-Stat 列は触らない (既存設計のまま) |
| WRITE_TRUNCATE で一時テーブル誤爆 | — | 書き込みは `_tmp_reinfolib_load` のみ、本テーブルは MERGE のみ。実行後 drop |
| 重複 code (region 跨ぎ) | 後勝ちで意図せぬ上書き | 調査済: 9 CSV 間に重複コードなし。念のため dedup + warning |

---

## Out of Scope

- 未 MATCH ~95 コードの新規 INSERT (別タスク、要 e-Stat 行整合確認)
- Frontend 表示拡張 (既存 reinfolib カード UI は自治体コード次第で自動表示)
- reinfolib fetch-all 自体 (タスク 7、別途進行中)
- BQ 接続ハングの根本調査 (環境問題)
