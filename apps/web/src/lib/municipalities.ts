/** 自治体マスタ (1,795 件) ローダ + 検索 util。
 *
 * 静的 JSON (`/public/municipalities.json`) を fetch して in-memory にキャッシュ。
 * Tier 1 (国会 + 23 区 + 政令市 + 都道府県) を default 表示用に分離。
 */

import { z } from "zod";

export const MunicipalitySchema = z.object({
  code: z.string(), // 5 桁、"00000" は国会
  name: z.string(),
  prefecture: z.string(),
  kana: z.string(),
  tier: z.number().int().min(1).max(3),
  is_active: z.boolean(),
});

export type Municipality = z.infer<typeof MunicipalitySchema>;

const ResponseSchema = z.object({ items: z.array(MunicipalitySchema) });

const NATIONAL_DIET_CODE = "00000";

let _cache: Municipality[] | null = null;
let _loadingPromise: Promise<Municipality[]> | null = null;

/** ブラウザの fetch で municipalities.json を読み込み (キャッシュあり)。 */
export async function loadMunicipalities(): Promise<Municipality[]> {
  if (_cache) return _cache;
  if (_loadingPromise) return _loadingPromise;
  _loadingPromise = fetch("/municipalities.json", { cache: "force-cache" })
    .then((r) => {
      if (!r.ok)
        throw new Error(`HTTP ${r.status}: failed to load municipalities.json`);
      return r.json();
    })
    .then((d) => {
      const parsed = ResponseSchema.parse(d);
      _cache = parsed.items;
      return _cache;
    });
  return _loadingPromise;
}

/** 検索 (前方一致): 名前 / 読み仮名 / 都道府県。 */
export function searchMunicipalities(
  all: Municipality[],
  query: string,
  opts?: { tier?: 1 | 2 | 3; prefecture?: string; limit?: number },
): Municipality[] {
  const q = query.trim().toLowerCase();
  const tier = opts?.tier;
  const prefecture = opts?.prefecture;
  const limit = opts?.limit ?? 50;

  return all
    .filter((m) => {
      if (tier && m.tier !== tier) return false;
      if (prefecture && m.prefecture !== prefecture) return false;
      if (!q) return true;
      return (
        m.name.toLowerCase().includes(q) ||
        m.kana.toLowerCase().includes(q) ||
        m.prefecture.toLowerCase().includes(q) ||
        m.code.startsWith(q)
      );
    })
    .slice(0, limit);
}

/** 都道府県一覧を取り出す。 */
export function listPrefectures(all: Municipality[]): string[] {
  const set = new Set<string>();
  for (const m of all) {
    if (m.prefecture && m.prefecture !== "国") set.add(m.prefecture);
  }
  return Array.from(set).sort();
}

/** code から自治体オブジェクトを引く。 */
export function findByCode(
  all: Municipality[],
  code: string,
): Municipality | undefined {
  return all.find((m) => m.code === code);
}

/** 表示用ラベル: "東京都新宿区" (国会は単に "国会")。 */
export function formatMunicipalityLabel(m: Municipality): string {
  if (m.code === NATIONAL_DIET_CODE) return "🏛️ 国会";
  if (m.prefecture === m.name) return m.prefecture;
  return `${m.prefecture}${m.name}`;
}

export const NATIONAL_DIET = {
  code: NATIONAL_DIET_CODE,
  name: "国会",
  prefecture: "国",
  kana: "コッカイ",
  tier: 1 as const,
  is_active: true,
};
