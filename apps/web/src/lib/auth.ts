/** Firebase 匿名認証 — AUTH_MODE="firebase" の時のみ有効化される薄いラッパ。
 *
 * デフォルト (AUTH_MODE="demo") では一切 firebase を import せず、
 * 既存の x-user-id ヘッダ運用 (apps/web/src/lib/api.ts) を変更しない。
 * 将来 CITIFY_AUTH_MODE=firebase (backend) と組み合わせて
 * Authorization: Bearer <Firebase ID token> を送るための土台。
 *
 * 環境変数 (firebase モード時のみ必須):
 *   NEXT_PUBLIC_AUTH_MODE           "demo" (default) | "firebase"
 *   NEXT_PUBLIC_FIREBASE_API_KEY
 *   NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
 *   NEXT_PUBLIC_FIREBASE_PROJECT_ID
 *   NEXT_PUBLIC_FIREBASE_APP_ID
 */

import type { Auth } from "firebase/auth";

export const AUTH_MODE = process.env.NEXT_PUBLIC_AUTH_MODE ?? "demo";

type AuthState = { authObj: Auth };

// 初期化 (app 生成 + 匿名サインイン) は最初の呼び出し時に一度だけ実行し、以降は共有する。
let statePromise: Promise<AuthState> | null = null;
// firebaseUid() は同期 API のため、サインイン完了時に更新するキャッシュを持つ。
let cachedUid: string | null = null;

/** firebase app / auth を遅延初期化し、匿名サインインを (未サインインなら) 一度だけ行う。 */
async function ensureSignedIn(): Promise<AuthState | null> {
  if (AUTH_MODE !== "firebase") return null;
  if (typeof window === "undefined") return null;

  if (!statePromise) {
    statePromise = (async () => {
      const { initializeApp, getApps } = await import("firebase/app");
      const { getAuth, signInAnonymously } = await import("firebase/auth");

      const app =
        getApps()[0] ??
        initializeApp({
          apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
          authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
          projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
          appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
        });
      const authObj = getAuth(app);

      // 永続化された前回サインインの復元を待ってから、未サインインの場合のみ匿名サインイン。
      await authObj.authStateReady();
      if (!authObj.currentUser) {
        await signInAnonymously(authObj);
      }
      cachedUid = authObj.currentUser?.uid ?? null;
      return { authObj };
    })();
  }
  return statePromise;
}

/**
 * 現在の Firebase ID token を取得する ("firebase" モード以外は常に null)。
 * サインイン未完了なら待機する。失敗時は例外を投げず null を返す
 * (呼び出し側は「認証ヘッダなし」で継続できるようにするため)。
 */
export async function getIdToken(): Promise<string | null> {
  try {
    const state = await ensureSignedIn();
    if (!state) return null;
    const user = state.authObj.currentUser;
    if (!user) return null;
    return await user.getIdToken();
  } catch {
    statePromise = null; // 次回呼び出しでリトライできるようにリセット
    return null;
  }
}

/** 匿名サインイン中の uid ("firebase" モード以外、または未サインインは null)。将来の owned-data キー用。 */
export function firebaseUid(): string | null {
  return AUTH_MODE === "firebase" ? cachedUid : null;
}
