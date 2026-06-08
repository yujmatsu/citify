/** ペルソナ管理 — localStorage に保存 (将来 Firestore 化)。
 *
 * A-1 オンボーディング画面で年代 + 関心軸 + 自治体を設定、
 * A-8 For You / A-9 詳細から read。
 */

import { z } from "zod";

export const AGE_GROUPS = [
  "18-24",
  "25-29",
  "30-39",
  "40-49",
  "50+",
] as const;
export type AgeGroup = (typeof AGE_GROUPS)[number];

export const INTERESTS = [
  "住居",
  "雇用",
  "結婚",
  "子育て",
  "税",
  "起業",
  "防災",
  "医療",
  "教育",
  "移住",
] as const;
export type Interest = (typeof INTERESTS)[number];

// TASK-ONBOARDING: 前提整理 (B 家族構成)
export const HOUSEHOLDS = ["single", "couple", "family_kids", "other"] as const;
export type Household = (typeof HOUSEHOLDS)[number];
export const HOUSEHOLD_LABELS: Record<Household, string> = {
  single: "単身",
  couple: "夫婦・パートナー",
  family_kids: "子どもがいる世帯",
  other: "その他",
};

export const PersonaSchema = z.object({
  user_id: z.string(),
  age_group: z.enum(AGE_GROUPS),
  interests: z.array(z.enum(INTERESTS)).default([]),
  municipality_codes: z.array(z.string()).default([]),
  // TASK-ONBOARDING: 前提整理 (全て省略可・後方互換)
  priorities: z.array(z.enum(INTERESTS)).default([]), // A: 上位3順位 (interests の部分集合)
  household: z.enum(HOUSEHOLDS).nullable().default(null), // B
  budget_man: z.number().nullable().default(null), // B: 中古マンション/家賃上限(万円)
  area_pref: z.array(z.string()).default([]), // B: 希望都道府県コード(2桁)
  free_form_context: z.string().default(""), // C: 移住の背景・動機
});

export type Persona = z.infer<typeof PersonaSchema>;

const STORAGE_KEY = "citify.persona";

/** localStorage から読む。未設定なら null。 */
export function loadPersona(): Persona | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return PersonaSchema.parse(JSON.parse(raw));
  } catch {
    return null;
  }
}

/** localStorage に保存。 */
export function savePersona(p: Persona): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
}

/** デモ用 default ペルソナ (Cloud Run worker と整合)。 */
export const DEMO_PERSONA: Persona = {
  user_id: "demo-25-29",
  age_group: "25-29",
  interests: ["住居", "雇用", "税", "子育て"],
  municipality_codes: ["33000", "00000"],
  priorities: ["子育て", "住居"],
  household: null,
  budget_man: null,
  area_pref: ["33"],
  free_form_context: "",
};

// ============================================================================
// ウォッチ街 (マイ街エージェント Slice 3) — persona の municipality_codes を
// 「住む街(先頭) + 気になる街(残り)」として解釈する。スキーマは変えず互換維持。
// ============================================================================

/** 住む街コード (municipality_codes の先頭)。未設定なら null。 */
export function homeCode(p: Persona): string | null {
  return p.municipality_codes[0] ?? null;
}

/** 気になる街コード (municipality_codes の 2 件目以降)。 */
export function watchedCodes(p: Persona): string[] {
  return p.municipality_codes.slice(1);
}
