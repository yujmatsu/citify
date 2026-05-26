/** 関心軸 → Imagen 生成サムネ画像 URL のマッピング (Plan A-4 / B-4)。
 *
 * 画像は `apps/api/imagen/generate_interest_images.py` で 1 度生成 + GCS public 配信。
 * `NEXT_PUBLIC_INTEREST_IMAGE_BASE` (default: GCS public URL) で base URL を差替可能。
 */

const DEFAULT_IMAGE_BASE =
  process.env.NEXT_PUBLIC_INTEREST_IMAGE_BASE ??
  "https://storage.googleapis.com/citify-dev-public-assets/interests";

const INTEREST_TO_SLUG: Record<string, string> = {
  住居: "housing",
  雇用: "employment",
  結婚: "marriage",
  子育て: "childcare",
  税: "tax",
  起業: "startup",
  防災: "disaster",
  医療: "medical",
  教育: "education",
  移住: "migration",
};

/** 関心軸 (日本語) から画像 URL を返す。未登録は null。 */
export function interestImageUrl(interest: string): string | null {
  const slug = INTEREST_TO_SLUG[interest];
  if (!slug) return null;
  return `${DEFAULT_IMAGE_BASE}/${slug}.jpg`;
}

/** matched_interests の配列から最初に画像がある関心軸の URL を返す。
 *  すべて未登録なら null。 */
export function firstInterestImageUrl(interests: string[]): string | null {
  for (const it of interests) {
    const url = interestImageUrl(it);
    if (url) return url;
  }
  return null;
}
