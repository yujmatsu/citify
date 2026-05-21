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
| **Week 2** | 6/2-6/8 | コア Agent 3 体 + DiscussNet パーサー | **`cc:WIP`** 🚧 Phase E (A-5) + F (A-6) + G (A-7) 完了、コア Agent 3 体 ✅。残 A-4 / Pub/Sub |
| Week 3 | 6/9-6/15 | フロント UI + 議題詳細 + voices_asp パーサー | `cc:TODO` |
| Week 4 | 6/16-6/22 | Veo/Imagen + 比較ビュー + リアクション | `cc:TODO` |
| Week 5 | 6/23-6/29 | DB-Search + プレス RSS + 通知 | `cc:TODO` |
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

## Week 2 (6/2-6/8): コアエージェント 3 体 + DiscussNet パーサー `cc:WIP`

> **Phase E (5/21 前倒し) 完了** ✅ A-5 翻訳 Agent: 実 Gemini 動作確認、倫理ガードレール 3 段、tests 11/11

### `cc:TODO` ADK セットアップ

- [ ] ADK プロジェクト初期化 (now: google.genai SDK 直接利用、ADK 化は後でも可)
- [ ] Vertex AI Agent Engine 連携 (Cloud Run + Pub/Sub で代替予定)

### `cc:WIP` AI Agent 実装

- [x] [A-5] 翻訳 Agent (agents/translator/) `cc:完了` — Gemini 2.5 Flash + response_schema + 3 段倫理ガードレール、casual/neutral/formal トーン出し分け、実翻訳 5 秒
- [x] [A-6] 影響度 Agent (agents/relevance/) + スコアリング `cc:完了` — 4 軸 (topic/age/geo/urgency 各 25 点) で 3 ペルソナ実測 45-90 点で明確差別化、自動補正機能
- [x] [A-7] 配信 Agent (agents/distributor/) + 優先度ソート `cc:完了` — LLM 不要 MMR 風 greedy ranking、diversity_penalty で同 interest/speaker 連続回避、freshness boost ±5、実 BQ 10 件 → top 5 feed 生成確認
- [ ] エージェント間 Pub/Sub メッセージング

### `cc:TODO` 議事録パーサー(Playwright)

- [ ] [A-4] DiscussNetPremium パーサー (Playwright)
- [ ] 主要 5 自治体動作確認 (横浜・大阪・岡山県・荒川・新宿・墨田)

### **Drop Point 判定: 2026-06-04 (水)**

- [A-4] Playwright が 1 自治体動かなければ → Plan B (国会 + プレス RSS のみ) に切替

### 並行イベント

- [ ] **6/7 (日) 13:00-18:00 ファインディ チームビルディング参加**
- [ ] グーグル・クラウド・ジャパン Agentic AI Bootcamp 2026 受講

---

## Week 3 (6/9-6/15): フロントエンド + フィード UI + 議題詳細 `cc:TODO`

### `cc:TODO` Next.js セットアップ

- [ ] Next.js 15 + Tailwind + shadcn/ui セットアップ
- [ ] Firebase Hosting デプロイパイプライン

### `cc:TODO` UI 実装

- [ ] [A-1] オンボーディング画面
- [ ] [A-2] マイ自治体登録 UI (Phase 1+2 マスタ連携)
- [ ] [A-8] For You フィード (縦スクロール)
- [ ] [A-9] 議題詳細ビュー + RAG 検索結果表示
- [ ] FastAPI BFF 経由でデータ取得

### `cc:TODO` 議事録パーサー第 2 系統

- [ ] [A-4b] voices_asp パーサー (BeautifulSoup + Shift_JIS)
- [ ] sapporo / minato / adachi で動作確認

---

## Week 4 (6/16-6/22): Veo/Imagen + 比較ビュー + リアクション `cc:TODO`

### `cc:TODO` メディア生成

- [ ] [B-4] Imagen サムネ生成 + フィード統合
- [ ] [B-3] Veo 60 秒動画生成 + 議題詳細統合
- [ ] [B-3] 政治家描写ガードレール (倫理コンプラ)
- [ ] ストーリー Agent (agents/storyteller/) 実装

### `cc:TODO` 差別化機能

- [ ] [B-2] 比較ビュー(マイ自治体 2 つ)— **Citify のキラー体験**
- [ ] [B-1] リアクション機能 + 「みんなの反応」集計

### **Drop Point 判定**

- Veo 品質不安定 → 静止画 + テキスト代替
- 比較ビューが想定以上に難しい → Week 5 にずらす(諦めない)

---

## Week 5 (6/23-6/29): データソース拡張 + 通知 `cc:TODO`

### `cc:TODO` データソース拡張

- [ ] [B-6] DB-Search パーサー (千代田・文京・江東・品川)
- [ ] [B-7] プレス RSS 収集 (47 都道府県分)
- [ ] [INFRA-006 Phase 3] 自治体マスタ Tier 2 拡張 (200-300 件)

### `cc:TODO` 通知 + UX

- [ ] [B-5] メール / Push 通知 (月曜 9 時固定)
- [ ] [B-8] ペルソナ別プリセット
- [ ] パフォーマンスチューニング(キャッシュ、CDN、Cold Start)

### Week 5 終了時判定基準

- [ ] 300+ 自治体で議事録 or プレス取得
- [ ] ユーザー選択自治体に週 1 件新着あり
- [ ] 通知メール送信動作

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
