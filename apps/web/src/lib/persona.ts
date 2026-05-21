/** ペルソナ管理 — localStorage に保存 (将来 Firestore 化)。
 *
 * A-1 オンボーディング画面で年代 + 関心軸 + 自治体を設定、
 * A-8 For You / A-9 詳細から read。
 */

import { z } from "zod";

export const AGE_GROUPS = ["18-24", "25-29", "30-34", "35+"] as const;
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

export const PersonaSchema = z.object({
  user_id: z.string(),
  age_group: z.enum(AGE_GROUPS),
  interests: z.array(z.enum(INTERESTS)).default([]),
  municipality_codes: z.array(z.string()).default([]),
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
};
