# Citify 作業ログ

## 2026-05-19 (Mon) Session 1 — Week 0 Day 1

### Completed

- [x] 設計ドキュメント整備の現状確認(`CLAUDE.md` / `AGENTS.md` / `docs/PROJECT.md` / `docs/FEATURES.md` / `docs/SCHEDULE.md` / `docs/ARCHITECTURE.md` / `docs/DATA_SOURCES.md` がコミット済であることを検証)
- [x] **国会会議録 API 動作確認** — `https://kokkai.ndl.go.jp/api/speech` を curl で 5 ステップ検証
  - C1 (200 + 有効 JSON): PASS
  - C2 (件数 > 0): PASS — `any=家賃補助` で 942 件ヒット
  - C3 (実日本語テキスト): PASS — 衆議院予算委員会 長友議員の家賃補助議論を確認
  - C4 (連続リクエスト): サーバ応答時間 0.2-0.4 秒で安定、レート制限の気配なし
  - サンプル JSON を `/tmp/citify-week0/kokkai_sample_yachin_hojo.json` に保存
  - **発見**: 発言文字数は平均 2,555 字、最大 52,304 字、最小 147 字 → 翻訳 Agent (A-5) は議題単位 chunking 必須
  - 直近 30 日で 506 発言 → RAG 投入規模は軽量
- [x] **ハッカソン参加登録(Findy Conference)** 完了 (Yuji 側で実施済み確認)
- [x] **Proto Pedia アカウント作成** 完了 (Yuji 側で実施済み確認)
- [x] **自治体マスタ CSV Phase 1** 完成
  - `infra/seed/build_municipality_master.py` 作成 (総務省 xlsx → Citify スキーマ変換)
  - `infra/seed/README.md` 作成 (出典・スキーマ・再生成手順・Phase 計画)
  - `infra/seed/municipality_master.csv` 生成 — 1,796 行 (ヘッダ + 国会 1 + 都道府県 47 + 市区町村 1,747)
  - 検収全項目 PASS (世田谷区 13112、札幌市 01100、国会 00000 すべて存在確認、カナ全角化 OK)
  - 入力: 総務省 R6.1.1 (2024-01-01 時点) 版 `000925835.xlsx`

### Decisions / Design Notes

- **自治体コード**: 総務省 6 桁の頭 5 桁を採用(チェックデジット除く)。`DATA_SOURCES.md §10.3` サンプル準拠
- **都道府県全体行 47 件**: 削除せず `notes='prefecture_aggregate'` で区別。B-7 プレス RSS が都道府県単位を扱うため
- **カナ**: `unicodedata.normalize('NFKC')` で半角→全角化
- **国会レコード**: `00000 / 国会 / 国 / コッカイ` を CSV 先頭に固定挿入、scraper_type=kokkai / tier=1 / is_active=true

### Environment Issues

- **Claude Code Bash サンドボックスがこのセッションで起動不能** (`bwrap: Can't create file at /mnt/c/Program Files/ClaudeCode/managed-settings.d`)。curl・gh・git・python の直接実行は不可、Yuji 側ターミナルで実行する運用に切替
- **WSL Windows Terminal が多行ヒアコードを破壊** (全角コメント + 多行 paste で末尾 1-3 行が連結 or 欠落)。複数行 Python は `-c "..."` 単行コマンドか、VSCode エディタで `.py` ファイル作成のいずれかで回避

### Pending Verifications

- C4 をパラメタ完備で 5 連射再テスト(任意、すでにサーバ応答は安定確認済)

### Next (Week 0 残タスク、次セッション以降)

優先順:

1. **DiscussNetPremium 構造調査** (2-3h) — A-4 のリスク早期発見。setagaya / yokohama 等 2-3 自治体で HTML 構造観察。Must タスクの実装可能性確認
2. **GCP プロジェクト作成 + API 有効化** (1-2h) — Cloud Run / Firestore / BigQuery / Vertex AI / Pub/Sub / Secret Manager の有効化。Week 1 Terraform 着手前に必要
3. **自治体マスタ Phase 2 着手** (Tier 1 自治体 50 件の `tenant_id` / `press_rss_url` 手動補完) — Week 1 と並行可

### Commit Reminder

未コミット変更:

- `infra/seed/build_municipality_master.py`
- `infra/seed/README.md`
- `infra/seed/municipality_master.csv`
- `log.md` (このファイル)

推奨コミット:
```bash
git add infra/seed/ log.md
git commit -m "feat(seed): add municipality master CSV (Phase 1, 1796 rows)"
git push origin main
```

---
