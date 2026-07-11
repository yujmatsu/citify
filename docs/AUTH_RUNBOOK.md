# AUTH_RUNBOOK.md — Firebase 認証の有効化手順 (W1 / IDOR 対策)

> Citify の owned-data endpoint (watcher / concierge history) は既定で **demo 認可**
> (`x-user-id` ヘッダ == path `user_id`) で動く。これはヘッダ自己申告なので本人確認にならず、
> IDOR (他人の user_id を騙って読み書き) が成立する既知の弱点。
>
> **Firebase 認証を有効化すると**、`Authorization: Bearer <Firebase ID token>` を
> サーバー側で暗号的に検証し `uid == path user_id` を要求する = IDOR を解消する。
>
> コード (バックエンド検証 + フロント匿名サインイン) は実装・テスト済み。以下は
> **本番で live にするための人間の作業**。既定 demo のままなら現行デモは一切変わらない。

---

## 実装済み (コード)

- バックエンド: `apps/api/main.py` `_resolve_user()` / `_verify_firebase_id_token()`。
  `CITIFY_AUTH_MODE=firebase` で有効化。watcher 4 endpoint + concierge history に配線済。
  テスト: `apps/api/tests/test_auth.py` (demo/firebase/IDOR 5 ケース、firebase_admin は monkeypatch)。
  依存: `firebase-admin>=6.5` を pyproject に追加済 (firebase mode 実行時のみ import)。
- フロント: `apps/web/src/lib/auth.ts` (匿名サインイン + `getIdToken()`)、
  `lib/api.ts` `fetchJson` が firebase mode 時に `Authorization: Bearer` を付与。
  `NEXT_PUBLIC_AUTH_MODE=firebase` で有効化。既定 demo では firebase SDK を import すらしない。

---

## live にする手順

### 1. Firebase コンソール
1. Firebase プロジェクト (citify-dev の GCP プロジェクトに紐付け) で **Authentication** を有効化。
2. Sign-in method で **匿名 (Anonymous)** を有効化。
3. ウェブアプリ設定から `apiKey` / `authDomain` / `projectId` / `appId` を取得。

### 2. バックエンド (Cloud Run citify-api)
- 環境変数 `CITIFY_AUTH_MODE=firebase` を設定してデプロイ。
- ランタイム SA に Firebase Admin が使えること (ADC で verify_id_token が動く)。
- `firebase-admin` は依存に追加済 (次ビルドで入る)。

### 3. フロント (Firebase App Hosting)
- `NEXT_PUBLIC_AUTH_MODE=firebase` + `NEXT_PUBLIC_FIREBASE_API_KEY` /
  `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN` / `NEXT_PUBLIC_FIREBASE_PROJECT_ID` /
  `NEXT_PUBLIC_FIREBASE_APP_ID` を設定してデプロイ。

### 4. ⚠️ owned-data の user_id を uid に移行 (必須・未実装)
firebase mode では `uid == path user_id` を要求する。現在フロントは owned-data
(watcher/concierge) の `user_id` に `demo-{年代}` を使っているため、**そのままでは
uid ≠ demo-{年代} で 403 になる**。有効化前に、owned-data 呼び出しの `user_id` を
`firebaseUid()` (auth.ts が公開) に切り替える必要がある。

- 影響範囲: `/agent` (watcher), `/concierge` の owned-data 呼び出しの user_id。
- **フィードは変更不要**: `/v1/feed/{user_id}` は年代バケット (`demo-{年代}`) の
  共有バッチ採点を読む公開的データで、認証対象外のまま。identity (uid) と
  persona bucket (年代) を分離する設計。
- 既存の localStorage watchlist (demo-{年代} キー) は uid キーに移行されないため、
  ユーザーは再設定になる (実ユーザー不在のデモでは許容)。
- **未配線の呼び出し**: `lib/api.ts` の一部 owned-data 関数 (`postConcierge` /
  `fetchConciergeHistory` / `fetchWatchlist` / watcher 系) は共有 `fetchJson` を通らず
  `fetch()` 直呼びのため、現状 Authorization ヘッダが付かない。firebase mode を live に
  する前に、これらを `fetchJson` 経由に統一するか個別に `getIdToken()` ヘッダを付与する
  必要がある (demo mode では影響なし)。

### 5. スモーク検証
- 未ログイン/トークン無しで `/v1/watcher/{uid}/analysis` → 401。
- 他人の uid を path に指定 → 403 (IDOR 遮断の確認)。
- 自分の uid + 有効トークン → 200。

---

## ロールバック
`CITIFY_AUTH_MODE` と `NEXT_PUBLIC_AUTH_MODE` を未設定 (or `demo`) に戻して再デプロイ
→ 即座に demo 認可へ復帰 (コードは両対応)。
