import { describe, expect, it } from "vitest";

import {
  CompareStatsResponseSchema,
  ExtractedPreferencesSchema,
  TownAnalysisSchema,
  WatcherAnalysisResponseSchema,
} from "@/lib/api";

// front/back の契約ズレを防ぐ zod スキーマの回帰テスト (TASK: web vitest)。
// pydantic 側 (apps/api) と既定値・必須項目が一致しているかを固定する。

describe("TownAnalysisSchema", () => {
  it("最小構成をパースし既定値を埋める (Lv2.5 の investigation_plan 含む)", () => {
    const a = TownAnalysisSchema.parse({
      verdict: { headline: "今は小田原が優勢", recommended_code: "27206" },
      town_assessments: [
        { municipality_code: "13104", role: "home", headline: "基準の街" },
      ],
    });
    expect(a.verdict.headline).toContain("小田原");
    expect(a.verdict.confidence).toBe("medium"); // 既定
    expect(a.verdict.contains_political_judgment).toBe(false); // 既定
    expect(a.investigation_plan).toEqual([]); // Lv2.5 で追加・後方互換
    expect(a.specialist_findings).toEqual([]);
    expect(a.changes_since_last).toEqual([]);
    expect(a.town_assessments[0].fit_score).toBe(50); // 既定
    expect(a.town_assessments[0].confidence).toBe("medium");
  });

  it("verdict が無ければ拒否する", () => {
    expect(() => TownAnalysisSchema.parse({ town_assessments: [] })).toThrow();
  });

  it("role が enum 外なら拒否する", () => {
    expect(() =>
      TownAnalysisSchema.parse({
        verdict: { headline: "x" },
        town_assessments: [
          { municipality_code: "1", role: "invalid", headline: "y" },
        ],
      }),
    ).toThrow();
  });
});

describe("WatcherAnalysisResponseSchema", () => {
  it("analysis / latest_run が null でも 200 を許容する", () => {
    const r = WatcherAnalysisResponseSchema.parse({ user_id: "u" });
    expect(r.analysis).toBeNull();
    expect(r.latest_run).toBeNull();
  });

  it("latest_run は user_id 以外を既定で補う", () => {
    const r = WatcherAnalysisResponseSchema.parse({
      user_id: "u",
      latest_run: { user_id: "u", run_id: "r1" },
    });
    expect(r.latest_run?.status).toBe("ok"); // 既定
    expect(r.latest_run?.tool_calls).toEqual([]);
  });
});

describe("ExtractedPreferencesSchema", () => {
  it("空オブジェクトを既定で埋める", () => {
    const e = ExtractedPreferencesSchema.parse({});
    expect(e.interests).toEqual([]);
    expect(e.budget_man).toBeNull();
    expect(e.household).toBe("");
  });
});

describe("CompareStatsResponseSchema", () => {
  it("metrics + towns をパースする", () => {
    const c = CompareStatsResponseSchema.parse({
      metrics: [{ key: "fiscal", label: "財政力", direction: "higher" }],
      towns: [
        {
          municipality_code: "13104",
          municipality_name: "新宿区",
          values: { fiscal: { raw: 1.1, score: 80 } },
        },
      ],
    });
    expect(c.towns[0].municipality_name).toBe("新宿区");
    expect(c.metrics[0].direction).toBe("higher");
    expect(c.towns[0].values.fiscal.score).toBe(80);
  });
});
