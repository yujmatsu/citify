# AGENTS.md — Coding Agent への統一指示書

> このファイルは、Claude Code / Gemini CLI / GitHub Copilot / Codex CLI などのコーディングエージェントが Citify のコードを生成する際に必ず読むべきルール集です。フクシア(第 3 回 AI Agent Hackathon 最優秀賞)の方式を踏襲しています。
>
> Coding Agent はコードを生成・編集する前に、必ずこのファイルを読み、`docs/PROJECT.md` と `docs/FEATURES.md` を併読してください。

---

## 1. プロジェクトコンテキスト

- **プロジェクト名**:Citify
- **ハッカソン**:Findy DevOps × AI Agent Hackathon 2026
- **提出締切**:2026 年 7 月 10 日 23:59
- **開発者**:Yuji(個人開発)
- **開発環境**:Windows 11 + **WSL2 (Ubuntu 24.04)** + VSCode Remote
- **使用言語**:日本語(ドキュメント・UI・コメント)、英語(変数名・関数名・コミットメッセージ)
- **シェル**:bash(Linux 系コマンドのみを使用、PowerShell コマンドは生成しない)

## 2. 技術スタック(変更禁止、変更時は人間と相談)

### バックエンド
- **言語**:Python 3.12
- **フレームワーク**:FastAPI
- **AI Agent**:Agent Development Kit (ADK) for Python
- **AI Agent 実行環境**:Vertex AI Agent Engine
- **LLM**:Gemini 2.5 Pro(本番)、Gemini 2.5 Flash(高頻度・低レイテンシ処理)
- **RAG**:Vertex AI RAG Engine
- **動画生成**:Veo 3(API 経由)
- **画像生成**:Imagen 3(API 経由)
- **文書パース**:Document AI

### フロントエンド
- **フレームワーク**:Next.js 15 (App Router) + TypeScript
- **UI**:Tailwind CSS + shadcn/ui
- **状態管理**:Server Components 優先、必要時 Zustand
- **ホスティング**:Firebase Hosting

### データ・ストレージ
- **アプリ DB**:Cloud Firestore(ユーザープロファイル、設定、リアクション集計)
- **アナリティクス DB**:BigQuery(議事録構造化データ、ユーザー行動ログ)
- **オブジェクトストレージ**:Cloud Storage(動画、画像、生 PDF)
- **キャッシュ**:Memorystore for Redis(必要時のみ)

### インフラ・運用
- **コンテナ実行**:Cloud Run(API)
- **バッチ実行**:Cloud Run Jobs
- **スケジューラ**:Cloud Scheduler
- **メッセージング**:Cloud Pub/Sub(エージェント間疎結合)
- **IaC**:Terraform
- **CI**:GitHub Actions
- **CD**:Cloud Build
- **観測性**:Cloud Logging + Cloud Trace
- **シークレット**:Secret Manager

## 3. リポジトリ構成

```
citify/
├── README.md               # 公開用 README
├── CLAUDE.md               # Claude Code 専用ガイド
├── AGENTS.md               # このファイル(他の AI コーディングツール向け)
├── LICENSE
├── .gitignore
├── .env.example
│
├── docs/                   # 設計ドキュメント集
│   ├── PROJECT.md          # プロダクト概要(必ず最初に読む)
│   ├── FEATURES.md         # 機能仕様
│   ├── SCHEDULE.md         # スケジュール + Drop Points
│   ├── ARCHITECTURE.md     # アーキテクチャ詳細
│   ├── DATA_SOURCES.md     # データソース仕様
│   ├── DATA_MODEL.md       # データモデル
│   ├── UI_WIREFRAMES.md    # UI ワイヤーフレーム
│   ├── AGENT_PROMPTS.md    # エージェントプロンプト集
│   ├── TERRAFORM_GUIDE.md  # Terraform 運用
│   ├── PROMPT_VERSIONS.md  # プロンプト版管理(LLMOps)
│   ├── DEMO_SCRIPT.md      # デモ動画スクリプト
│   └── GETTING_STARTED.md  # 開発開始ガイド
│
├── apps/
│   ├── web/                # Next.js フロントエンド
│   └── api/                # FastAPI バックエンド
│
├── agents/                 # ADK マルチエージェント
│   ├── collector/          # 収集 Agent
│   ├── classifier/         # 分類 Agent
│   ├── relevance/          # 影響度 Agent
│   ├── translator/         # 翻訳 Agent
│   ├── comparator/         # 比較 Agent
│   ├── storyteller/        # ストーリー Agent (Veo/Imagen)
│   └── distributor/        # 配信 Agent
│
├── scrapers/               # データ収集パーサー
│   ├── kokkai/             # 国会会議録 API
│   ├── kaigiroku_net/      # DiscussNetPremium
│   ├── db_search/          # DB-Search
│   ├── sophia/             # Sophia
│   ├── press_rss/          # 自治体プレス RSS
│   ├── e_gov_pubcom/       # e-Gov パブコメ
│   ├── opendata/           # オープンデータポータル
│   ├── koho_pdf/           # 公報 PDF
│   └── shingikai/          # 政府審議会
│
├── prompts/                # プロンプト版管理(Git + Cloud Storage)
│   ├── manifest.json
│   └── {agent}/
│
├── infra/                  # Terraform
│   ├── modules/
│   ├── env/dev/
│   └── env/prod/
│
├── .github/workflows/      # GitHub Actions
└── cloudbuild/             # Cloud Build 定義
```

## 4. コーディング規約

### 共通
- **コメントは日本語**で書く(他人=未来の自分が読みやすい)
- 関数・クラスには必ず docstring/JSDoc を付与し、何をするかと引数・戻り値を明記
- 関数は 1 つの責任のみを持つ。50 行を超えたら分割を検討
- 早期 return を使う。ネストは最大 2 段
- マジックナンバーは禁止。定数化する
- TODO コメントには必ず `# TODO(yuji): ...` の形式で起票理由を書く

### Python
- 型ヒント必須(`from __future__ import annotations`)
- 非同期処理は `async def` を使う(FastAPI / ADK 共に async ファースト)
- フォーマッタ:`ruff format`(black 互換)
- リンタ:`ruff check`
- 例外は具体的に。`except Exception:` は最後の砦のみ
- ログは `logging` モジュールを使い、`print()` は禁止
- 環境変数は `pydantic-settings` の Settings クラスで集約管理

### TypeScript
- `strict: true` を維持
- `any` 禁止。`unknown` を使ってから絞り込む
- フォーマッタ:Prettier
- リンタ:Biome(または ESLint)
- React コンポーネントは関数コンポーネントのみ
- フック使用時は `'use client'` を明示
- API 呼び出しは Server Component / Server Actions 優先

### Terraform
- バージョン:1.7+
- モジュール化を徹底、`env/dev` と `env/prod` でパラメータ切替
- リソース命名:`citify-{env}-{service}-{purpose}`
- 全リソースに `labels = { project = "citify", env = var.env }` を付与

## 5. Coding Agent への重要ルール

### やってほしいこと
- 既存のファイル構造に従う。新しいパターンを勝手に導入しない
- 変更前に該当ファイルの周囲を必ず読む。コンテキストを把握してから書く
- 1 つのタスクは 1 つの PR にする。複数機能を 1 度に作らない
- 不明な仕様は仮定で進めず、人間に質問する
- エラーハンドリングを必ず書く。サイレントに握りつぶさない
- 新しい依存パッケージを追加する前に、人間に確認する

### やってはいけないこと
- **docs/PROJECT.md の倫理制約に違反するコードを生成しない**(政治家描写、党派的出力など)
- 既存のコードを断りなく大規模リファクタしない
- テストを削除しない
- 環境変数や秘密情報をハードコードしない
- 「とりあえず動く」コードでドキュメントを書き換えない
- 仕様にない機能を勝手に追加しない(YAGNI 原則)

### 困ったとき
- 仕様が曖昧 → docs/FEATURES.md と docs/PROJECT.md を再読、それでも不明なら人間に質問
- 技術選定で迷う → 「変更禁止」の技術スタック内で判断、それ以外は人間に確認
- スコープが膨らみそう → Drop Points に該当しないか docs/SCHEDULE.md を確認

## 6. テスト方針

- ハッカソンなので網羅性より「コア動作の保証」を優先
- バックエンド:エージェントの入出力を pytest でユニットテスト、主要 API は smoke test
- フロント:E2E は Playwright で最低 3 シナリオ(オンボーディング、フィード表示、議題詳細)
- スクレイパー:HTML fixture を保存して、構造変化を検知する unit test
- カバレッジ目標:60% 程度。100% は目指さない

## 7. Git / GitHub ワークフロー

### ブランチ
- `main`:常にデプロイ可能な状態
- `develop`:統合ブランチ
- `feature/{機能名}`:機能ブランチ

### コミットメッセージ
- 形式:`<type>: <短い説明>` (英語)
- 例:`feat: add kokkai api scraper`、`fix: handle empty speeches`、`docs: update docs/PROJECT.md`
- type:`feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### PR
- main へは develop からのみマージ
- セルフレビュー OK(個人開発のため)
- マージ後は Cloud Build が自動デプロイ

## 8. デプロイワークフロー

1. `develop` ブランチ push → GitHub Actions で Lint + Test
2. PR を `main` に作成 → 同じく Lint + Test
3. `main` にマージ → Cloud Build で Cloud Run / Firebase Hosting にデプロイ
4. デプロイ失敗時は Cloud Build ログを Cloud Logging で確認

## 9. アンチパターン(避けること)

- **過剰設計**:7 週間で完成させる必要がある。完璧より動く方が大事
- **抽象化の早すぎる導入**:同じパターンが 3 回出現してから抽象化する
- **テスト網羅**:全部テストを書こうとして時間を溶かす
- **新技術の試食**:選定済みのスタック以外を勝手に使わない
- **Coding Agent の出力をそのまま信じる**:必ず動作確認してからマージ

## 10. Drop Points の判断

docs/SCHEDULE.md に定義された Drop Points に到達したら、躊躇なく該当機能を諦める。Coding Agent はスコープ縮小の提案を積極的に行うこと。

---

> **最後に**:このプロジェクトのゴールは「完璧な Citify を作る」ことではなく「**ハッカソンで受賞する Citify を 7/10 までに提出する**」ことです。判断に迷ったらこの一文に立ち返ってください。
