/** プリセット・ペルソナ (TASK-UX: 価値到達の短縮)。
 *
 * 設定ゼロで「触ってすぐ結論」を体験させるための既製ペルソナ。
 * 1タップで persona を保存し /agent へ → そのまま分析を体感できる。デモにも有効。
 * municipality_codes は [住む街(現在), ...気になる街(候補)] 順 (persona.homeCode/watchedCodes 解釈)。
 */

import type { Persona } from "@/lib/persona";

export type PresetPersona = {
  id: string;
  emoji: string;
  label: string;
  description: string;
  persona: Persona;
};

/** 選択街の都道府県コード(先頭2桁、国会00除外)を一意化。 */
function areaOf(codes: string[]): string[] {
  return Array.from(
    new Set(codes.map((c) => c.slice(0, 2)).filter((p) => p !== "00")),
  );
}

const HOME_TOKYO = "13104"; // 新宿区
const HOME_OSAKA = "27100"; // 大阪市
const ODAWARA = "14206";
const FUKUOKA = "40130";
const YOKOHAMA = "14100";

export const PRESET_PERSONAS: PresetPersona[] = [
  {
    id: "family-kids",
    emoji: "👶",
    label: "子育て世帯・東京から地方へ",
    description: "家賃と子育て環境に悩み、医療・教育を重視して移住を検討",
    persona: {
      user_id: "demo-30-39",
      age_group: "30-39",
      interests: ["子育て", "住居", "医療", "教育"],
      municipality_codes: [HOME_TOKYO, ODAWARA, FUKUOKA],
      priorities: ["子育て", "医療", "住居"],
      household: "family_kids",
      budget_man: 3000,
      area_pref: areaOf([HOME_TOKYO, ODAWARA, FUKUOKA]),
      free_form_context:
        "東京の家賃と子育て環境に悩み、地方移住を検討している。",
    },
  },
  {
    id: "remote-single",
    emoji: "💻",
    label: "リモートワークの単身20代",
    description: "場所に縛られず、家賃を抑えて身軽に暮らしたい",
    persona: {
      user_id: "demo-25-29",
      age_group: "25-29",
      interests: ["住居", "雇用", "移住"],
      municipality_codes: [HOME_TOKYO, ODAWARA, FUKUOKA],
      priorities: ["住居", "移住", "雇用"],
      household: "single",
      budget_man: 2000,
      area_pref: areaOf([HOME_TOKYO, ODAWARA, FUKUOKA]),
      free_form_context:
        "リモートワークで場所に縛られず、家賃を抑えて暮らしたい。",
    },
  },
  {
    id: "second-life",
    emoji: "🌿",
    label: "セカンドライフの夫婦",
    description: "定年後、医療と落ち着いた暮らしを重視して移住を検討",
    persona: {
      user_id: "demo-50+",
      age_group: "50+",
      interests: ["医療", "住居", "防災"],
      municipality_codes: [HOME_OSAKA, ODAWARA, YOKOHAMA],
      priorities: ["医療", "住居", "防災"],
      household: "couple",
      budget_man: 2500,
      area_pref: areaOf([HOME_OSAKA, ODAWARA, YOKOHAMA]),
      free_form_context:
        "定年後、医療体制と落ち着いた暮らしを重視して移住を検討している。",
    },
  },
];
