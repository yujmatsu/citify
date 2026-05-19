# GETTING_STARTED.md — VSCode で Citify 開発を始めるガイド

> Cowork での企画段階を終え、ここから **VSCode + WSL + Claude Code** で実装を進めるためのスタートアップガイド。
>
> このファイルは「最初に何をすればいいか」が一目で分かることを目的としています。

---

## 0. 前提環境

このガイドは **Windows 11 + WSL2 (Ubuntu) + VSCode Remote** の環境を想定しています。

### WSL を使う理由
- Linux 向けのツールチェーン（gcloud, terraform, Python, Node 等）が動きやすい
- ファイルシステム性能が良い（WSL 内パスでの開発時）
- 本番 Cloud Run (Linux コンテナ) と環境が近い
- Vibe Coding 関連ツールが Linux 向けに最適化されている

### WSL がまだ入っていない場合
PowerShell を **管理者権限** で開いて：

```powershell
wsl --install -d Ubuntu-24.04
```

インストール後、Ubuntu を一度起動し、ユーザー名・パスワードを設定してください。
以降のコマンドは **すべて WSL の Ubuntu ターミナル** で実行します。

### 重要: ファイルの保管場所
**WSL 内のホームディレクトリ (`~/`)** に保管してください。`/mnt/c/...` 配下に置くと **I/O が極端に遅くなる** ため。

```bash
# 推奨
~/projects/citify

# 避ける (遅い)
/mnt/c/Users/Yujimatsumoto/Desktop/hackathon/citify
```

---

## 0.1 全体の流れ

```
[Phase 1] 環境セットアップ (30分〜1時間)
   ├─ VSCode インストール
   ├─ Claude Code インストール
   ├─ Git / Python / Node.js / gcloud / Terraform 確認
   └─ GitHub リポジトリ作成

[Phase 2] プロジェクトの初期化 (15分)
   ├─ ローカルにリポジトリをクローン
   ├─ Citify フォルダのドキュメントを移動
   ├─ 初回コミット & プッシュ

[Phase 3] Claude Code 起動 (5分)
   ├─ プロジェクトルートで claude コマンド
   ├─ キックオフプロンプトを投入
   └─ Week 0 タスクから着手

[Phase 4] 日々の開発 (Week 0-7)
   └─ docs/SCHEDULE.md に沿って進める
```

---

## 1. Phase 1: 環境セットアップ

> 以降のコマンドはすべて **WSL Ubuntu ターミナル** で実行します。

### 1.1 必須ツールの確認

```bash
# Git
git --version            # 期待: 2.40 以上 (Ubuntu 24.04 なら標準で入る)

# Node.js
node --version           # 期待: v20 以上
npm --version

# Python
python3 --version        # 期待: 3.12 以上

# pnpm (Node パッケージマネージャ)
pnpm --version           # 未インストールなら次節でインストール

# Google Cloud SDK
gcloud --version

# Terraform
terraform --version      # 期待: 1.7 以上

# GitHub CLI
gh --version             # 任意だが推奨
```

### 1.2 ツールのインストール (足りないもの)

WSL Ubuntu で必要なツールを順次インストールします。

#### Git (通常は既にあります)
```bash
sudo apt update
sudo apt install -y git
```

#### Node.js 20 (nvm 経由が推奨)
```bash
# nvm をインストール
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
source ~/.bashrc

# Node.js 20 をインストール
nvm install 20
nvm use 20
nvm alias default 20

# pnpm をインストール
npm install -g pnpm
```

#### Python 3.12 + uv
```bash
# Python は Ubuntu 24.04 標準で 3.12
sudo apt install -y python3 python3-pip python3-venv

# uv (高速な Python パッケージマネージャ)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
```

#### Google Cloud SDK
```bash
# 公式 apt リポジトリを追加
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
sudo apt update
sudo apt install -y google-cloud-cli
```

#### Terraform
```bash
# HashiCorp の公式 apt リポジトリを追加
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update
sudo apt install -y terraform
```

#### GitHub CLI (任意だが推奨)
```bash
sudo apt install -y gh
gh auth login        # ブラウザで認証
```

#### Docker (Cloud Run ローカル動作確認用、任意)
```bash
# Docker Desktop for Windows をインストールし、WSL 統合を有効化するのが最も簡単
# (Windows 側で: https://www.docker.com/products/docker-desktop/)
# 統合後、WSL 側で:
docker --version
```

### 1.3 VSCode + WSL Remote のセットアップ

#### VSCode 本体
Windows 側に [Visual Studio Code](https://code.visualstudio.com/) をインストール（既にインストール済みなら OK）。

#### WSL Remote 拡張機能 (必須)
VSCode の拡張機能から以下をインストール:

- **WSL** (Microsoft) — VSCode を WSL 内で動かす（最重要）

これにより、WSL の Linux 環境にネイティブに VSCode が接続できます。

#### その他の推奨拡張機能
| 拡張機能 | 用途 |
|---|---|
| **Python** (Microsoft) | Python サポート |
| **Pylance** | Python 型チェック |
| **Ruff** | Python フォーマッタ/リンタ |
| **ESLint** | JavaScript/TypeScript リンタ |
| **Prettier** | フォーマッタ |
| **Tailwind CSS IntelliSense** | Tailwind 補完 |
| **HashiCorp Terraform** | Terraform サポート |
| **Docker** | Docker サポート |
| **GitLens** | Git 強化 |
| **GitHub Pull Requests** | GitHub 連携 |
| **Markdown All in One** | Markdown 編集 |
| **Mermaid Preview** | 図のプレビュー |

これらは **WSL 側にもインストール** する必要があります（VSCode が WSL 接続中に拡張ボタンを押せばインストール可能）。

### 1.4 Claude Code のインストール

WSL Ubuntu のターミナルで:

```bash
# Linux 用インストーラ
curl -fsSL https://claude.ai/install.sh | sh

# PATH を反映
source ~/.bashrc

# バージョン確認
claude --version

# 初回ログイン (ブラウザが開く)
claude login
```

> **WSL 環境での Claude Code 認証について**
> WSL 内で `claude login` を実行すると、Windows のブラウザが開きます。コールバック URL をクリックすれば認証は完了します。うまく自動連携しない場合は、ターミナルに表示されるコードを **手動でブラウザに貼り付け** ても OK です。

---

## 2. Phase 2: プロジェクトの初期化

### 2.1 GitHub リポジトリの作成

```bash
# GitHub CLI で一発作成
gh repo create citify --public --description "自治体情報の For You フィード — Findy DevOps × AI Agent Hackathon 2026"

# 出力例:
# ✓ Created repository {username}/citify on GitHub
```

または、ブラウザで <https://github.com/new> からマニュアル作成：
- Repository name: `citify`
- Description: `自治体情報の For You フィード — Findy DevOps × AI Agent Hackathon 2026`
- Public
- Initialize this repository with: **空のまま**

### 2.2 ローカルクローン (WSL 内の高速領域に)

WSL のホームディレクトリ配下にプロジェクト用フォルダを作成し、そこにクローンします。

```bash
# 作業ディレクトリ作成
mkdir -p ~/projects
cd ~/projects

# 新規クローン
gh repo clone citify
# または: git clone https://github.com/{username}/citify.git

cd citify
```

> **なぜ `~/projects/` か**
> Windows 側の `C:\Users\...` ではなく WSL 内 (`~/...`) に置くのは、I/O 性能が **10〜100倍速い** ためです。`pnpm install` や `pytest` の所要時間に大きく効きます。

### 2.3 ドキュメントをリポジトリに配置

これまで作成したドキュメントは Windows 側にある想定です (`C:\Users\Yujimatsumoto\Desktop\hackathon\Citify`)。WSL からは `/mnt/c/...` でアクセスできます。

Tier 1 構成（ルート: README/CLAUDE/AGENTS、docs/: その他）に従って配置:

```bash
# Windows 側のソースパスを変数に
SRC="/mnt/c/Users/Yujimatsumoto/Desktop/hackathon/Citify"

# 念のためソースの構造を確認
ls "$SRC"
ls "$SRC/docs"

# ルートファイル (README, CLAUDE, AGENTS) をコピー
cp "$SRC/README.md" .
cp "$SRC/CLAUDE.md" .
cp "$SRC/AGENTS.md" .

# docs/ フォルダを作成して中身をコピー
mkdir -p docs
cp "$SRC/docs/"*.md docs/

# 配置確認
ls -1
ls -1 docs/
```

> **配置完了後の対応**
> Windows 側の元フォルダ `C:\Users\Yujimatsumoto\Desktop\hackathon\Citify` はそのまま残しておけば、何かあった時のバックアップになります。 不要になったタイミングで手動削除してください。

これで `citify/` 配下が以下の構造になります（Tier 1 構成）:
```
citify/
├── README.md           ← 公開フェイス
├── CLAUDE.md           ← Claude Code 専用ガイド
├── AGENTS.md           ← 他の AI コーディングエージェント向け
│
└── docs/               ← 設計ドキュメント集
    ├── PROJECT.md
    ├── FEATURES.md
    ├── SCHEDULE.md
    ├── ARCHITECTURE.md
    ├── DATA_SOURCES.md
    ├── DATA_MODEL.md
    ├── UI_WIREFRAMES.md
    ├── AGENT_PROMPTS.md
    ├── TERRAFORM_GUIDE.md
    ├── PROMPT_VERSIONS.md
    ├── DEMO_SCRIPT.md
    └── GETTING_STARTED.md  ← このファイル
```

### 2.4 `.gitignore` の作成

リポジトリルートに `.gitignore` を作成：

```bash
cd citify
```

`.gitignore` の内容：

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
.pytest_cache/
.ruff_cache/
*.egg-info/
.coverage
htmlcov/

# Node
node_modules/
.next/
out/
dist/
build/
.turbo/
*.tsbuildinfo

# Environment
.env
.env.local
.env.*.local
!.env.example

# Terraform
.terraform/
*.tfstate
*.tfstate.*
*.tfplan
.terraform.lock.hcl
crash.log
crash.*.log

# IDE
.vscode/settings.json
.idea/

# OS
.DS_Store
Thumbs.db

# GCP
.gcp/
*-key.json
service-account*.json

# Citify 固有
prompts/eval_dataset/*.local.jsonl
scrapers/**/fixtures/*.html.test
```

### 2.5 VSCode の `.vscode/settings.json` (推奨)

```json
{
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": "explicit",
    "source.fixAll.ruff": "explicit"
  },
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff"
  },
  "[typescript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "[typescriptreact]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode"
  },
  "[terraform]": {
    "editor.defaultFormatter": "hashicorp.terraform"
  },
  "python.defaultInterpreterPath": ".venv/bin/python",
  "terminal.integrated.defaultProfile.linux": "bash"
}
```

これは `.vscode/settings.json` に置く（`.gitignore` に追加済み）。

### 2.6 初回コミット & プッシュ

```bash
cd ~/projects/citify
git add .
git commit -m "docs: initial documentation set"
git push origin main
```

### 2.7 VSCode で WSL 接続してフォルダを開く

WSL Ubuntu のターミナルから:

```bash
cd ~/projects/citify
code .
```

`code .` を WSL 内で実行すると、VSCode が **自動的に WSL 接続モード** で開きます。
ウィンドウ左下に `WSL: Ubuntu` の表示が出れば成功です。

> **手動で接続する場合**
> VSCode のコマンドパレット (`Ctrl+Shift+P`) で `WSL: Connect to WSL` を実行 → `~/projects/citify` を開く、でも OK。

---

## 3. Phase 3: Claude Code 起動

### 3.1 ターミナルで Claude Code を起動

VSCode 内のターミナル (`Ctrl + @` または `表示 > ターミナル`) を開き：

```bash
# プロジェクトルートで
claude
```

`claude` コマンドが起動し、対話モードに入ります。Claude Code は **自動的に `CLAUDE.md` を読み込み**、プロジェクトコンテキストを把握します。

### 3.2 キックオフプロンプト（コピペ用）

最初のメッセージとして、以下をコピペしてください：

```text
Citify プロジェクトの開発を開始します。

私は個人開発者の Yuji です。Findy DevOps × AI Agent Hackathon 2026 への提出作品として、Citify を作ります。

## 最初にお願いしたいこと

1. 以下のドキュメントを順番に読んで、プロジェクト全体を把握してください:
   - CLAUDE.md (ルート、まず最初)
   - AGENTS.md (ルート、コーディング規約)
   - docs/PROJECT.md
   - docs/FEATURES.md
   - docs/SCHEDULE.md

2. 読み終わったら、docs/SCHEDULE.md の Week 0 (5/19-5/25) のタスクリストを確認し、現状の進捗を以下の3点でまとめてください:
   - 完了済み (ドキュメント整備など)
   - 今日着手できるタスク
   - 今週中にやるべき残タスク

3. 「今日着手できるタスク」の中で、最も基礎となるものを 1 つ提案してください。私は今からそれに取り組みます。

質問があれば遠慮なく聞いてください。
```

### 3.3 Claude Code が返してくる内容（期待）

Claude Code は以下のように応答するはずです：

1. **ドキュメントを順次 Read** する（Glob + Read ツール使用）
2. **Week 0 タスクの整理** を提示
3. **最初の着手タスク提案**（例: 「ルート package.json と pyproject.toml を作成」「Terraform バックエンド初期化」など）

### 3.4 Claude Code が止まったら

時々、Claude Code が考えすぎたり長く動いたりすることがあります。以下を覚えておきましょう：

- `Ctrl+C` : 現在の応答を中断
- `/help` : ヘルプ表示
- `/clear` : 会話履歴をクリア
- `/compact` : 会話を圧縮 (長くなったとき)
- 同じセッションで作業し続けると context が膨張するので、節目ごとに `/compact` を活用

---

## 4. Phase 4: 日々の開発ワークフロー

### 4.1 毎日のセッション開始

WSL Ubuntu ターミナルで：

```bash
cd ~/projects/citify
git pull origin main        # 最新を取得
code .                      # VSCode を WSL 接続モードで開く
```

開いた VSCode 内のターミナル (`Ctrl + @`) で：

```bash
claude
```

最初のメッセージで前回の続きを伝える：

```text
今日は Week 1 の「議事録 RAG の動作確認」をやります。
docs/SCHEDULE.md の Week 1 タスクと、docs/DATA_SOURCES.md の「1. 国会会議録 API」を参照して、最初のスクレイパーを実装してください。
```

### 4.2 1日の標準的な流れ

```
9:00  Claude Code 起動、今日のタスク確認
9:30  実装開始 (1機能 ≒ 30分〜2時間)
12:00 ランチ前にコミット & プッシュ
13:00 続き、または別機能
16:00 テスト実行
17:00 進捗確認、明日の計画
17:30 終了
```

### 4.3 タスク単位のサイクル

毎タスクで：

```
1. Claude Code に「これを実装して」と指示
2. Claude Code が実装提案 + 確認
3. 内容を確認 (重要箇所だけでOK)
4. Claude Code に「進めて」と指示
5. 実装完了
6. ターミナルで pytest / pnpm test / terraform plan で動作確認
7. git commit & push
8. 次のタスクへ
```

### 4.4 進捗管理 (毎週金曜)

週末に進捗を整理：

```text
（Claude Code に向けて）
今週の進捗をまとめてください。docs/SCHEDULE.md の Week X のタスクと照らし合わせて、完了 / 進行中 / 遅延 を整理してください。
```

---

## 5. よくあるトラブルと対処

### 5.1 Claude Code が「ファイルが見つかりません」と言う

- カレントディレクトリが間違っている可能性。`pwd` で確認、`citify/` 直下で起動してください
- Claude Code 起動後にディレクトリ移動はできません。終了して移動してから再起動

### 5.2 Claude Code がコード生成を拒否する (倫理的に)

- 「政治的中立」「政治家描写禁止」のような Citify の倫理制約に引っかかっています
- 内容を見直し、docs/PROJECT.md の倫理セクションに準拠した形で再依頼してください

### 5.3 GCP の認証エラー

```bash
gcloud auth login
gcloud auth application-default login
gcloud config set project citify-dev
```

### 5.4 「context が長くなりすぎ」と言われる

```text
/compact
```

または、新セッションを開始（古いセッションは終了）。

### 5.5 Claude Code が予想外の変更をした

```bash
# 直前のコミットに戻す (注意: 未コミット変更は失われる)
git restore .

# 一部のファイルだけ戻す
git restore path/to/file
```

### 5.6 トークン (使用量) を抑えたい

- 巨大なファイル全体を Claude Code に読み込ませない
- 必要な部分だけ Read してもらう
- `/compact` をこまめに使う
- 終わったタスクのセッションはこまめに閉じる

### 5.7 WSL: `code .` を実行しても VSCode が開かない

```bash
# Windows 側で VSCode の Path が通っているか確認
which code

# 出ない場合: VSCode 内で Ctrl+Shift+P → "Shell Command: Install 'code' command in PATH"
# その後、WSL ターミナルを再起動
```

### 5.8 WSL: ファイル操作が遅い

`/mnt/c/...` 配下を作業領域にしているのが原因。`~/projects/...` に移動してください。

```bash
# 確認
pwd
# 期待: /home/yuji/projects/citify
# 避ける: /mnt/c/Users/.../citify
```

### 5.9 WSL: クリップボード連携

WSL から Windows のクリップボードに送る:
```bash
echo "コピーしたいテキスト" | clip.exe
```

逆に Windows のクリップボードから貼り付け:
```bash
powershell.exe Get-Clipboard
```

---

## 6. VSCode + Claude Code の便利機能

### 6.1 ターミナル内で Claude Code、エディタで結果確認

VSCode を**分割表示** にすると効率的：
- 左: ファイルエディタ
- 右下: Claude Code のターミナル
- 右上: テスト実行用ターミナル

### 6.2 git diff を VSCode で確認

Claude Code が変更したファイルは VSCode のソース管理タブ (`Ctrl+Shift+G`) で確認可能。

### 6.3 Mermaid 図のプレビュー

`docs/ARCHITECTURE.md` などの Mermaid 図は VSCode 拡張「Mermaid Preview」でプレビュー可能。

### 6.4 Markdown のアウトライン

ドキュメントが長くなったら、VSCode の **アウトラインビュー** (`Ctrl+Shift+O`) でセクション間を素早く移動。

---

## 7. 今日の最初のアクションプラン

ここまで読んだら、以下を順番にやってください：

### ✅ 今日中に終わらせること (Day 1)

- [ ] WSL2 (Ubuntu) の動作確認
- [ ] Phase 1: WSL 内にツール一式インストール (Node, Python, gcloud, terraform, Claude Code)
- [ ] VSCode の WSL Remote 拡張を有効化
- [ ] Phase 2: GitHub リポジトリ作成 → `~/projects/citify` にクローン → ドキュメント配置
- [ ] Phase 3: VSCode を `code .` で開き、ターミナルで `claude` 起動 → キックオフプロンプト投入
- [ ] **GCP プロジェクト** `citify-dev` を作成 (docs/TERRAFORM_GUIDE.md Section 2.1)
- [ ] **国会会議録 API** を `curl` で叩いて動作確認 (docs/DATA_SOURCES.md Section 1)

### 📅 今週中 (Week 0: 5/19-5/25)

docs/SCHEDULE.md の Week 0 タスクリストを参照：

- [ ] docs/ARCHITECTURE.md / docs/DATA_SOURCES.md 確認 (既に完成)
- [ ] GCP プロジェクト 2つ作成 (dev/prod)
- [ ] サンプル Cloud Run のデプロイ確認
- [ ] DiscussNetPremium の HTML 構造調査
- [ ] 自治体マスタ CSV 初期作成 (50 自治体)
- [ ] **Findy Conference でハッカソン参加申込**
- [ ] **Proto Pedia アカウント作成**

---

## 8. 不安・困ったときの参照先

| 困ったこと | 参照ドキュメント |
|---|---|
| プロジェクト全体が分からなくなった | `docs/PROJECT.md` |
| 機能の優先度を確認したい | `docs/FEATURES.md` |
| Claude Code への指示の出し方 | `CLAUDE.md` (ルート) |
| コーディング規約 | `AGENTS.md` (ルート) |
| アーキテクチャの詳細 | `docs/ARCHITECTURE.md` |
| API・スクレイピング仕様 | `docs/DATA_SOURCES.md` |
| エージェントのプロンプト | `docs/AGENT_PROMPTS.md` |
| Firestore / BigQuery 設計 | `docs/DATA_MODEL.md` |
| UI 設計 | `docs/UI_WIREFRAMES.md` |
| Terraform 操作 | `docs/TERRAFORM_GUIDE.md` |
| プロンプト改善 | `docs/PROMPT_VERSIONS.md` |
| デモ動画スクリプト | `docs/DEMO_SCRIPT.md` |
| 週次スケジュール | `docs/SCHEDULE.md` |

---

## 9. メンタル面のヒント

### 9.1 完璧を目指さない

> 「7/10 までに動くものを提出する」が最優先

Drop Point の判断は躊躇なく。

### 9.2 毎日少しずつ

7週間 × 25時間/週 = 175時間。1日4時間でも十分間に合うペース。

### 9.3 詰まったら散歩

2日連続で同じバグに詰まったら、そのバグを諦めて次に進む or 散歩。

### 9.4 Claude Code に頼っていい

Vibe Coding 前提なので、わからないことは Claude Code に質問する。「これって何？」「どうやればいい？」を躊躇なく。

### 9.5 進捗を可視化

毎週金曜に GitHub の Insights や Issue/PR 一覧を眺めて、自分を褒める。

---

## 10. 最後に

> **「ハッカソンで受賞する Citify を 7/10 までに提出する」**

これだけが目標です。完璧な Citify ではなく、**完成した Citify** を作りましょう。

ここから先は Claude Code との二人三脚です。応援しています。

---

## 改訂履歴

- 2026-05-19 v0.1 初版作成
