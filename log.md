# Citify 作業ログ

## 2026-05-20 (Tue) Session 4 — 自治体マスタ Phase 2 (Tier 1 補完 + 戦略再構築)

### Completed

- [x] **東京 23 区の議事録システムをベンダ別に分類** (WebSearch 7 件 + Yuji curl 1 件)
  - **重要発見 1**: `kensakusystem.jp/{区名}/` は **旧 HTML4 別実装**(SPA でなく BeautifulSoup でパース可)。同じ会議録研究所系列だが、新版 DiscussNet とは別物
  - **重要発見 2**: 23 区中 **DiscussNet SPA で取れるのは 荒川区のみ**(`ssp.kaigiroku.net/tenant/arakawa`)
  - 23 区のベンダ分布:
    - DiscussNet SPA: 1 (荒川区)
    - voices/asp 系 (gijiroku.com): 7 (港・台東・世田谷・杉並・板橋・足立・江戸川)
    - DB-Search 系 (*.dbsr.jp): 4 (千代田・文京・江東・品川)
    - kensakusystem.jp 旧 HTML4: 3 (目黒・豊島・葛飾)
    - 独自/不明: 5 + 3 (中央・大田・渋谷・中野・練馬 + 新宿・墨田・北)
- [x] **戦略判断: A-4 + voices/asp + DB-Search の 3 系統並行実装** に決定
  - Yuji 判断、ハッカソン期間ギリギリだが「全国 800 自治体カバー」の dream を守る
  - 実装工数 +5-7 日見込み、ただし voices/asp と DB-Search は静的 HTML なので BeautifulSoup で容易
- [x] **`infra/seed/tier1_supplements.csv` 新規作成** (30 行) — Tier 1 自治体の `scraper_type` / `scraper_base_url` / `tenant_id` を手動補完
- [x] **`build_municipality_master.py` を supplements マージ対応に拡張** — `load_supplements()` + `apply_supplements()` 追加、`notes` は append、フィールドは override
- [x] **`scraper_base_url` カラムを CSV スキーマに追加** (12 → 13 カラム)
- [x] **`KOKKAI_RECORD` を scraper_base_url 対応 + notes に "国会会議録 (kokkai.ndl.go.jp/api/speech)" 追記**
- [x] **`infra/seed/README.md` を全面改訂** — scraper_type の 7 種類定義、Tier 再定義(対応予定の優先度、scraper_type と独立)、Phase 計画更新
- [x] **CSV 再生成 & 検収** — 1796 行、supplements 30 件全マッチ、scraper_type 7 種類の分布想定通り
  - kaigiroku: 7、voices_asp: 8、db_search: 4、kensakusystem_legacy: 3、custom: 5、kokkai: 1、unknown: 1767

### Decisions / Design Notes

- **配信モデル 7 分類確定**: kokkai / kaigiroku / voices_asp / db_search / kensakusystem_legacy / custom / unknown
- **Tier 軸の再解釈**: tier = 「実装目標の優先度」、scraper_type = 「ベンダ種別」、is_active = 「実装済か」 の 3 軸独立
- **supplements の運用方針**: `municipality_code` をキーに base レコードを override、`notes` は append (`base; supp` の形)、identity 系 (name/prefecture/kana/population) は override 不可
- **国会の扱い**: 引き続きスクリプト内 `KOKKAI_RECORD` でハードコード(`tier=1, is_active=true`)、supplements には載せない(municipality_code 00000 は base にないため)
- **Tier 1 のメンバ**: 国会(1) + 東京 23 区(23) + 政令市等(6: 横浜・大阪市・大阪府・岡山県・高知県・大分県) + 札幌市(1, voices_asp 系) = **31 件**

### Surprises / Risks

- **23 区の議事録ベンダが想像以上に散乱** — 「東京 23 区カバー」のアピールには DiscussNet 1 系統では完全に足りず、最低でも voices/asp 系が必要
- **kensakusystem.jp の robots.txt が 404** — 利用規約が明確でない。Phase 3 で実装判断時に NTT-AT/議事録発行センターに直接確認した方が安全
- **不明 5 区(中央以外: 新宿・墨田・北・大田・練馬)** — Phase 3 で WebSearch + 個別 curl で追加調査必要
- **DiscussNet SPA (Playwright 必須) と voices/asp / DB-Search (BeautifulSoup でOK) のインフラ要件が違う** — Cloud Run のメモリ・コンテナサイズの 2 構成を維持する必要

### Tier 1 / scraper_type 分布(最終)

```
                Tier 1 (31)
                 ├── kokkai (1)         国会
                 ├── kaigiroku (7)      横浜・大阪市・大阪府・岡山県・高知県・大分県・荒川区
                 ├── voices_asp (8)     港・台東・世田谷・杉並・板橋・足立・江戸川・札幌
                 ├── db_search (4)      千代田・文京・江東・品川
                 ├── kensakusystem (3)  目黒・豊島・葛飾
                 └── custom (5) + unknown (3)
                                        中央・大田・渋谷・中野・練馬 + 新宿・墨田・北
```

### Next (Week 1 着手前の残タスク or 着手)

優先順:

1. **Week 1 Day 1 雛形作成** — FastAPI / Dockerfile / Terraform / GitHub Actions 雛形。先取りすれば 5/26 月曜から機能実装に直行可能
2. **`docs/scrapers/voices_asp_recon.md`** — voices/asp 系の構造調査。実装可能性確認(Week 3-4 で着手予定の前哨)
3. **`docs/DATA_SOURCES.md` 追加更新** — scraper_type の 7 分類を §2 に反映、`voices_asp` 系・`db_search` 系・`kensakusystem_legacy` のセクション追加
4. **不明 5 区の追加調査** (新宿・墨田・北・大田・練馬) — WebSearch + curl で確定

### Commit Reminder

未コミット変更:

- `infra/seed/tier1_supplements.csv` (新規、30 行)
- `infra/seed/build_municipality_master.py` (supplements マージ機能追加)
- `infra/seed/municipality_master.csv` (再生成、scraper_base_url カラム追加 + 30 件補完反映)
- `infra/seed/README.md` (全面改訂、scraper_type 7 種定義・Tier 再定義)
- `log.md` (このファイル)

推奨コミット:
```bash
git add infra/seed/ log.md
git status   # 5 ファイル staged + 想定外がないか確認
git commit -m "feat(seed): Phase 2 — Tier 1 supplements (30 self-gov, 5-vendor classification)"
git push origin main
```

---

## 2026-05-20 (Tue) Session 3 — GCP プロジェクト立ち上げ

### Completed

- [x] **GCP プロジェクト `citify-dev` 作成** (Phase 1-5、所要 ~30 分)
  - Phase 1: gcloud SDK 566.0.0 確認、`yujmatsu@gmail.com` 認証済
  - Phase 2: `citify-dev` 作成、請求アカウント `01A6C1-923A4E-0676C4` (OPEN: True) link、リージョン `asia-northeast1` (Tokyo) 設定 (compute / run / artifacts 全部)
  - Phase 3: 必要 API **14 個一括有効化** (run, cloudbuild, artifactregistry, aiplatform, documentai, firestore, bigquery, storage, pubsub, cloudscheduler, secretmanager, logging, cloudtrace, iamcredentials)、依存関係で計 23 個 enabled。ADC のクォータプロジェクトを citify-dev に向け直し
  - Phase 4: **予算アラート ¥7,500/月、4 段階** (50%/90%/100% actual + 100% forecasted) 作成。$50 → JPY 7500 に修正(請求アカウントが JPY ベースのため)
  - Phase 5: **サンプル Cloud Run デプロイ成功** — `gcr.io/cloudrun/hello` を `hello-citify` として asia-northeast1 にデプロイ、curl で 200 / 360ms 確認
- [x] **Week 0 終了時判定基準 4/4 すべて達成** 🎯
  - ✅ ドキュメント 4-6 個が GitHub にコミット (Day 1)
  - ✅ 国会 API から 1 件以上の発言が取れる (Day 1)
  - ✅ DiscussNetPremium の HTML 構造把握 (Day 2)
  - ✅ **GCP プロジェクトでサンプル Cloud Run がデプロイできる** (Day 2 Session 3)

### Decisions / Design Notes

- **プロジェクト名**: `citify-dev` (Week 5+ で `citify-prod` を追加予定)
- **プロジェクト番号**: `46070204654` (Terraform / IAM binding で参照する場面で使用)
- **リージョン統一**: `asia-northeast1` (Tokyo) を compute / run / artifacts 全部で固定。マルチリージョン非採用
- **請求通貨**: JPY 固定(請求アカウントの仕様、USD 指定だと `INVALID_ARGUMENT`)
- **予算ライン**: ¥7,500/月(約 $50)、超過時の挙動は計測のみ(自動停止はなし)。Veo/Imagen 多用で超える可能性は Week 4 以降
- **デプロイ済サービス**: `hello-citify` は idle 課金なし、Week 1 で `citify-api` に上書きまたは削除予定

### Surprises / Risks

- **request 通貨ミスマッチ**: 最初 `--budget-amount=50USD` で `INVALID_ARGUMENT` 発生 → 請求アカウントが JPY ベースで USD 不可。同様の罠は Terraform 設計時の `google_billing_budget` リソースでも要注意
- **ADC quota project 警告**: 古いプロジェクト (`hackason-grab`) のクォータ参照を `citify-dev` に向け直し。これを忘れると Python SDK の課金が別プロジェクトに行く事故が起きる
- **Service URL の 2 形式**: gcloud deploy 出力は `hello-citify-{プロジェクト番号}.asia-northeast1.run.app`、`describe` は `hello-citify-{hash}-an.a.run.app` を返す → 両方とも有効、Cloud Run の URL エイリアス仕様

### Next (Week 0 残タスク → Week 1 着手準備)

優先順:

1. **自治体マスタ Phase 2 設計** — 今回判明した 3 配信モデル(中央型/白ラベル/別ベンダ)を吸収する `scraper_base_url` カラム追加マイグレーションの計画。Tier 1 自治体 50 件の手動補完 (`tenant_id`, `press_rss_url`)
2. **`docs/scrapers/voices_asp_recon.md`** — 別ベンダ系(札幌市・世田谷区) の予備調査。Tier 1 候補から漏れる影響範囲が大きい場合のみ
3. **Week 1 着手 (5/26 月-)** — Terraform 雛形、FastAPI 雛形、Cloud Run + Cloud Build 自動デプロイパイプライン、国会 API クライアント実装、Vertex AI RAG セットアップ

### Commit Reminder

未コミット変更:

- `log.md` (このファイル) — 唯一の差分

> 補足: GCP セットアップは外部リソース変更で、リポジトリ側にはコード生成なし(`hello-citify` は外部状態としてのみ存在)。Terraform 化は Week 1 で実施

推奨コミット:
```bash
git add log.md
git commit -m "docs: GCP project citify-dev set up + Week 0 milestones cleared"
git push origin main
```

---

## 2026-05-20 (Tue) Session 2 — Week 0 Day 2

### Completed

- [x] **DiscussNet (kaigiroku.net) 構造調査 — 重大発見の連続**
  - robots.txt 取得 → `/tenant/` 配下のみ Allow、`/dnp/` 含む他は Disallow
  - 当初想定 (`ssp.kaigiroku.net/tenant/{id}/SpTop.html`) は 5 自治体中 3 自治体で 404 → 仮説崩壊
  - WebSearch + 実地調査で **3 種類の配信モデル** が判明:
    - **中央型** (`ssp.kaigiroku.net/tenant/{id}/`) — 大阪市、岡山県、高知県等
    - **白ラベル型** — 横浜市 (`giji.city.yokohama.lg.jp`)
    - **別ベンダ型(対象外)** — 札幌市、世田谷区 (`*.gijiroku.com/voices/*.asp` 系)
  - 採用自治体数: **350+ → 540** (2025/7 時点、株式会社会議録研究所公表) と判明、`DATA_SOURCES.md` 修正
- [x] **DiscussNet 内部アーキテクチャの解明** — DevTools 観察で判明:
  - 全 Search/Browse ページは **SPA (Single Page Application)** — `<tbody id="council_list">` は空、JS で動的描画
  - 内部 API: `/dnp/search/councils/{index|get_view_years|get_layout|get_permission}` — **POST + Cookie + CSRF + JSONP**
  - **直接 API コールは robots.txt の Disallow `/dnp/` 違反**
  - **Playwright + headless Chromium 必須** という結論
- [x] **A-4 判定: 🟡 YELLOW (Playwright 必須) — Plan A 採用決定**
  - Plan A (Playwright): インフラ +$0-5/月、コンテナ +400 MB、実装工数 +1.5-2 日
  - Drop Point: Week 2 中日 (6/4 水) で Playwright が動かなければ Plan B (A-4 を Should 降格、国会 API + プレス RSS のみ) に切替
- [x] **`docs/scrapers/kaigiroku_net_recon.md` を観察結果で全面書き直し** (約 200 行、判定根拠 + Drop Point ルール + Week 2 実装計画含む)
- [x] **`docs/DATA_SOURCES.md §2` を実態に合わせて改訂** — 配信モデル 3 分類、Playwright 必須化、setagaya/sapporo を別ベンダ扱いで除外、改訂履歴に記録

### Decisions / Design Notes

- **採用判定 Plan A**: Playwright + Chromium を Cloud Run Jobs バッチで実行。540 自治体カバレッジを死守、B-2 比較ビューの実現性確保
- **Drop Point の明文化**: 「Week 2 中日 6/4 水」を判断日として `recon.md §4.3` に記録、判定基準 4 つも列挙
- **配信モデル混在**: Phase 2 で `municipality_master.csv` に `scraper_base_url` カラム追加して中央型/白ラベルを吸収する設計
- **別ベンダ系**: `札幌市・世田谷区` は A-4 対象外。Phase 2 で `docs/scrapers/voices_asp_recon.md` として別調査を計画
- **倫理判定**: robots.txt は自動クローラ向け、Playwright (実ブラウザ的振る舞い) は許容範囲という整理。Zenn 記事・ピッチで明示予定

### Surprises / Risks

- **採用自治体数の認識**: DATA_SOURCES.md の「350+」は最新値より少なく、楽観論として 540 まで増える可能性は朗報
- **DOMContentLoaded 2.8 分** (キャプチャ観察): 1 ページ取得に 3 分弱かかる可能性。Playwright 実装時に再計測必須、許容できない遅さなら Cloud Run Jobs のタイムアウト設計を見直す
- **CSRF トークン**: 直接 API 叩きを「物理的にできなくする」セキュリティ対策が既に組まれている → 開発元の意図として「クローラ非推奨」が明確、Playwright を選んだ判断の追加裏付け

### Environment Issues (Day 1 から継続)

- Claude Code Bash サンドボックスは引き続き使用不可。Yuji 側ターミナル + 私のファイル編集の運用で問題なし

### Next (Week 0 残タスク、次セッション以降)

優先順:

1. **GCP プロジェクト作成 + API 有効化** (1-2h) — Week 1 Terraform 着手前に必須
2. **自治体マスタ Phase 2: Tier 1 自治体 50 件の補完** — `scraper_type='kaigiroku'`, `tenant_id`, `press_rss_url` を手動収集。今回判明した 3 配信モデルを `scraper_base_url` 新カラムで吸収する設計を含む(マイグレーション計画も同時に)
3. **`docs/scrapers/voices_asp_recon.md`** (別ベンダ系の予備調査、Phase 2) — 札幌市・世田谷区が漏れる影響範囲を確認したい場合のみ
4. **Week 1 着手**: Terraform 雛形、FastAPI 雛形、Cloud Run デプロイ、国会 API クライアント実装、Vertex AI RAG セットアップ

### Commit Reminder

未コミット変更:

- `docs/scrapers/kaigiroku_net_recon.md` (Write で全面書き直し)
- `docs/DATA_SOURCES.md` (§2 改訂 + 改訂履歴追記)
- `log.md` (このファイル)

> 参考: `/tmp/citify-week0/kaigiroku_recon/*.html` は fixture 候補だが gitignore 推奨(`/tmp/` 配下、再生成可能、容量大)。Week 2 で必要な分だけ `scrapers/kaigiroku_net/fixtures/` に正式移植する

推奨コミット:
```bash
git add docs/scrapers/kaigiroku_net_recon.md docs/DATA_SOURCES.md log.md
git status   # 3 ファイル + 想定外がないか確認
git commit -m "docs: kaigiroku.net recon -> A-4 verdict YELLOW (Playwright required)"
git push origin main
```

---

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
