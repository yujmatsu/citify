# Citify Web (Next.js 16 + App Router)

For You フィード型の自治体議事録 AI 翻訳プロダクト UI。

## 構成

- **Framework**: Next.js 16.2 (App Router, Server Components, Turbopack)
- **Style**: Tailwind CSS 4 + shadcn-style util (`cn()` ← clsx + tailwind-merge)
- **Validation**: zod
- **Routes**:
  - `/` — トップ (persona あれば feed、なければ onboarding へ)
  - `/onboarding` — A-1 年代 + 関心軸選択 (2 step、localStorage 保存)
  - `/feed` — A-8 For You フィード (TikTok 風 snap-scroll カード)
  - `/feed/[speech_id]` — A-9 議題詳細 (スコア breakdown + 原典リンク + リアクション)

## 開発フロー

```bash
cd apps/web

# 1. 依存インストール (1 回だけ)
npm install

# 2. 環境変数 (.env.local) 設定
cp .env.local.example .env.local
# NEXT_PUBLIC_API_BASE を BFF (Cloud Run citify-api) の URL に書き換え
# ローカル uvicorn 起動なら http://localhost:8080 のまま

# 3. dev server 起動
npm run dev
# → http://localhost:3000

# 4. 本番ビルド検証
npm run build
```

## BFF 連携

`/v1/feed/{user_id}` および `/v1/speeches/{speech_id}` (`apps/api/main.py`) を呼ぶ。

ローカルで BFF を立てるなら:

```bash
cd /home/yujmatsu/projects/citify/apps/api
gcloud auth application-default login   # 初回のみ
source .venv/bin/activate
uvicorn main:app --reload --port 8080
```

## Firebase App Hosting デプロイ (推奨)

`firebase.json` + `.firebaserc` + `apphosting.yaml` で構成。

### 初回セットアップ (1 回だけ)

```bash
# Firebase CLI
npm install -g firebase-tools
firebase login

# プロジェクト alias (.firebaserc に既に "default" → "citify-dev" を設定済)
firebase use citify-dev

# Backend 作成 (App Hosting GA)
# NOTE: Firebase CLI v14+ では `--location` flag は廃止、対話プロンプトのみ
firebase apphosting:backends:create --project=citify-dev
# Prompts (順不同):
#   - Region: asia-northeast1 を選択
#   - Backend ID: citify-web
#   - GitHub repo: yujmatsu/citify (OAuth 連携同意ステップあり)
#   - Root directory: apps/web
#   - Live branch: main
```

### 以降のデプロイ

main ブランチに push するだけで Firebase App Hosting が自動 build & deploy する。

### 環境変数の本番設定

`apphosting.yaml` の `env:` に書いた値は git にチェックインされるため、**秘匿値は Firebase Console から個別設定**。`NEXT_PUBLIC_API_BASE` は公開値なので yaml 直書きで OK (Cloud Run citify-api の実 URL に書き換える)。

## トラブルシュート

| 症状 | 原因 | 対処 |
|---|---|---|
| `/feed` で「フィードの取得に失敗」 | BFF 起動していない / CORS 設定 / API_BASE 誤り | `.env.local` の `NEXT_PUBLIC_API_BASE` を確認、BFF を起動 |
| `/feed` が永遠に loading | localStorage に persona が無い | `/onboarding` で setup する |
| `next build` で TypeScript エラー | zod schema と Pydantic schema が乖離 | `apps/api/main.py` の Pydantic と `src/lib/api.ts` の zod を再確認 |
| Firebase deploy で `not authorized` | gcloud + firebase の認証分離 | `firebase login` を別途実行 |
