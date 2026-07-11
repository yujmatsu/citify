/** 「前回訪問以降の変化」用の lastSeen タイムスタンプ管理 (localStorage)。
 *  criterion ④ (再訪問のきっかけ) のためのリテンションフック。
 *  SSR では window が無いため、必ず typeof window ガードを通す。
 */

const STORAGE_PREFIX = "citify.lastSeen.";

/** key (例: "feed") に対応する最後に見た時刻 (ISO 文字列) を取得。未設定/SSR/取得失敗なら null。 */
export function getLastSeen(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(`${STORAGE_PREFIX}${key}`);
  } catch {
    // private mode 等で localStorage が使えない環境は黙って無視
    return null;
  }
}

/** key (例: "feed") に対応する最後に見た時刻を保存。SSR/保存失敗時は何もしない。 */
export function setLastSeen(key: string, iso: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${key}`, iso);
  } catch {
    // private mode 等で localStorage が使えない環境は黙って無視
  }
}

/**
 * itemDateIso が lastSeenIso より新しいかどうかを判定 (新着バッジ/バナー用)。
 * lastSeen が未設定 (初回訪問) の場合や、日付が不正な場合は false を返す
 * (「新着だらけ」表示にならないよう安全側に倒す)。
 */
export function isNewerThan(
  itemDateIso: string | null | undefined,
  lastSeenIso: string | null,
): boolean {
  if (!itemDateIso || !lastSeenIso) return false;
  const itemTime = Date.parse(itemDateIso);
  const lastSeenTime = Date.parse(lastSeenIso);
  if (Number.isNaN(itemTime) || Number.isNaN(lastSeenTime)) return false;
  return itemTime > lastSeenTime;
}
