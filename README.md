# Citify

> **自分の街、自分の世代の話を、60 秒で。**

Citify は、若者世代が自分の住む自治体・関心のある自治体で起きている政策・行政の動きを、TikTok 的な縦動画フィードで自然に知れる **マルチエージェント AI プロダクト** です。

自治体ホームページは「図書館」(整然と並んでいるが自分で探しに行く必要がある)。Citify は「For You フィード」(関心軸でキュレーションされ、向こうから流れてくる)。

---

## 🎯 概要

- **対象ハッカソン**: [Findy DevOps × AI Agent Hackathon 2026](https://findy.notion.site/devops-ai-agent-hackathon-2026)
- **提出締切**: 2026年7月10日 23:59
- **最終ピッチ**: 2026年8月19日 @ Google 渋谷オフィス
- **開発者**: Yuji Matsumoto（個人開発）

---

## ✨ 主な機能

### コア機能
- 📰 **For You フィード** — TikTok型縦スクロールで議題を消費
- 🗣️ **役所言葉の平易化** — 役所言葉を若者にも分かる3行サマリに翻訳
- ⚖️ **複数自治体の比較** — マイ自治体間の政策差分を表示
- 🎬 **Veo 60秒解説動画** — 議題の概念を抽象シーンで表現
- 🖼️ **Imagen サムネ生成** — フィード用ビジュアル

### データソース（すべて公開データ）
- 国会会議録 検索API (国立国会図書館)
- 自治体議事録 (kaigiroku.net、DB-Search 経由で350+自治体)
- 自治体プレスリリース RSS (47都道府県+政令市)
- e-Gov パブリックコメント
- 政府審議会議事録

### 7 体の AI エージェント
| Agent | 役割 |
|---|---|
| 📥 Collector | 議事録・プレスリリース収集 |
| 🏷️ Classifier | 議題テーマ分類 |
| 🎯 Relevance | ユーザーマッチング・スコアリング |
| 🗣️ Translator | 役所言葉→若者向け平易化 |
| ⚖️ Comparator | 複数自治体の比較 |
| 🎬 Storyteller | Veo/Imagen 統括 |
| 📤 Distributor | 配信優先順位生成 |

---

## 🛠️ 技術スタック

### バックエンド
- **言語**: Python 3.12
- **フレームワーク**: FastAPI
- **AI Agent**: ADK (Agent Development Kit)
- **LLM**: Gemini 2.5 Pro / Flash
- **RAG**: Vertex AI RAG Engine
- **動画生成**: Veo 3
- **画像生成**: Imagen 3
- **文書パース**: Document AI

### フロントエンド
- **フレームワーク**: Next.js 15 (App Router) + TypeScript
- **UI**: Tailwind CSS + shadcn/ui
- **ホスティング**: Firebase Hosting

### データ
- **Firestore** (ユーザー・議題メタ)
- **BigQuery** (議事録・分析)
- **Cloud Storage** (動画・画像)
- **Vertex AI Vector Search** (RAG インデックス)

### インフラ・DevOps
- **コンテナ実行**: Cloud Run (API + 7 Agents)
- **バッチ**: Cloud Run Jobs
- **スケジュール**: Cloud Scheduler
- **メッセージング**: Cloud Pub/Sub
- **IaC**: Terraform
- **CI**: GitHub Actions
- **CD**: Cloud Build
- **観測性**: Cloud Logging + Cloud Trace
- **シークレット**: Secret Manager

---

## 🚀 セットアップ

### 前提条件
- **開発環境**: Linux / macOS / **WSL2 (Ubuntu 24.04 推奨、Windows ユーザー向け)**
- Node.js 20+
- Python 3.12+
- Google Cloud SDK
- Terraform 1.7+
- Docker (任意)
- pnpm

> Windows ユーザーの方は、WSL2 + VSCode Remote 環境での開発を推奨しています。詳細は [docs/GETTING_STARTED.md](./docs/GETTING_STARTED.md) を参照。

### 1. リポジトリのクローン

```bash
git clone https://github.com/{your-username}/citify.git
cd citify
```

### 2. 環境変数の設定

```bash
cp .env.example .env.local
# .env.local を編集して値を設定
```

### 3. GCP プロジェクトの準備

```bash
gcloud config set project citify-dev
gcloud auth application-default login
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  bigquery.googleapis.com \
  pubsub.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com
```

### 4. インフラ構築 (Terraform)

```bash
cd infra/env/dev
terraform init
terraform plan
terraform apply
```

### 5. データシード

```bash
# 自治体マスタの投入
python -m infra.seed.load_municipalities

# サンプルデータの投入
python -m infra.seed.load_sample_topics
```

### 6. バックエンド起動

```bash
cd apps/api
uv venv && source .venv/bin/activate
uv pip install -e .
uvicorn main:app --reload
```

### 7. フロントエンド起動

```bash
cd apps/web
pnpm install
pnpm dev
```

ブラウザで `http://localhost:3000` を開く。

---

## 📁 ディレクトリ構成

```
citify/
├── README.md           # このファイル (公開フェイス)
├── CLAUDE.md           # Claude Code が自動読込
├── AGENTS.md           # 他のAIコーディングエージェント向け
├── LICENSE
├── .gitignore
├── .env.example
│
├── docs/               # 設計ドキュメント集
│   ├── PROJECT.md           # プロダクト概要 (北極星)
│   ├── FEATURES.md          # 機能仕様
│   ├── SCHEDULE.md          # 開発スケジュール
│   ├── ARCHITECTURE.md      # アーキテクチャ詳細
│   ├── DATA_SOURCES.md      # データソース仕様
│   ├── DATA_MODEL.md        # データモデル
│   ├── UI_WIREFRAMES.md     # UI ワイヤーフレーム
│   ├── AGENT_PROMPTS.md     # エージェントプロンプト集
│   ├── TERRAFORM_GUIDE.md   # Terraform 運用
│   ├── PROMPT_VERSIONS.md   # LLMOps (プロンプト管理)
│   ├── DEMO_SCRIPT.md       # デモ動画スクリプト
│   └── GETTING_STARTED.md   # 開発開始ガイド
│
├── apps/
│   ├── web/            # Next.js フロントエンド
│   └── api/            # FastAPI バックエンド
│
├── agents/             # ADK マルチエージェント (7体)
│   ├── collector/
│   ├── classifier/
│   ├── relevance/
│   ├── translator/
│   ├── comparator/
│   ├── storyteller/
│   └── distributor/
│
├── scrapers/           # データ収集パーサー
│   ├── kokkai/
│   ├── kaigiroku_net/
│   ├── db_search/
│   ├── press_rss/
│   └── ...
│
├── infra/              # Terraform IaC
│   ├── modules/
│   ├── env/dev/
│   ├── env/prod/
│   └── seed/
│
├── prompts/            # プロンプトの版管理 (Git+GCS)
│   ├── manifest.json
│   └── {agent}/
│
├── .github/workflows/  # GitHub Actions
└── cloudbuild/         # Cloud Build 定義
```

---

## 🧪 テスト

```bash
# Python
cd apps/api
pytest

# TypeScript
cd apps/web
pnpm test
pnpm type-check
```

---

## 🚢 デプロイ

```bash
# main にマージで自動デプロイ
git push origin main

# 手動デプロイ
bash scripts/deploy.sh dev
```

---

## 🔒 倫理・コンプライアンス

Citify は以下を厳守します:

- **政治的中立性**: 特定政党・候補者の推奨は一切しません
- **AI 生成コンテンツの明示**: すべての動画・画像に SynthID + ラベル付与
- **政治家描写の禁止**: 実在の政治家・首長・議員の顔・声・名前を含む生成はしません
- **議事録の引用**: 全文転載せず、要約 + 原典 URL の形式
- **個人情報の最小化**: 住所は郵便番号レベルまで、リアクションは集計後匿名化

詳細は [docs/PROJECT.md](./docs/PROJECT.md) の倫理セクション参照。

---

## 📚 ドキュメント

### ルート (AI 開発エージェント向け)
| ドキュメント | 内容 |
|---|---|
| [CLAUDE.md](./CLAUDE.md) | Claude Code 向け開発ガイド |
| [AGENTS.md](./AGENTS.md) | 他の AI コーディングエージェント向け指示 |

### 設計ドキュメント (`docs/`)
| ドキュメント | 内容 |
|---|---|
| [PROJECT.md](./docs/PROJECT.md) | 北極星：プロダクトビジョン、倫理制約 |
| [FEATURES.md](./docs/FEATURES.md) | 機能仕様 (Must/Should/Could/Won't) |
| [SCHEDULE.md](./docs/SCHEDULE.md) | 開発スケジュール + Drop Points |
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | システムアーキテクチャ詳細 |
| [DATA_SOURCES.md](./docs/DATA_SOURCES.md) | データソース仕様 |
| [DATA_MODEL.md](./docs/DATA_MODEL.md) | Firestore/BigQuery スキーマ |
| [UI_WIREFRAMES.md](./docs/UI_WIREFRAMES.md) | UI ワイヤーフレーム |
| [AGENT_PROMPTS.md](./docs/AGENT_PROMPTS.md) | 7エージェントのシステムプロンプト |
| [TERRAFORM_GUIDE.md](./docs/TERRAFORM_GUIDE.md) | Terraform 初期化・運用ガイド |
| [PROMPT_VERSIONS.md](./docs/PROMPT_VERSIONS.md) | プロンプト版管理 (LLMOps) |
| [DEMO_SCRIPT.md](./docs/DEMO_SCRIPT.md) | デモ動画・ピッチスクリプト |
| [GETTING_STARTED.md](./docs/GETTING_STARTED.md) | 開発開始ガイド |

---

## 🤝 コントリビューション

本リポジトリはハッカソン応募作品です。コントリビューションは現在受け付けていませんが、コメント・フィードバックは Issue で歓迎します。

---

## 📄 ライセンス

MIT License (詳細は [LICENSE](./LICENSE) 参照)

---

## 🙏 謝辞

- **データ提供**:
  - 国立国会図書館 (国会会議録 検索API)
  - 各自治体 (議事録・プレスリリース)
  - NTT-AT (kaigiroku.net)
- **技術提供**:
  - Google Cloud (Vertex AI, Gemini, Veo, Imagen, ADK)
  - Firebase
- **ハッカソン主催**:
  - Findy 株式会社
  - グーグル・クラウド・ジャパン合同会社

---

## 📬 お問い合わせ

- 開発者: Yuji Matsumoto
- Email: y.matsumoto@flux-g.com
- GitHub Issues: [issues](https://github.com/{your-username}/citify/issues)

---

**「自分の街、自分の世代の話を、60 秒で。」**

Citify が、若者と自治体の距離を縮めるきっかけになれたら嬉しいです。
