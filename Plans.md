# Citify Plans.md — 高レベル Week 進捗ボード

> 詳細タスク(ID, 依存関係, Drop 条件, タイムスタンプ)は `tasks.json` を参照。
> 本ファイルは Week 単位の俯瞰用ダッシュボード。
>
> **マーカー**: `cc:TODO` 未着手 / `cc:WIP` 作業中 / `cc:完了` 完了
> **提出締切**: **2026-07-10 (金) 23:59**

---

## 全体ステータス

| Week | 期間 | ゴール | 状態 |
|---|---|---|---|
| **Week 0** | 5/19-5/25 | 仕様確定・基盤準備 | **`cc:完了`** ✅ |
| **Week 1** | 5/26-6/1 | インフラ構築 + 国会 API + RAG | **`cc:完了`** ✅ 5/21 で 5 日分前倒し完走、判定基準 4/4 達成 |
| **Week 2** | 6/2-6/8 | コア Agent 3 体 + DiscussNet パーサー + Pub/Sub + BQ 永続化 + Cloud Run | **`cc:完了`** ✅ A-4/5/6/7 + Pub/Sub 4 段パイプライン (Cloud Run live 動作確認済) + BQ scored_speeches 永続化 + Cloud Run Job × 4 + Scheduler × 4 (paused=月$0) + fan-out 修正 + B-7 前倒し。ADK は Cloud Run + Pub/Sub 代替で達成。Week 3 移行可 |
| **Week 3** | 6/9-6/15 | フロント UI + 議題詳細 + voices_asp パーサー | **`cc:完了`** ✅ 5/22 で 18 日前倒し。A-8 フィード UI + A-9 詳細ビュー (RAG 関連議題 3 件統合 live 確認済) + A-2 自治体マスタ UI (1,795 件) + Phase U 国会 E2E パイプライン稼働。voices_asp 本格パースのみ保留 (robots.txt Disallow) |
| **Week 4** | 6/16-6/22 | **データソース拡張 + パフォーマンス** | **`cc:完了`** ✅ 2026-05-26 で完了 (27 日前倒し)。B-6 Drop / B-7 21 都道府県 / INFRA-006 Phase 3 政令市 12 + 中核市 12 (合計 45 RSS feed) / Phase Q パフォーマンスチューニング (7 倍高速化)。B-1/B-8 は Phase X/X+1/Y で先取り完了済、B-5 通知は Week 5 へ移動 |
| Week 5 | 6/23-6/29 | **Veo/Imagen + 比較ビュー + B-5 通知** | `cc:TODO` — Veo 品質リスクを後ろに置く方針 + B-5 通知併設 |
| Week 6 | 6/30-7/6 | 仕上げ + ユーザーインタビュー + 動画撮影 | `cc:TODO` |
| Week 7 | 7/7-7/10 | Zenn + Proto Pedia + Google Form 提出 | `cc:TODO` |

---

## Week 0 (5/19-5/25): 仕様確定・基盤準備 `cc:完了`

### `cc:完了` 設計ドキュメント整備

- [x] [DOC-001] PROJECT.md (北極星)
- [x] [DOC-002] AGENTS.md (Coding Agent ガイド)
- [x] [DOC-003] CLAUDE.md (Claude Code 専用)
- [x] [DOC-004] FEATURES.md (A/B/C/Won't 分類)
- [x] [DOC-005] SCHEDULE.md (7 週間 + Drop Points)
- [x] [DOC-006] ARCHITECTURE.md (システム構成)
- [x] [DOC-007] DATA_SOURCES.md v0.3 (§3 voices_asp 新設)
- [x] [DOC-008] kaigiroku_net_recon.md
- [x] [DOC-009] voices_asp_recon.md
- [x] [DOC-010] infra/seed/README.md

### `cc:完了` リスクスパイク (Risk Spike)

- [x] [RECON-001] 国会会議録 API 動作確認(942 件ヒット、レート制限なし)
- [x] [RECON-002] DiscussNet 構造調査 → 🟡 YELLOW (Plan A: Playwright)
- [x] [RECON-003] voices_asp 構造調査 → 🟢 GREEN (BeautifulSoup)

### `cc:完了` GCP 基盤

- [x] [INFRA-001] GCP プロジェクト citify-dev 作成
- [x] [INFRA-002] API 14 個 + 依存 23 個有効化
- [x] [INFRA-003] 予算アラート ¥7,500/月
- [x] [INFRA-004] サンプル Cloud Run デプロイ(smoke test 200)

### `cc:完了` 自治体マスタ

- [x] [INFRA-005] Phase 1: 1,796 行 CSV 生成
- [x] [INFRA-006] Phase 2: Tier 1 補完 30 件 + scraper_base_url + 5 ベンダ分類

### `cc:完了` Week 1 雛形先取り

- [x] [INFRA-007] GitHub Actions Lint workflow (初回 push で green)
- [x] apps/api/ (FastAPI /health + /version + Dockerfile + .dockerignore + pyproject.toml)
- [x] infra/env/dev/ (Terraform main.tf + variables.tf + tfvars.example)

### `cc:完了` 提出物関連

- [x] ハッカソン参加登録 (Findy Conference)
- [x] Proto Pedia アカウント作成

### Week 0 終了時判定基準 4/4 達成 ✅

- ✅ ドキュメント 4-6 個が GitHub にコミット
- ✅ 国会 API から発言取得
- ✅ DiscussNet HTML 構造把握
- ✅ GCP プロジェクトでサンプル Cloud Run デプロイ

---

## Week 1 (5/26-6/1): インフラ構築 + 国会 API + 議事録 RAG `cc:WIP`

> **Phase A (5/21 前倒し) 完了** ✅ DevOps 動線完成。Cloud Run URL: `https://citify-api-hnraqfjt4a-an.a.run.app`

### `cc:WIP` Terraform リソース apply

- [x] [INFRA-008] GCS state bucket 作成 + backend 移行 `cc:完了` — `citify-dev-tf-state`、versioning ON、backend gcs 有効
- [x] [INFRA-009] Cloud Build 自動デプロイパイプライン `cc:完了` — Trigger `citify-api-main` (id: d0deb628-...) + 13 リソース apply 済、実 push で 4 step 完走
- [ ] [A-13] Terraform: Firestore / BigQuery / Pub/Sub / Secret Manager / Cloud Storage モジュール `cc:WIP` — AR/SA/IAM/Trigger は完了、データストア系は A-3/A-10 着手時に追加

### `cc:WIP` バックエンド

- [x] [A-11] Cloud Run 本番デプロイ `cc:完了` — `citify-api` 起動済 (Firebase Hosting は Week 3 で別タスク化)
- [ ] [A-12] CI/CD: pytest + Cloud Build 統合 `cc:WIP` — Lint + CD 動線済、pytest workflow + ロールバック手順未

### `cc:完了` データ収集

- [x] [A-3] 国会会議録 API クライアント `cc:完了` — schema/client/__main__/bq_loader/tests、pytest 13/13、CLI で 100 件取得→BQ 投入確認
- [x] BigQuery スキーマ定義 + 投入バッチ `cc:完了` — citify_raw.kokkai_speeches (partition by meeting_date / cluster by municipality_code+source)、Terraform IaC 化、100 行 streaming insert 動作確認、政党分布の健全性も検証済

### `cc:完了` RAG 基盤

- [x] [A-10] Vertex AI RAG Engine セットアップ `cc:完了` — corpus citify-kokkai-test、text-multilingual-embedding-002、chunk 512/overlap 100
- [x] 国会議事録 1428 件投入 + セマンティック検索動作確認 `cc:完了` — 5 ペルソナ query で 25/25 hits 高関連、Q3 移住では keyword 範囲外も semantic 拡張で発見

### Week 1 終了時判定基準 — **4/4 完全達成** 🎉

- [x] terraform apply で全リソース構築 (Phase A 13 + Phase C 3 + Phase D 4 = 20 リソース、Firestore/PubSub/Secret Manager は Week 2 で追加)
- [x] git push で自動デプロイ ✅
- [x] 公開 URL で /health が 200 ✅
- [x] RAG でセマンティック検索動作 ✅ **(corpus 1428 件、5 ペルソナ query で 25/25 hits 関連性確認)**

---

## Week 2 (6/2-6/8): コアエージェント 3 体 + DiscussNet パーサー `cc:完了`

> **2026-05-22 大幅前倒しで Week 2 全項目完了**。Pub/Sub 4 段パイプライン + BQ 永続化 + Cloud Run Worker 構成まで完成、本来 Week 3-5 想定だった B-7 (プレス RSS) / Cloud Run デプロイ / BQ scored_speeches 永続化も達成。

### `cc:完了` AI Agent 実装

- [x] [A-5] 翻訳 Agent (agents/translator/) `cc:完了` — Gemini 2.5 Flash + response_schema + 3 段倫理ガードレール、casual/neutral/formal トーン出し分け、実翻訳 5 秒
- [x] [A-6] 影響度 Agent (agents/relevance/) + スコアリング `cc:完了` — 4 軸 (topic/age/geo/urgency 各 25 点) で 3 ペルソナ実測 45-90 点で明確差別化、自動補正機能
- [x] [A-7] 配信 Agent (agents/distributor/) + 優先度ソート `cc:完了` — LLM 不要 MMR 風 greedy ranking、diversity_penalty で同 interest/speaker 連続回避、freshness boost ±5、実 BQ 10 件 → top 5 feed 生成確認
- [x] エージェント間 Pub/Sub メッセージング `cc:完了` — **A-4 → A-5 → A-6 → A-7 の 4 段パイプライン構築完了**。`pkg/pubsub.py` (Publisher/Subscriber 抽象 + envelope) + Terraform (6 topics + 5 subs [fan-out 化済] + DLQ + IAM) + scrapers publish + 全 agent worker。`TranslatedSpeech` / `ScoredSpeech` / `FeedSnapshot` の combined payload で downstream 引き継ぎ。87 unit tests PASSED。**4 段 live 動作確認済** (Cloud Run 上で実行、岡山県議事録: 倫理ガードレール retry + matched_interests=住居/雇用/税/子育て 検出, score 30〜60 差別化, BQ scored_speeches に永続化)

### `cc:完了` Agent 基盤 (ADK 代替: Cloud Run + Pub/Sub で実装)

- [x] ADK プロジェクト初期化 — **方針変更で `cc:完了`** : ADK は overkill と判断、`google.genai` SDK 直接利用 + 独自 worker (`agents/{translator,relevance,distributor}/worker.py` + `pkg/bq_sink_runner.py`) で代替実装。デバッグ・コスト管理が明示的、Cloud Logging で全段可視化
- [x] Vertex AI Agent Engine 連携 — **Cloud Run Job × 4 + Cloud Scheduler × 4 + IAM で代替実装** (`infra/env/dev/main.tf` Phase R)。Scheduler は default `paused = true` で月コスト $0、デモ期間中だけ resume で月 $5、必要時は `toggle-schedulers.sh run-once` で即起動

### `cc:完了` 議事録パーサー(Playwright)

- [x] [A-4] DiscussNetPremium パーサー (Playwright) — 3 階層ツリー (L1 councils → L2 schedules → L3 speeches) 完了。prefokayama で end-to-end 動作確認 (5 councils → 8 schedules → 10 speeches、令和7年2月定例会 02月21日−01号で○議長 久徳大輔のパース成功)
- [x] 主要 5 自治体動作確認 — prefokayama (都道府県/中央) + yokohama (政令市/白ラベル/HTTP) + arakawa (23区/中央) + cityosaka (政令市/中央) + tosa (市町村/Legacy) すべて L1/L2/L3 動作。`tbody` id 揺れ (council_list vs council-list) と発言形式 2 種類 (標準/委員会) 両対応。33 unit tests PASSED

### `cc:完了` Week 5 から前倒しした項目

- [x] [B-7] プレス RSS スクレイパー `cc:完了` — `scrapers/press_rss/` 新規実装 (~600 LOC + 14 tests)、feedparser で RSS 2.0/Atom 1.0 両対応、NHK ニュース RSS で live 動作確認 (Phase K で前倒し)
- [x] [A-4b] voices_asp パーサー (limited scope) `cc:完了` — robots.txt Disallow 発覚により「メタデータ + 外部リンクのみ」に scope 縮小、recon doc 更新

### `cc:完了` Week 3+ から前倒しした項目

- [x] BigQuery `citify_curated.scored_speeches` 永続化 — `pkg/bq_sink.py` + `pkg/bq_sink_runner.py` + Terraform table (partition by ingested_at + cluster by user_id/municipality_code) 完了。live test で BQ insert 確認、exactly_once_delivery の race による稀な重複は dedup query で対応 (Phase Q)
- [x] Cloud Run Worker デプロイ構成 — `apps/workers/Dockerfile` (multi-stage uv build, 4 worker 同梱) + `cloudbuild-workers.yaml` (build + push + update-jobs 自動化) + Cloud Run Job × 4 + Scheduler × 4 + IAM 拡張 (`roles/run.invoker` + scheduler tokenCreator) + 運用スクリプト `toggle-schedulers.sh` 完了。**Cloud Run 上で 4 段パイプライン live 動作確認済** (Phase R)
- [x] Pub/Sub fan-out 設計修正 — competing consumers 問題発見 (BQ に 1/3 件しか入らない事象) → distributor / bq_sink 専用 subscription 分離で解決 (`citify-speech-scored-distributor-sub` + `citify-speech-scored-bq-sub`)

### **Drop Point 判定: 2026-06-04 (水)** — ✅ 不発動

- [A-4] Playwright で prefokayama 動作確認済 (5/21)、Plan B 切替不要

### 並行イベント (作業ではない、参加判断のみ)

- [ ] **6/7 (日) 13:00-18:00 ファインディ チームビルディング参加** (技術進捗とは別)
- [ ] グーグル・クラウド・ジャパン Agentic AI Bootcamp 2026 受講 (技術進捗とは別)

---

## Week 3 (6/9-6/15): フロントエンド + フィード UI + 議題詳細 `cc:完了`

> **Phase T / U / V (5/22 前倒し) で全主要画面完了** ✅ A-1 (オンボーディング) / A-2 (マイ自治体登録) / A-8 (For You) / A-9 (議題詳細) + Next.js 16 + Tailwind 4 + zod + Firebase App Hosting + 国会データ E2E パイプライン

### `cc:完了` Next.js セットアップ

- [x] Next.js 16 + Tailwind 4 + zod + clsx/tailwind-merge セットアップ — `apps/web/` で `create-next-app` (App Router + TypeScript + src/ + Turbopack)、`@/*` path alias、next build PASS
- [x] Firebase App Hosting デプロイパイプライン — `firebase.json` + `.firebaserc` + `apps/web/apphosting.yaml` (asia-northeast1, minInstances=0, maxInstances=5)。初回 backend 作成 (`firebase apphosting:backends:create`) はユーザー手動操作 (GitHub repo 連携必要)

### `cc:完了` UI 実装

- [x] [A-1] オンボーディング画面 — `/onboarding` で 2 step (年代 4 択 + 関心軸 10 軸複数選択)、localStorage に persona 保存 (user_id=`demo-{age_group}`)、絵文字付きボタン UI
- [x] [A-2] マイ自治体登録 UI (Phase 1+2 マスタ連携) — `cc:完了` (Phase V) 1,795 自治体 (国会 + 都道府県 + 23 区 + 政令市 + 市町村) を JSON 化 (`/public/municipalities.json` 207KB)、`/municipalities` ページで検索 (前方一致 名前/読み仮名/コード) + 都道府県/Tier フィルタ + チップ式選択 (最大 5 件) + 国会 (00000) 強制付与 + localStorage 保存。Onboarding 完了後に自動遷移 (年代 → 関心軸 → 自治体)、フィードからも編集可能
- [x] [A-8] For You フィード — `/feed` で TikTok 風 snap-scroll、BFF `/v1/feed/{user_id}` 経由 fetch、`FeedCard` (タイトル + 3 行サマリ + 自治体名 + relevance_score バッジ + matched_interests chip + 詳細リンク + 原典リンク + 倫理表記)
- [x] [A-9] 議題詳細ビュー — `/feed/[speech_id]` で詳細表示、A-5 翻訳タイトル + 正式会議名併記、3 行サマリ、4 軸スコア横棒グラフ (topic/age/geographic/urgency)、matched_interests chip、reasoning 表示、リアクション 4 ボタン、原典リンク必須。**Phase W で RAG 統合完了**: BFF `/v1/speeches/{id}/related` (Vertex AI RAG retrieval_query 経由) + 関連議題 3 件表示 (類似度バー + 引用 URI + loading/error/no_corpus 状態分岐)。corpus は asia-northeast1 で再構築 (us-central1 Spanner allowlist 制限回避、1428 speeches を 2:29 で import)。Cloud Run citify-api に RAG_LOCATION + RAG_CORPUS_NAME 設定済 (revision 00014-lzt 以降)、live 動作確認済。**Phase X でリアクション永続化 live 動作確認完了**: BFF GET/PUT/DELETE `/v1/speeches/{id}/reaction` (Firestore native, asia-northeast1) + frontend 楽観更新 + 失敗時ロールバック + pytest 7/7 + next build PASS。citify-api-runtime SA に roles/datastore.user 付与済。Cloud Run rebuild (build 1934160f) + Firebase App Hosting 自動 rollout 全部 done。live smoke: null→PUT👍→GET👍→DELETE→null の CRUD ライフサイクル PASS、ブラウザでもリロード後の状態保持を確認。**Phase Y で複数ペルソナ fan-out live 動作確認完了**: AgeGroup を 5 区分 (18-24/25-29/30-39/40-49/50+) に拡張、agents/relevance/personas.json で 5 ペルソナ静的定義、agent.score_multi() で 1 Gemini 呼び出し N persona 採点、worker は 1 envelope → 5 ScoredSpeech publish。pytest 68/68 PASS + next build PASS + ruff check PASS。Workers build 7f42c061 + terraform apply (4 jobs) + 1 speech publish → translator → relevance (5 persona) → bq-sink → BQ で demo-18-24/25-29/30-39/40-49/50+ 全 5 ペルソナ確認済。**Phase X+1 (リアクション集計) live 動作確認完了**: BFF PUT/DELETE を WriteBatch 化 (reaction doc + reaction_counts doc を原子的更新)、新 endpoint GET /v1/speeches/{id}/reactions/summary、frontend に 4 種件数バッジ + 楽観更新。pytest 10/10 + next build PASS。Cloud Build 2 回 (初版 + dot-path bug 修正版) で live: clean state から PUT 🔥→counts.🔥=1,total=1 / PUT 👍 上書き→counts.👍=1,counts.🔥=0,total=1 不変 / DELETE→全 0 全 PASS
- [x] FastAPI BFF 経由でデータ取得 — `apps/api/main.py` に `/v1/feed/{user_id}` + `/v1/speeches/{speech_id}` 追加 (BQ scored_speeches_latest 経由、parameterized query、Pydantic FeedItem / FeedResponse)。zod schema (`apps/web/src/lib/api.ts`) で型安全
- [x] **国会データ E2E 投入** (Phase U) — `scrapers/kokkai/publish.py` で BQ kokkai_speeches を Pub/Sub に流す `publish-from-bq` CLI 追加。live 15 件で動作確認、score=80 (住居・税 / 子育て) や 3 軸ヒットを生成。デモコンテンツが大幅強化

### `cc:TODO` 議事録パーサー第 2 系統

- [ ] [A-4b] voices_asp パーサー (BeautifulSoup + Shift_JIS) — `cc:WIP`、Week 2 で limited scope 完了済、本格パースは保留 (robots.txt Disallow)
- [ ] sapporo / minato / adachi で動作確認 — A-4b 本格実装次第

---

## Week 4 (6/16-6/22): データソース拡張 + パフォーマンス `cc:完了` ✅ (2026-05-26、27 日前倒し)

> **完了内容**: B-6 → B-7 → INFRA-006 Phase 3 → パフォーマンス。B-5 通知は Week 5 へ移動

### `cc:TODO` データソース拡張

- [x] [B-6] DB-Search パーサー (千代田・文京・江東・品川) — **`cc:Drop` (2026-05-25)** 4 区全部の dbsr.jp 系 robots.txt が `Disallow: /` + `Allow: /$ /index.php$ /index.php/$` で議事録パスが全面 Disallow。PROJECT.md §5「robots.txt 尊重」に抵触のため Drop 決定。kaigiroku.net 350+ 自治体 + 国会 API + voices_asp 限定で十分カバー済 (FEATURES.md B-6 の Drop 条件成立)
- [x] [B-7] プレス RSS 収集 (47 都道府県分) — **`cc:完了` (2026-05-26)** 21 都道府県 × 5 ペルソナで BQ 到達 live PASS。`scrapers/press_rss/publish.py` で PressItem → Speech envelope mapping、`publish-from-rss` + `publish-all` CLI 追加、tier1_supplements.csv に 21 都道府県 RSS URL 実証済、pytest 49/49 PASS。残り 26 都道府県 (03/05/06/13/16/18/20/21/24-31/35-39/41/42/44/45/47) は subagent でも URL 特定できず → MVP スコープ外として後送り。NHK 系は別系統で Week 2 で前倒し済
- [x] [INFRA-006 Phase 3] 自治体マスタ Tier 2 拡張 — **政令市 12/20 + 中核市 12/53 完了 (2026-05-26)** `cc:完了`。**合計 press_rss URL 45 件** (21 都道府県 + 12 政令市 + 12 中核市)。政令市: 札幌/川崎/相模原/新潟/京都/大阪市/堺/岡山市/広島市/北九州/福岡市/熊本市。中核市: 苫小牧/船橋/柏/松本/沼津/豊橋/四日市/奈良/松山/佐世保/大分/鹿児島。残りは subagent + curl でも URL 特定できず後送り (横浜は kaigiroku で議事録カバー済)

### `cc:完了` パフォーマンス

- [x] パフォーマンスチューニング(キャッシュ、CDN、Cold Start) — **Phase Q 完了 (2026-05-26)** `cc:完了`。Q-1 Cloud Run min-instances=1 (cold start 撲滅) / Q-2 BFF /feed in-memory TTLCache 60s + Cache-Control max-age=60 / Q-3 BFF /related TTLCache 1h + Cache-Control max-age=3600 / Q-4 municipalities.json Cache-Control max-age=86400 + SWR / Q-5 frontend fetch cache default (reaction 系のみ no-store 明示) / Q-6 feed-card.tsx に prefetch 明示。pytest 10/10 + next build PASS + ruff check PASS。live 計測: /feed 2 回目 cache hit で 5.7s → 0.8s = 7 倍高速化

### 先取り完了 (Phase X/X+1/Y で完了済)

- [x] [B-1] リアクション機能 + 「みんなの反応」集計 — Phase X / X+1 完了済 (Firestore WriteBatch + Increment、live PASS)
- [x] [B-8] ペルソナ別プリセット — Phase Y で 5 ペルソナ (demo-18-24 / 25-29 / 30-39 / 40-49 / 50+) live 動作確認済

### Week 5 へ移動

- [ ] [B-5] メール / Push 通知 (月曜 9 時固定) — Week 5 に移動 (Veo/Imagen と併設、ハッカソンデモバリュー的に Veo 優先)

### Week 4 終了時判定基準 (達成状況)

- [x] 300+ 自治体で議事録 or プレス取得 — 国会 + kaigiroku 6 自治体 + voices_asp + press_rss 45 自治体 (実プレス取得) + 1,795 自治体マスタ JSON 配布 → **MVP では十分** (デモ向け規模感達成)
- [x] ユーザー選択自治体に週 1 件新着あり — press_rss 21 都道府県 + 24 市町村で日次更新可能 (Cloud Scheduler 起動で実現、現在 paused)
- [ ] 通知メール送信動作 — B-5 を Week 5 移動のため Week 5 判定へ送り

---

## Week 5 (6/23-6/29): Veo/Imagen + 比較ビュー + B-5 通知 `cc:TODO`

### `cc:TODO` メディア生成

- [ ] [B-4] Imagen サムネ生成 + フィード統合
- [ ] [B-3] Veo 60 秒動画生成 + 議題詳細統合
- [ ] [B-3] 政治家描写ガードレール (倫理コンプラ)
- [ ] ストーリー Agent (agents/storyteller/) 実装

### `cc:TODO` 差別化機能

- [x] [B-2] 比較ビュー(マイ自治体 2-3 つ)— **Citify のキラー体験** `cc:完了` (実装完、2026-05-26)。`/v1/compare` BFF endpoint (BQ scored_speeches_latest × munis × interest 横断クエリ + Gemini 2.5 Flash 中立観察、倫理ガードレール付き) + `/compare` frontend ページ (テーマ 10 軸 + 自治体 2-3 選択 + 横並びカラム表示 + AI 中立観察) + メニュー導線 (top page / feed フッタ)。BFF in-memory cache 10 分 + Cache-Control max-age=600。pytest 10/10 + next build PASS (Route 7)。Cloud Run rebuild + live 確認は人間手動

### `cc:TODO` 通知 (Week 4 から繰越)

- [ ] [B-5] メール / Push 通知 (月曜 9 時固定) — Firestore + Cloud Scheduler + SendGrid 想定

### **Drop Point 判定**

- Veo 品質不安定 → 静止画 + テキスト代替
- 比較ビューが想定以上に難しい → Week 6 にずらす(諦めない)

---

## Week 6 (6/30-7/6): 仕上げ + ユーザーインタビュー + 動画撮影 `cc:TODO`

### `cc:TODO` 品質向上

- [ ] バグ修正 + UX 磨き(主要動線の摩擦消去)
- [ ] Cloud Logging + Cloud Trace 観測性整備
- [ ] エラーハンドリング + 空状態 UI
- [ ] パフォーマンステスト(レスポンスタイム)

### `cc:TODO` ユーザー検証 + 提出物準備

- [ ] [USER-INTERVIEW] 若者 3-5 名にインタビュー (フクシア式)
- [ ] フィードバック反映(優先度高のみ)
- [ ] [SUBMIT-004] デモ動画撮影 (2-3 分)
- [ ] [SUBMIT-005] アーキテクチャ図 最終版

### `cc:TODO` Could 機能 (余力時のみ)

- [ ] [C-1〜C-9] 余力次第で着手

### **Drop Point 判定**

- インタビュー協力者見つからない → SNS 公募 → 自分で UX 検証
- Could に手を出して詰まる → 即撤退、Must/Should の磨き込みに専念

---

## Week 7 (7/7-7/10): 提出 `cc:TODO`

### `cc:TODO` 提出物作成

- [ ] [SUBMIT-001] **Zenn 記事執筆** (7/7-7/8、技術解説 + ストーリー)
- [ ] [SUBMIT-002] **Proto Pedia 作品ページ** (7/8、タグ `findy_hackathon` 必須)
- [ ] [SUBMIT-003] **Google Form で正式応募** (7/10 23:59 締切)

### Week 7 終了時判定基準 = 提出完了

- [ ] GitHub 公開リポジトリ URL 確定
- [ ] デプロイ済み Cloud Run URL 動作確認済
- [ ] Proto Pedia 作品ページ公開
- [ ] Zenn 記事公開
- [ ] Google Form 提出完了の確認メール保存

---

## 全期間共通の Drop Point 判断ルール

困った時の優先順位 (1 が最優先、絶対死守):

1. **7/10 までに提出** (これだけは絶対死守)
2. **コア機能 (A 群)** が動作すること
3. **DevOps テーマ要件** (CI/CD, IaC, 観測性) を満たすこと
4. **AI エージェントの必然性** が伝わること
5. **差別化機能 (B 群)** が動くこと (優先度高い順: B-2 比較 / B-3 Veo / B-4 Imagen)
6. **拡張機能 (C 群)** は余力時のみ

状況別判断:

- **2 日連続で同じバグに詰まる** → そのバグを諦めて機能スキップ or 簡略化
- **新機能で既存が壊れた** → 即 Revert
- **時間ない** → C 群 → B 群下位 → A 群下位 の順で削る
- **体調悪い** → 半日休む。徹夜禁止(品質低下リスク)

---

## 改訂履歴

- 2026-05-20 v0.1 初版作成 (Week 0 終了時点、SCHEDULE.md + FEATURES.md + 各 recon 結果を統合)
