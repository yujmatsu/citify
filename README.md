# 🏛️ Citify

> **自分の街、自分の世代の話を、60 秒で。**

Citify は、自治体の議事録・プレスリリース・統計を AI が読み、役所言葉を若者の言葉に翻訳して TikTok 風フィードで届ける **マルチエージェント AI プロダクト** です。「街の見張り番」**Watcher エージェント**が自分で調査計画を立て、統計・議題・人口推移を並列調査して「あなたに合う街」を自己検証つきで結論します。

自治体ホームページは「図書館」(整然と並んでいるが自分で探しに行く必要がある)。Citify は「For You フィード」(関心軸でキュレーションされ、向こうから流れてくる)。

| | |
|---|---|
| 🌐 **デモ (デプロイ済み)** | https://citify-web--citify-dev.asia-east1.hosted.app/ |
| 🏆 **ハッカソン** | [Findy DevOps × AI Agent Hackathon 2026](https://findy.notion.site/devops-ai-agent-hackathon-2026) (提出 2026-07-10) |
| 👤 **開発** | Yuji Matsumoto (個人開発 / Vibe Coding) |

---

## 🏗️ アーキテクチャ

![Citify システムアーキテクチャ](docs/assets/architecture.svg)

全国 **1,795 自治体マスタ**、**830 自治体・議会**の **3,700 件超の議題**を処理 (2026-07 時点)。詳細は [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)。

---

## ✨ 主な機能

| 画面 | 内容 |
|---|---|
| 📰 **For You フィード** | 議事録・プレスを年代×関心×地理で採点し縦スクロール配信。Imagen サムネ + 3 行サマリ |
| 🔭 **Watcher (街の見張り番)** | ADK 自律エージェント。調査計画→ツール並列実行→自己検証→根拠つき結論 + アクションプラン |
| ⚖️ **自治体比較** | 2〜3 自治体 × テーマの横並び比較 + AI の中立観察 |
| 💬 **コンシェルジュ** | 対話で街探し。翻訳/影響度エージェントをサブエージェントに持つ ADK 親子階層 |
| 🏙️ **街ダッシュボード** | 全国順位・人口推移 (実績+推計)・年齢構成・関心軸別議題 |
| 🗾 **全国ヒートマップ / 🕰 タイムライン** | Agent が指標を自動選定する 47 都道府県比較 / 議論の時系列ナラティブ |
| 🩺 **運用エージェント** | スクレイパー失敗診断 (Scraper Doctor)・コスト異常検知 (Cost Hunter)。人間レビュー前提 |

### スクリーンショット

| For You フィード | Watcher | 街ダッシュボード |
|---|---|---|
| ![feed](docs/submission/screenshots/01_feed.png) | ![watcher](docs/submission/screenshots/02_agent_watcher.png) | ![city](docs/submission/screenshots/04_city_dashboard.png) |

---

## 🤖 13 の AI エージェント

| 系統 | Agent | 役割 |
|---|---|---|
| パイプライン (Pub/Sub + Cloud Run Jobs) | 🖊️ Translator | 役所言葉→年代別に平易化 (Gemini 2.5 Flash) |
| | 🎯 Relevance | 4 軸採点 × 5 ペルソナ fan-out |
| | 📮 Distributor | MMR 多様性ランキング (非 LLM・設計判断) |
| | 🧪 Critic | 翻訳品質の自己批評ループ (`CITIFY_ENABLE_CRITIQUE=1` で opt-in) |
| ADK (自律・対話) | 🔭 Watcher | 自律ツールループ + 自己検証。本作のヒーロー |
| | 💬 Concierge | sub_agents=[Translator, Relevance] の親子階層 |
| | 📝 Preferences | 自然言語の自己紹介から関心軸を構造化抽出 |
| 分析 API | 🕰 Timeline / 📈 Forecast / 🗾 Heatmap Advisor / 🔍 Reasoner | 時系列ナラティブ / 件数予測 / 指標自動選定 / 説明の平易化 (全てルールベース fallback 付き) |
| 運用 (DevOps × AI Agent) | 🩺 Scraper Doctor | 失敗ログを診断し修正提案 (自動 PR はしない) |
| | 💰 Cost Hunter | コスト異常検知 + 削減提案 (自動削減はしない) |

---

## 📥 データソース (すべて公開データ)

- 国会会議録 検索 API (国立国会図書館) — 発言 2,000 件超 + RAG corpus 1,428 件
- 自治体議事録 (kaigiroku.net / Playwright)
- 自治体プレスリリース RSS (都道府県 + 政令市 + 中核市 = 45 自治体)
- e-Stat 国勢調査 / 不動産情報ライブラリ (Reinfolib) — 統計・人口推移

> DB-Search 系 (150+ 自治体) は robots.txt が議事録パスを全面 Disallow のため**対応コードごと Drop** しました (倫理方針: robots.txt 尊重)。

---

## 🛠️ 技術スタック

| 層 | 技術 |
|---|---|
| AI | **ADK** (Watcher/Concierge/Preferences) / **Gemini 2.5 Pro・Flash** / **Vertex AI RAG Engine** / **Imagen 3** / Embeddings (text-multilingual-embedding-002) |
| バックエンド | Python 3.12 / FastAPI / Cloud Run + Cloud Run Jobs / Pub/Sub (4 段パイプライン + DLQ) |
| データ | BigQuery / Firestore / Cloud Storage |
| フロントエンド | Next.js 16 (App Router) + TypeScript / Tailwind CSS / zod / Firebase App Hosting |
| DevOps | Terraform (全リソース IaC) / GitHub Actions (ruff・pytest・tsc・vitest・build) / Cloud Build (パスベース検知→自動デプロイ) / Cloud Scheduler / Cloud Logging |

---

## 🚀 セットアップ

### 前提条件
- **開発環境**: Linux / macOS / **WSL2 (Ubuntu 24.04 推奨、Windows ユーザー向け)**
- Node.js 20+ / Python 3.12+ / Google Cloud SDK / Terraform 1.7+

> Windows ユーザーの方は、WSL2 + VSCode Remote 環境での開発を推奨しています。詳細は [docs/GETTING_STARTED.md](./docs/GETTING_STARTED.md) を参照。

### 1. リポジトリのクローン

```bash
git clone https://github.com/yujmatsu/citify.git
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
gcloud auth application-default set-quota-project citify-dev
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  pubsub.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  logging.googleapis.com \
  cloudtrace.googleapis.com \
  iamcredentials.googleapis.com
```

### 4. インフラ構築 (Terraform)

```bash
cd infra/env/dev
terraform init
terraform plan
terraform apply
```

### 5. バックエンド起動

```bash
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn main:app --reload
```

### 6. フロントエンド起動

```bash
cd apps/web
npm install
npm run dev
```

ブラウザで `http://localhost:3000` を開く。

---

## 📁 ディレクトリ構成

```
citify/
├── README.md           # このファイル (公開フェイス)
├── CLAUDE.md           # Claude Code が自動読込
├── AGENTS.md           # 他のAIコーディングエージェント向け
│
├── docs/               # 設計ドキュメント集
│   ├── PROJECT.md           # プロダクト概要 (北極星)
│   ├── FEATURES.md          # 機能仕様
│   ├── ARCHITECTURE.md      # アーキテクチャ詳細
│   ├── DEMO_SCRIPT.md       # デモ動画スクリプト
│   ├── assets/              # アーキテクチャ図 (SVG/PNG)
│   └── submission/          # ProtoPedia 提出素材 + スクリーンショット
│
├── apps/
│   ├── web/            # Next.js フロントエンド (16 画面)
│   ├── api/            # FastAPI BFF (Cloud Run)
│   └── workers/        # Cloud Run Jobs (Pub/Sub workers)
│
├── agents/             # 13 AI エージェント
│   ├── translator/ relevance/ distributor/ critic/     # パイプライン
│   ├── watcher/ concierge/ preferences/                # ADK (自律・対話)
│   ├── timeline/ forecast/ heatmap_advisor/ reasoner/  # 分析 API
│   ├── scraper_doctor/ cost_hunter/                    # 運用
│   └── _shared/                                        # 共通倫理ガードレール
│
├── scrapers/           # データ収集
│   ├── kokkai/             # 国会会議録 API (JSON)
│   ├── kaigiroku_net/      # DiscussNet SPA (Playwright)
│   ├── press_rss/          # プレスリリース RSS (45 自治体)
│   ├── reinfolib/          # 不動産情報ライブラリ (統計・人口)
│   └── voices_asp/         # VOICES (robots.txt 制約で limited scope)
│
├── infra/              # Terraform IaC + seed データ
├── scripts/            # 運用スクリプト
└── .github/workflows/  # GitHub Actions
```

---

## 🧪 テスト

```bash
# Python (700+ tests)
apps/api/.venv/bin/python -m pytest

# TypeScript
cd apps/web
npx vitest run
npx tsc --noEmit
```

---

## 🚢 デプロイ

```bash
# main にマージで自動デプロイ (Cloud Build: API / Firebase App Hosting: web)
git push origin main

# workers (Cloud Run Jobs) は手動トリガー
gcloud builds submit --config cloudbuild-workers.yaml
```

---

## 🔒 倫理・コンプライアンス

Citify は以下を厳守します:

- **政治的中立性**: 特定政党・候補者の推奨は一切しません。賛否も出しません (多層ガードレール + 失敗時ルールベース代替)
- **AI 生成コンテンツの明示**: すべての画像に SynthID + 「AI 生成」ラベル付与
- **政治家描写の禁止**: 実在の政治家・首長・議員の顔・声・名前を含む生成はしません (`person_generation="dont_allow"`)
- **議事録の引用**: 全文転載せず、要約 + 原典 URL の形式
- **robots.txt の尊重**: Disallow のソースは対応コードごと Drop
- **個人情報の最小化**: リアクションは集計後匿名化

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
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | システムアーキテクチャ詳細 |
| [DATA_SOURCES.md](./docs/DATA_SOURCES.md) | データソース仕様 |
| [DATA_MODEL.md](./docs/DATA_MODEL.md) | Firestore/BigQuery スキーマ |
| [DEMO_SCRIPT.md](./docs/DEMO_SCRIPT.md) | デモ動画・ピッチスクリプト |
| [TERRAFORM_GUIDE.md](./docs/TERRAFORM_GUIDE.md) | Terraform 初期化・運用ガイド |
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
  - 政府統計の総合窓口 e-Stat / 国土交通省 不動産情報ライブラリ
- **技術提供**:
  - Google Cloud (Vertex AI, Gemini, Imagen, ADK)
  - Firebase
- **ハッカソン主催**:
  - Findy 株式会社
  - グーグル・クラウド・ジャパン合同会社

---

## 📬 お問い合わせ

- 開発者: Yuji Matsumoto
- GitHub Issues: [issues](https://github.com/yujmatsu/citify/issues)

---

**「自分の街、自分の世代の話を、60 秒で。」**

Citify が、若者と自治体の距離を縮めるきっかけになれたら嬉しいです。
