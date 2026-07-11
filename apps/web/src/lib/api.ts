/** Citify BFF (FastAPI) クライアント — TypeScript + zod 型安全。
 *
 * 環境変数:
 *   NEXT_PUBLIC_API_BASE (例: https://citify-api-xxxxx.a.run.app, default: http://localhost:8080)
 */

import { z } from "zod";
import { AUTH_MODE, getIdToken } from "@/lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080";

// ============================================================================
// Schemas (apps/api main.py の Pydantic と一致させる)
// ============================================================================

export const FeedItemSchema = z.object({
  speech_id: z.string(),
  title: z.string().nullable(),
  summary: z.array(z.string()).default([]),
  detail_url: z.string().nullable(),
  meeting_date: z.string().nullable(), // ISO date 文字列 or null
  municipality_code: z.string().nullable(),
  name_of_meeting: z.string().nullable(),
  speaker_position: z.string().nullable(),
  tone: z.string().nullable(),

  relevance_score: z.number().int(),
  score_topic: z.number().int(),
  score_age: z.number().int(),
  score_geographic: z.number().int(),
  score_urgency: z.number().int(),
  matched_interests: z.array(z.string()).default([]),
  reasoning: z.string().nullable(),
});

export type FeedItem = z.infer<typeof FeedItemSchema>;

export const FeedResponseSchema = z.object({
  user_id: z.string(),
  items: z.array(FeedItemSchema),
  total: z.number().int().nonnegative(),
});

export type FeedResponse = z.infer<typeof FeedResponseSchema>;

// ============================================================================
// Client functions
// ============================================================================

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchJson<T extends z.ZodTypeAny>(
  url: string,
  schema: T,
  init?: RequestInit,
): Promise<z.infer<T>> {
  // Phase Q: 呼び出し側で cache を指定しない場合は "default" にし、
  // BFF が返す Cache-Control header (max-age) をブラウザ HTTP cache で活用する。
  // リアルタイム性が必要な reaction 系は呼び出し側で明示的に "no-store" を指定。
  const headers: HeadersInit = {
    Accept: "application/json",
    ...(init?.headers ?? {}),
  };
  // AUTH_MODE="firebase" の時のみ Authorization を付与する。
  // デフォルト (demo) では getIdToken を呼ばず、既存の x-user-id 運用を一切変えない。
  if (AUTH_MODE === "firebase") {
    const token = await getIdToken();
    if (token) {
      (headers as Record<string, string>).Authorization = `Bearer ${token}`;
    }
  }
  const res = await fetch(url, {
    ...init,
    headers,
    cache: init?.cache ?? "default",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  return schema.parse(data);
}

/**
 * ユーザー別フィード取得。
 * @param userId  - ペルソナ ID (例: 'demo-25-29')
 * @param opts.minRelevance - 0-100 スコア閾値 (default 0)
 * @param opts.limit        - 取得上限 (default 20, max 100)
 */
export async function fetchFeed(
  userId: string,
  opts?: { minRelevance?: number; limit?: number },
): Promise<FeedResponse> {
  const params = new URLSearchParams();
  if (opts?.minRelevance != null)
    params.set("min_relevance", String(opts.minRelevance));
  if (opts?.limit != null) params.set("limit", String(opts.limit));
  const qs = params.toString() ? `?${params.toString()}` : "";
  return fetchJson(
    `${API_BASE}/v1/feed/${encodeURIComponent(userId)}${qs}`,
    FeedResponseSchema,
  );
}

/** 1 件の speech 詳細取得 (user_id コンテキストで採点情報込み)。 */
export async function fetchSpeech(
  speechId: string,
  userId: string,
): Promise<FeedItem> {
  const url = `${API_BASE}/v1/speeches/${encodeURIComponent(speechId)}?user_id=${encodeURIComponent(
    userId,
  )}`;
  return fetchJson(url, FeedItemSchema);
}

// ============================================================================
// Related (RAG) — A-9 詳細ビュー用
// ============================================================================

export const RelatedContextSchema = z.object({
  text: z.string(),
  source_uri: z.string().default(""),
  distance: z.number().nullable(),
});

export type RelatedContext = z.infer<typeof RelatedContextSchema>;

export const RelatedResponseSchema = z.object({
  speech_id: z.string(),
  query_text: z.string(),
  items: z.array(RelatedContextSchema),
  corpus_used: z.string().nullable(),
});

export type RelatedResponse = z.infer<typeof RelatedResponseSchema>;

/**
 * 1 speech から RAG で関連発言を取得 (Vertex AI RAG corpus、国会会議録)。
 * @param speechId  - 元 speech_id
 * @param userId    - ペルソナ ID (BQ から元 speech を引くため必要)
 * @param limit     - 取得上限 (default 3, max 10)
 */
export async function fetchRelated(
  speechId: string,
  userId: string,
  limit = 3,
): Promise<RelatedResponse> {
  const url = `${API_BASE}/v1/speeches/${encodeURIComponent(
    speechId,
  )}/related?user_id=${encodeURIComponent(userId)}&limit=${limit}`;
  return fetchJson(url, RelatedResponseSchema);
}

// ============================================================================
// Reactions (Phase X) — Firestore 永続化
// ============================================================================

export const REACTION_VALUES = ["👍", "🤔", "😢", "🔥"] as const;
export type Reaction = (typeof REACTION_VALUES)[number];

export const ReactionResponseSchema = z.object({
  speech_id: z.string(),
  user_id: z.string(),
  reaction: z.enum(REACTION_VALUES).nullable(),
  updated_at: z.string().nullable(),
});

export type ReactionResponse = z.infer<typeof ReactionResponseSchema>;

function reactionUrl(speechId: string, userId: string): string {
  return `${API_BASE}/v1/speeches/${encodeURIComponent(
    speechId,
  )}/reaction?user_id=${encodeURIComponent(userId)}`;
}

/** 現在のリアクションを取得 (未設定なら reaction=null)。リアルタイム性が必要なので no-store。 */
export async function fetchReaction(
  speechId: string,
  userId: string,
): Promise<ReactionResponse> {
  return fetchJson(reactionUrl(speechId, userId), ReactionResponseSchema, {
    cache: "no-store",
  });
}

/** リアクションを設定 or 上書き。 */
export async function setReaction(
  speechId: string,
  userId: string,
  reaction: Reaction,
): Promise<ReactionResponse> {
  return fetchJson(reactionUrl(speechId, userId), ReactionResponseSchema, {
    method: "PUT",
    // x-user-id: demo 認可 (path user_id と一致必須)。firebase 時は fetchJson が
    // Authorization を自動付与。共有集計の無認証書き込み汚染を防ぐ。
    headers: { "Content-Type": "application/json", "x-user-id": userId },
    body: JSON.stringify({ reaction }),
    cache: "no-store",
  });
}

/** リアクションを解除 (冪等)。 */
export async function clearReaction(
  speechId: string,
  userId: string,
): Promise<ReactionResponse> {
  return fetchJson(reactionUrl(speechId, userId), ReactionResponseSchema, {
    method: "DELETE",
    // x-user-id: demo 認可 (put_reaction と同様、共有集計の書き込み汚染を防ぐ)。
    headers: { "x-user-id": userId },
    cache: "no-store",
  });
}

// ============================================================================
// Reactions Summary (Phase X+1) — 全 user の集計件数
// ============================================================================

export const ReactionSummarySchema = z.object({
  speech_id: z.string(),
  counts: z.record(z.enum(REACTION_VALUES), z.number().int().nonnegative()),
  total: z.number().int().nonnegative(),
});

export type ReactionSummary = z.infer<typeof ReactionSummarySchema>;

/** speech 1 件のリアクション集計を取得 (全 user 合算、4 種絵文字を必ず key として含む)。 */
export async function fetchReactionSummary(
  speechId: string,
): Promise<ReactionSummary> {
  const url = `${API_BASE}/v1/speeches/${encodeURIComponent(
    speechId,
  )}/reactions/summary`;
  return fetchJson(url, ReactionSummarySchema, { cache: "no-store" });
}

// ============================================================================
// Compare (B-2 比較ビュー) — 複数自治体の同テーマ議題横並び
// ============================================================================

export const CompareSpeechSchema = z.object({
  speech_id: z.string(),
  title: z.string().nullable(),
  summary: z.array(z.string()).default([]),
  detail_url: z.string().nullable(),
  meeting_date: z.string().nullable(),
  name_of_meeting: z.string().nullable(),
  matched_interests: z.array(z.string()).default([]),
  relevance_score: z.number().int(),
});

export type CompareSpeech = z.infer<typeof CompareSpeechSchema>;

export const ComparisonColumnSchema = z.object({
  municipality_code: z.string(),
  speeches: z.array(CompareSpeechSchema).default([]),
});

export type ComparisonColumn = z.infer<typeof ComparisonColumnSchema>;

export const CompareResponseSchema = z.object({
  user_id: z.string(),
  interest: z.string(),
  municipality_codes: z.array(z.string()),
  columns: z.array(ComparisonColumnSchema),
  observation: z.string().nullable(),
});

export type CompareResponse = z.infer<typeof CompareResponseSchema>;

/**
 * 複数自治体 (2-3) を同テーマで比較。
 * @param userId  ペルソナ ID
 * @param munis   municipality_code 配列 (2-3 件)
 * @param interest 比較対象テーマ (matched_interests の 1 つ、例: "子育て")
 * @param limit   各自治体ごとの最大件数 (default 3)
 */
export async function fetchCompare(
  userId: string,
  munis: string[],
  interest: string,
  limit = 3,
): Promise<CompareResponse> {
  const params = new URLSearchParams({
    user_id: userId,
    munis: munis.join(","),
    interest,
    limit: String(limit),
  });
  return fetchJson(`${API_BASE}/v1/compare?${params.toString()}`, CompareResponseSchema);
}

// ============================================================================
// City Dashboard (Plan A-3) — 「あなたの街が今どうなっているか」
// ============================================================================

export const MunicipalityStatsSchema = z.object({
  population_total: z.number().int().nullable(),
  population_15_29: z.number().int().nullable(),
  population_65_plus: z.number().int().nullable(),
  households_total: z.number().int().nullable(),
  births_annual: z.number().int().nullable(),
  youth_share_pct: z.number().nullable(),
  elderly_share_pct: z.number().nullable(),
  population_change_pct: z.number().nullable(),
  birth_rate_per_1000: z.number().nullable(),
  data_year: z.number().int().nullable(),
  source_url: z.string().nullable(),
  // Phase F: Reinfolib 由来 (optional、未投入自治体は null)
  used_apartment_median_price_man_yen: z.number().int().nullable().optional(),
  used_apartment_sample_size: z.number().int().nullable().optional(),
  used_apartment_median_unit_price_yen: z.number().int().nullable().optional(),
  used_apartment_avg_building_age: z.number().nullable().optional(),
  emergency_shelter_count: z.number().int().nullable().optional(),
  emergency_shelter_official_link: z.string().nullable().optional(),
  // Phase F v3
  population_2025_estimated: z.number().int().nullable().optional(),
  population_2050_estimated: z.number().int().nullable().optional(),
  population_change_2025_2050_pct: z.number().nullable().optional(),
  medical_facility_count: z.number().int().nullable().optional(),
  medical_hospital_count: z.number().int().nullable().optional(),
  medical_clinic_count: z.number().int().nullable().optional(),
  childcare_facility_count: z.number().int().nullable().optional(),
  kindergarten_count: z.number().int().nullable().optional(),
  nursery_count: z.number().int().nullable().optional(),
  reinfolib_source_url: z.string().nullable().optional(),
  // TASK-FISCAL: 社会・人口統計体系 由来 5 指標
  financial_capability_index: z.number().nullable().optional(),
  real_debt_service_ratio_pct: z.number().nullable().optional(),
  taxable_income_per_capita_yen: z.number().int().nullable().optional(),
  homeownership_rate_pct: z.number().nullable().optional(),
  crime_rate_per_1000: z.number().nullable().optional(),
  // TASK-CITYDATA: SSDS 追加8指標
  doctors_per_100k: z.number().nullable().optional(),
  ssds_hospital_count: z.number().int().nullable().optional(),
  unemployment_rate_pct: z.number().nullable().optional(),
  tertiary_industry_pct: z.number().nullable().optional(),
  dwelling_area_sqm: z.number().nullable().optional(),
  day_night_pop_ratio: z.number().nullable().optional(),
  school_count: z.number().int().nullable().optional(),
  nursery_children: z.number().int().nullable().optional(),
});

export type MunicipalityStats = z.infer<typeof MunicipalityStatsSchema>;

export const CityDashboardResponseSchema = z.object({
  municipality_code: z.string(),
  municipality_name: z.string(),
  user_id: z.string(),
  total_speeches: z.number().int().nonnegative(),
  interest_counts: z.record(z.string(), z.number().int().nonnegative()),
  top_speeches: z.array(FeedItemSchema),
  fallback_used: z.string().nullable().optional(),
  fallback_name: z.string().nullable().optional(),
  stats: MunicipalityStatsSchema.nullable().optional(),
});

export type CityDashboardResponse = z.infer<typeof CityDashboardResponseSchema>;

/** 街ダッシュボードを取得 (関心軸別カウント + 上位議題)。 */
export async function fetchCityDashboard(
  userId: string,
  municipalityCode: string,
  limit = 10,
): Promise<CityDashboardResponse> {
  const params = new URLSearchParams({
    user_id: userId,
    limit: String(limit),
  });
  return fetchJson(
    `${API_BASE}/v1/cities/${encodeURIComponent(municipalityCode)}?${params.toString()}`,
    CityDashboardResponseSchema,
  );
}

// ============================================================================
// Population Trend (TASK-POPTREND) — 人口推移 (国勢調査実績 + XKT013 将来推計)
// ============================================================================

export const PopulationTrendPointSchema = z.object({
  year: z.number().int(),
  population: z.number().int(),
  source: z.enum(["census", "projection"]),
});
export type PopulationTrendPoint = z.infer<typeof PopulationTrendPointSchema>;

export const PopulationTrendResponseSchema = z.object({
  municipality_code: z.string(),
  series: z.array(PopulationTrendPointSchema).default([]),
  latest_actual_year: z.number().int().nullable().optional(),
  projection_start_year: z.number().int().nullable().optional(),
  source_note: z.string().default(""),
});
export type PopulationTrendResponse = z.infer<
  typeof PopulationTrendResponseSchema
>;

/** 1 自治体の人口推移 (実績 + 2025-2070 将来推計) を取得。 */
export async function fetchPopulationTrend(
  municipalityCode: string,
): Promise<PopulationTrendResponse> {
  return fetchJson(
    `${API_BASE}/v1/cities/${encodeURIComponent(municipalityCode)}/population-trend`,
    PopulationTrendResponseSchema,
  );
}

// ============================================================================
// Concierge (Plan E) — 街診断 Migration Concierge Agent
// ============================================================================

/** ToolCallLog: Concierge が呼んだ tool の履歴 (UI で折りたたみ表示)。 */
export const ToolCallLogSchema = z.object({
  name: z.string(),
  args: z.record(z.string(), z.unknown()).default({}),
  output_preview: z.string().default(""),
  duration_ms: z.number().int().nonnegative().default(0),
});

export type ToolCallLog = z.infer<typeof ToolCallLogSchema>;

/** MunicipalityCandidate: search_municipalities が返す候補 1 件 (UI card 用)。 */
export const MunicipalityCandidateSchema = z.object({
  municipality_code: z.string(),
  name: z.string(),
  prefecture: z.string(),
  match_score: z.number().min(0).max(100),
  population_total: z.number().int().nullable().optional(),
  youth_share_pct: z.number().nullable().optional(),
  used_apartment_median_price_man_yen: z.number().nullable().optional(),
  childcare_facility_count: z.number().int().nullable().optional(),
  // 医療は SSDS 信頼値に統一 (旧 medical_facility_count は退役)
  doctors_per_100k: z.number().nullable().optional(),
  ssds_hospital_count: z.number().int().nullable().optional(),
  unemployment_rate_pct: z.number().nullable().optional(),
  dwelling_area_sqm: z.number().nullable().optional(),
  population_change_pct: z.number().nullable().optional(),
  financial_capability_index: z.number().nullable().optional(),
  matched_interests: z.array(z.string()).default([]),
  summary_text: z.string().default(""),
});

export type MunicipalityCandidate = z.infer<typeof MunicipalityCandidateSchema>;

/** Concierge レスポンス (POST /v1/concierge の戻り値)。 */
export const ConciergeResponseSchema = z.object({
  reply: z.string(),
  tool_calls: z.array(ToolCallLogSchema).default([]),
  candidates: z.array(MunicipalityCandidateSchema).default([]),
  ethical_violations: z.array(z.string()).default([]),
});

export type ConciergeResponse = z.infer<typeof ConciergeResponseSchema>;

/** Concierge リクエスト (POST /v1/concierge の body)。 */
export type ConciergeRequest = {
  message: string;
  persona: {
    user_id: string;
    age_group: string;
    interests?: string[];
    municipality_codes?: string[];
    free_form_context?: string;
    // TASK-ONBOARDING: 前提整理 (optional・後方互換)
    priorities?: string[];
    household?: string;
    budget_man?: number | null;
    area_pref?: string[];
  };
};

/**
 * Concierge Agent に相談 (Plan E)。実 Gemini Flash 経由で 5-20 秒かかる。
 * 単発相談 UX: conversation memory なし、各 call は独立。
 */
export async function postConcierge(
  request: ConciergeRequest,
): Promise<ConciergeResponse> {
  const res = await fetch(`${API_BASE}/v1/concierge`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(request),
    cache: "no-store", // Concierge は毎回新規 LLM call
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  const data = await res.json();
  return ConciergeResponseSchema.parse(data);
}

// ============================================================================
// Concierge 会話履歴 (Plan L+LL) — GET /v1/concierge/history/{user_id}
// ============================================================================

export const ConciergeHistoryItemSchema = z.object({
  doc_id: z.string(),
  timestamp: z.string().nullable(),
  message: z.string(),
  short_summary: z.string().default(""),
  candidates_codes: z.array(z.string()).default([]),
  matched_interests: z.array(z.string()).default([]),
});

export type ConciergeHistoryItem = z.infer<typeof ConciergeHistoryItemSchema>;

export const ConciergeHistoryResponseSchema = z.object({
  user_id: z.string(),
  items: z.array(ConciergeHistoryItemSchema),
  total: z.number().int().nonnegative(),
});

export type ConciergeHistoryResponse = z.infer<
  typeof ConciergeHistoryResponseSchema
>;

/**
 * Concierge 会話履歴を取得 (Plan L+LL)。
 * x-user-id header で簡易認可 (path user_id と一致しないと 403)。
 */
export async function fetchConciergeHistory(
  userId: string,
  limit = 20,
): Promise<ConciergeHistoryResponse> {
  const res = await fetch(
    `${API_BASE}/v1/concierge/history/${encodeURIComponent(userId)}?limit=${limit}`,
    {
      headers: {
        Accept: "application/json",
        "x-user-id": userId,
      },
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  const data = await res.json();
  return ConciergeHistoryResponseSchema.parse(data);
}

// ============================================================================
// Heatmap (Plan X) — GET /v1/heatmap
// ============================================================================

export const HeatmapAdviceSchema = z.object({
  metric_column: z.string(),
  metric_label_ja: z.string(),
  direction: z.enum(["lower_is_better", "higher_is_better"]),
  unit: z.string().default(""),
  reasoning: z.string(),
  persona_summary: z.string(),
  source: z.enum(["llm", "rule_based"]),
});

export type HeatmapAdvice = z.infer<typeof HeatmapAdviceSchema>;

export const PrefectureValueSchema = z.object({
  prefecture_code: z.string(),
  prefecture_name: z.string(),
  metric_median: z.number(),
  muni_count: z.number().int(),
  rank: z.number().int(),
});

export type PrefectureValue = z.infer<typeof PrefectureValueSchema>;

export const PrefectureTopMuniSchema = z.object({
  prefecture_code: z.string(),
  municipalities: z.array(
    z.object({
      municipality_code: z.string(),
      municipality_name: z.string(),
      metric_value: z.number(),
    }),
  ),
});

export type PrefectureTopMuni = z.infer<typeof PrefectureTopMuniSchema>;

export const HeatmapResponseSchema = z.object({
  advice: HeatmapAdviceSchema,
  prefecture_values: z.array(PrefectureValueSchema),
  top_municipalities: z.array(PrefectureTopMuniSchema),
});

export type HeatmapResponse = z.infer<typeof HeatmapResponseSchema>;

/**
 * 全国ヒートマップを取得 (Plan X)。
 * HeatmapAdvisor がペルソナを踏まえて metric を選定し、47 都道府県の中央値 + 県別 TOP3 を返す。
 */
export async function fetchHeatmap(args: {
  userId?: string;
  ageGroup?: string;
  interests?: string[];
  focusInterest: string;
  freeFormContext?: string;
}): Promise<HeatmapResponse> {
  const params = new URLSearchParams({
    user_id: args.userId ?? "anon",
    age_group: args.ageGroup ?? "25-29",
    interests: (args.interests ?? []).join(","),
    focus_interest: args.focusInterest,
    free_form_context: args.freeFormContext ?? "",
  });
  const res = await fetch(`${API_BASE}/v1/heatmap?${params.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  const data = await res.json();
  return HeatmapResponseSchema.parse(data);
}

// ============================================================================
// Timeline (Plan N) — GET /v1/timeline
// ============================================================================

export const TimelineEventSchema = z.object({
  event_date: z.string(), // ISO date
  municipality_code: z.string(),
  municipality_name: z.string().default(""),
  headline: z.string(),
  detail: z.string(),
  source_speech_id: z.string(),
  importance: z.number().int().default(50),
});

export type TimelineEvent = z.infer<typeof TimelineEventSchema>;

export const TimelineNarrativeSchema = z.object({
  theme_label: z.string(),
  period_start: z.string(),
  period_end: z.string(),
  overall_summary: z.string().default(""),
  events: z.array(TimelineEventSchema).default([]),
  source: z.enum(["llm", "rule_based"]),
});

export type TimelineNarrative = z.infer<typeof TimelineNarrativeSchema>;

export const TimelineResponseSchema = z.object({
  narrative: TimelineNarrativeSchema,
  candidate_count: z.number().int().nonnegative(),
});

export type TimelineResponse = z.infer<typeof TimelineResponseSchema>;

/**
 * 議論タイムラインを取得 (Plan N)。
 * TimelineAgent が theme_interest + 自治体 + 期間で物語化したナラティブ + イベント 5-10 件。
 */
export async function fetchTimeline(args: {
  themeInterest: string;
  userId?: string;
  municipalityCode?: string | null;
  days?: number;
}): Promise<TimelineResponse> {
  const params = new URLSearchParams({
    theme_interest: args.themeInterest,
    user_id: args.userId ?? "anon",
    days: String(args.days ?? 90),
  });
  if (args.municipalityCode) {
    params.set("municipality_code", args.municipalityCode);
  }
  const res = await fetch(`${API_BASE}/v1/timeline?${params.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  const data = await res.json();
  return TimelineResponseSchema.parse(data);
}

// ============================================================================
// Forecast (Plan Z) — GET /v1/forecast
// ============================================================================

export const MonthCountSchema = z.object({
  year_month: z.string(),
  speech_count: z.number().nonnegative(),
});

export const ForecastPointSchema = z.object({
  year_month: z.string(),
  speech_count: z.number().nonnegative(),
  is_forecast: z.boolean(),
});

export type ForecastPoint = z.infer<typeof ForecastPointSchema>;
export type MonthCount = z.infer<typeof MonthCountSchema>;

export const ForecastSeriesSchema = z.object({
  historical: z.array(MonthCountSchema),
  forecast: z.array(ForecastPointSchema),
  trend_classification: z.enum([
    "surge",
    "increasing",
    "flat",
    "decreasing",
    "crash",
  ]),
  slope: z.number(),
  slope_std_error: z.number().nonnegative().default(0),
  confidence: z.enum(["high", "medium", "low"]),
  months_in_history: z.number().int().nonnegative(),
});

export type ForecastSeries = z.infer<typeof ForecastSeriesSchema>;

export const ForecastNarrativeSchema = z.object({
  headline: z.string(),
  reasoning: z.string(),
  source: z.enum(["llm", "rule_based"]),
});

export type ForecastNarrative = z.infer<typeof ForecastNarrativeSchema>;

export const ForecastResponseSchema = z.object({
  series: ForecastSeriesSchema,
  narrative: ForecastNarrativeSchema,
});

export type ForecastResponse = z.infer<typeof ForecastResponseSchema>;

/**
 * 議題件数トレンド予測 (Plan Z)。
 * Engine が線形回帰で 3 か月予測、Narrator が介入的説明。
 */
export async function fetchForecast(args: {
  themeInterest: string;
  userId?: string;
  ageGroup?: string;
  municipalityCode?: string | null;
  historyMonths?: number;
}): Promise<ForecastResponse> {
  const params = new URLSearchParams({
    theme_interest: args.themeInterest,
    user_id: args.userId ?? "anon",
    age_group: args.ageGroup ?? "25-29",
    history_months: String(args.historyMonths ?? 12),
  });
  if (args.municipalityCode) {
    params.set("municipality_code", args.municipalityCode);
  }
  const res = await fetch(`${API_BASE}/v1/forecast?${params.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  const data = await res.json();
  return ForecastResponseSchema.parse(data);
}

// ============================================================================
// Scraper Health (Plan F) — GET /v1/scraper-health
// ============================================================================

export const ScraperFailureLogSchema = z.object({
  failure_id: z.string(),
  timestamp: z.string(),
  scraper: z.string(),
  tenant_id: z.string().nullable(),
  municipality_code: z.string().nullable(),
  url: z.string().nullable(),
  error_type: z.string(),
  stack_trace: z.string(),
  html_snippet: z.string().nullable().optional(),
  html_signature: z.string().default(""),
  duration_ms: z.number().int().nonnegative().nullable().optional(),
});

export type ScraperFailureLog = z.infer<typeof ScraperFailureLogSchema>;

export const DiagnosticResultSchema = z.object({
  error_category: z.enum([
    "ssl_failure",
    "auth_403",
    "html_structure_change",
    "robots_disallow",
    "network_timeout",
    "rate_limit",
    "parser_logic",
    "unknown",
  ]),
  root_cause_text: z.string(),
  confidence: z.enum(["high", "medium", "low"]),
  severity: z.enum(["critical", "high", "medium", "low"]),
  source: z.enum(["llm", "rule_based"]),
});

export type DiagnosticResult = z.infer<typeof DiagnosticResultSchema>;

export const RepairProposalSchema = z.object({
  proposed_action: z.enum([
    "user_agent_change",
    "retry_strategy_adjust",
    "parser_path_update",
    "drop_tenant",
    "robots_check",
    "manual_review",
  ]),
  rationale: z.string(),
  code_hint: z.string(),
  risk_assessment: z.enum(["safe", "moderate", "risky"]),
  requires_human_review: z.boolean(),
  source: z.enum(["llm", "rule_based"]),
});

export type RepairProposal = z.infer<typeof RepairProposalSchema>;

export const ScraperHealthEntrySchema = z.object({
  failure: ScraperFailureLogSchema,
  diagnostic: DiagnosticResultSchema,
  proposal: RepairProposalSchema,
});

export type ScraperHealthEntry = z.infer<typeof ScraperHealthEntrySchema>;

export const ScraperHealthResponseSchema = z.object({
  period_start: z.string(),
  period_end: z.string(),
  total_failures: z.number().int().nonnegative(),
  by_category: z.record(z.string(), z.number().int().nonnegative()),
  by_scraper: z.record(z.string(), z.number().int().nonnegative()),
  entries: z.array(ScraperHealthEntrySchema),
  drop_candidates: z.array(z.string()),
  disclaimer: z.string(),
});

export type ScraperHealthResponse = z.infer<typeof ScraperHealthResponseSchema>;

/**
 * Scraper Health (Plan F): 失敗ログ + Agent 診断 + 修正提案を取得。
 * `use_sample=true` で sample seed を強制使用 (demo 用)。
 */
export async function fetchScraperHealth(args: {
  days?: number;
  limit?: number;
  useSample?: boolean;
} = {}): Promise<ScraperHealthResponse> {
  const params = new URLSearchParams({
    days: String(args.days ?? 7),
    limit: String(args.limit ?? 50),
    use_sample: args.useSample ? "true" : "false",
  });
  const res = await fetch(`${API_BASE}/v1/scraper-health?${params.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  const data = await res.json();
  return ScraperHealthResponseSchema.parse(data);
}

// ============================================================================
// Reasoning Transparency (Plan PP) — GET /v1/reasoning/explain
// ============================================================================

export const AgentNameEnum = z.enum([
  "concierge",
  "translator",
  "critic",
  "heatmap_advisor",
  "timeline",
  "forecast",
  "scraper_doctor",
]);

export type AgentName = z.infer<typeof AgentNameEnum>;

export const ReasoningExplanationSchema = z.object({
  plain_summary: z.string(),
  influencing_factors: z.array(z.string()),
  counterfactuals: z.array(z.string()),
  caveats: z.array(z.string()),
  confidence: z.enum(["high", "medium", "low"]),
  source: z.enum(["llm", "rule_based"]),
});

export type ReasoningExplanation = z.infer<typeof ReasoningExplanationSchema>;

/**
 * Reasoning Transparency (Plan PP): 対象 Agent の reasoning を第三者視点で再構成。
 * on-demand call (ユーザーがボタンクリック時のみ)、cache なし。
 */
export async function fetchReasoningExplanation(args: {
  agentName: AgentName;
  rawReasoning: string;
  agentOutputSummary: string;
  personaContext?: string;
}): Promise<ReasoningExplanation> {
  const params = new URLSearchParams({
    agent_name: args.agentName,
    raw_reasoning: args.rawReasoning,
    agent_output_summary: args.agentOutputSummary,
  });
  if (args.personaContext) {
    params.set("persona_context", args.personaContext);
  }
  const res = await fetch(`${API_BASE}/v1/reasoning/explain?${params.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  const data = await res.json();
  return ReasoningExplanationSchema.parse(data);
}

// ============================================================================
// Cost Anomaly Hunter (Plan CC) — GET /v1/cost-health
// ============================================================================

export const CostAnomalySchema = z.object({
  date: z.string(),
  service: z.string(),
  cost_jpy: z.number().nonnegative(),
  baseline_avg_7d: z.number().nonnegative(),
  baseline_stddev_7d: z.number().nonnegative(),
  z_score: z.number(),
  spike_ratio: z.number(),
  anomaly_type: z.enum(["spike", "drift_up", "drift_down", "normal"]),
  severity: z.enum(["critical", "high", "medium", "low"]),
});

export type CostAnomaly = z.infer<typeof CostAnomalySchema>;

export const CostRootCauseProposalSchema = z.object({
  root_cause_hypothesis: z.string(),
  proposed_action: z.enum([
    "scale_down",
    "optimize_query",
    "investigate_logs",
    "rate_limit",
    "manual_review",
  ]),
  rationale: z.string(),
  monthly_savings_estimate_jpy: z.number().int().nonnegative().max(100_000),
  risk_assessment: z.enum(["safe", "moderate", "risky"]),
  requires_human_review: z.boolean(),
  source: z.enum(["llm", "rule_based"]),
});

export type CostRootCauseProposal = z.infer<typeof CostRootCauseProposalSchema>;

export const CostHealthEntrySchema = z.object({
  anomaly: CostAnomalySchema,
  proposal: CostRootCauseProposalSchema,
});

export type CostHealthEntry = z.infer<typeof CostHealthEntrySchema>;

export const CostHealthResponseSchema = z.object({
  period_start: z.string(),
  period_end: z.string(),
  total_anomalies: z.number().int().nonnegative(),
  by_service: z.record(z.string(), z.number().int().nonnegative()),
  by_severity: z.record(z.string(), z.number().int().nonnegative()),
  estimated_total_savings_jpy: z.number().int().nonnegative(),
  entries: z.array(CostHealthEntrySchema),
  cross_service_pattern: z.string().nullable(),
  disclaimer: z.string(),
});

export type CostHealthResponse = z.infer<typeof CostHealthResponseSchema>;

/**
 * Cost Anomaly Hunter (Plan CC): GCP cost data から異常検知 + 削減提案。
 * 自動 cost 削減 action は実装されません (人間レビュー前提)。
 */
export async function fetchCostHealth(
  args: { days?: number; limitEntries?: number } = {},
): Promise<CostHealthResponse> {
  const params = new URLSearchParams({
    days: String(args.days ?? 30),
    limit_entries: String(args.limitEntries ?? 20),
  });
  const res = await fetch(`${API_BASE}/v1/cost-health?${params.toString()}`, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 300)}`);
  }
  const data = await res.json();
  return CostHealthResponseSchema.parse(data);
}

// ============================================================================
// Ops Crew (運用SREクルー、DevOps × AI Agent) — GET /v1/ops/health
// agents/ops_crew/schema.py の Pydantic (OpsAssessment / OpsRunLog) と一致させる。
// Watcher と同一パターン(計画→並列専門家→統合→批判→人間ゲート)を自分たちの運用に適用。
// 認可: OPS_ADMIN_TOKEN が server に設定されていれば x-admin-token 必須 (未設定なら dev 許可)。
// ============================================================================

export const OpsDomainEnum = z.enum(["scraper_health", "cost", "data_freshness"]);
export type OpsDomain = z.infer<typeof OpsDomainEnum>;

export const OpsVerdictSchema = z.object({
  headline: z.string().default(""),
  reasoning: z.string().default(""),
  top_priority_domain: OpsDomainEnum.nullable().default(null),
  confidence: z.enum(["high", "medium", "low"]).default("medium"),
  requires_human_review: z.boolean().default(true),
});

export type OpsVerdict = z.infer<typeof OpsVerdictSchema>;

export const OpsFindingSchema = z.object({
  domain: OpsDomainEnum,
  headline: z.string().default(""),
  key_points: z.array(z.string()).default([]),
  severity: z.string().default("none"),
  confidence: z.enum(["high", "medium", "low"]).default("medium"),
  source_refs: z.array(z.string()).default([]),
});

export type OpsFinding = z.infer<typeof OpsFindingSchema>;

export const OpsRemediationProposalSchema = z.object({
  domain: OpsDomainEnum,
  action: z.string(),
  rationale: z.string().default(""),
  risk_assessment: z.enum(["safe", "moderate", "risky"]).default("moderate"),
  requires_human_review: z.boolean().default(true),
  source: z.enum(["llm", "rule_based"]).default("rule_based"),
});

export type OpsRemediationProposal = z.infer<typeof OpsRemediationProposalSchema>;

export const OpsAssessmentSchema = z.object({
  verdict: OpsVerdictSchema,
  findings: z.array(OpsFindingSchema).default([]),
  proposals: z.array(OpsRemediationProposalSchema).default([]),
  critique_note: z.string().default(""),
  investigation_plan: z.array(z.string()).default([]),
});

export type OpsAssessment = z.infer<typeof OpsAssessmentSchema>;

export const OpsToolCallSchema = z.object({
  tool: z.string(),
  args: z.record(z.string(), z.unknown()).default({}),
});

export type OpsToolCall = z.infer<typeof OpsToolCallSchema>;

export const OpsRunLogSchema = z.object({
  run_id: z.string().default(""),
  targets_checked: z.array(z.string()).default([]),
  tool_calls: z.array(OpsToolCallSchema).default([]),
  n_findings: z.number().int().nonnegative().default(0),
  token_cost: z.number().int().nullable().optional(),
  status: z.enum(["ok", "empty", "error"]).default("ok"),
  note: z.string().default(""),
});

export type OpsRunLog = z.infer<typeof OpsRunLogSchema>;

export const OpsHealthResponseSchema = z.object({
  assessment: OpsAssessmentSchema.nullable().default(null),
  run_log: OpsRunLogSchema,
  freshness_hours: z.number().nullable().default(null),
});

export type OpsHealthResponse = z.infer<typeof OpsHealthResponseSchema>;

/**
 * Ops Crew (DevOps × AI Agent): scraper_health/cost/data_freshness を統括する
 * 運用SREクルーを実行し、統合アセスメント + 自律実行トレースを取得する。
 * 自動実行は一切されない (人間レビュー前提、requires_human_review は常に true)。
 * OPS_ADMIN_TOKEN が server 側で設定されている場合は 403 (x-admin-token 不一致/未設定) が返る。
 */
export async function fetchOpsHealth(
  opts: { days?: number; useSample?: boolean } = {},
): Promise<OpsHealthResponse> {
  const params = new URLSearchParams({
    days: String(opts.days ?? 7),
    use_sample: String(opts.useSample ?? true),
  });
  return fetchJson(
    `${API_BASE}/v1/ops/health?${params.toString()}`,
    OpsHealthResponseSchema,
    { cache: "no-store" },
  );
}

// ============================================================================
// Watcher (マイ街エージェント=街選びアナリスト / TASK-WATCHER Slice 3.5)
// agents/watcher/schema.py の Pydantic (TownAnalysis / AgentRunLog) と一致させる。
// 認可は x-user-id header (path user_id と一致必須、demo)。
// ============================================================================

/** 1 つの街(住む街=基準 or 候補)の多軸評価 */
export const TownAssessmentSchema = z.object({
  municipality_code: z.string(),
  role: z.enum(["home", "candidate"]),
  headline: z.string(),
  strengths: z.array(z.string()).default([]),
  concerns: z.array(z.string()).default([]),
  population_outlook: z.string().default(""),
  recent_signal: z.string().default(""),
  source_speech_ids: z.array(z.string()).default([]),
  fit_score: z.number().int().min(0).max(100).default(50),
  confidence: z.enum(["high", "medium", "low"]).default("medium"),
});

export type TownAssessment = z.infer<typeof TownAssessmentSchema>;

/** エージェントの"生きた結論" = 差別化の核 */
export const WatchVerdictSchema = z.object({
  headline: z.string(),
  reasoning: z.string().default(""),
  recommended_code: z.string().nullable().default(null),
  confidence: z.enum(["high", "medium", "low"]).default("medium"),
  contains_political_judgment: z.boolean().default(false),
});

export type WatchVerdict = z.infer<typeof WatchVerdictSchema>;

// P3: 専門エージェントの所見 (A5)
export const SpecialistFindingSchema = z.object({
  domain: z.string(),
  headline: z.string().default(""),
  key_points: z.array(z.string()).default([]),
  confidence: z.enum(["high", "medium", "low"]).default("medium"),
  source_speech_ids: z.array(z.string()).default([]),
});
export type SpecialistFinding = z.infer<typeof SpecialistFindingSchema>;

export const TownAnalysisSchema = z.object({
  verdict: WatchVerdictSchema,
  town_assessments: z.array(TownAssessmentSchema).default([]),
  watch_points: z.array(z.string()).default([]),
  open_questions: z.array(z.string()).default([]),
  // P2: 検証と反論の透明性 (A1 / A9)
  critique_note: z.string().default(""),
  devils_advocate: z.string().default(""),
  // P3: 専門家の所見 (A5)
  specialist_findings: z.array(SpecialistFindingSchema).default([]),
  // P4: 前回分析からの変化 (A3)
  changes_since_last: z.array(z.string()).default([]),
  // Lv3: Coordinator が立てた調査計画 (自律性の可視化)
  investigation_plan: z.array(z.string()).default([]),
});

export type TownAnalysis = z.infer<typeof TownAnalysisSchema>;

/** エージェントが自分で選んで呼んだツール 1 回 = ①自律性の証跡 */
export const WatcherToolCallSchema = z.object({
  tool: z.string(),
  args: z.record(z.string(), z.unknown()).default({}),
});

export type WatcherToolCall = z.infer<typeof WatcherToolCallSchema>;

export const WatcherRunLogSchema = z.object({
  run_id: z.string().default(""),
  user_id: z.string(),
  towns_checked: z.array(z.string()).default([]),
  tool_calls: z.array(WatcherToolCallSchema).default([]),
  n_discoveries: z.number().int().nonnegative().default(0),
  token_cost: z.number().int().nullable().optional(),
  status: z.enum(["ok", "empty", "error", "max_iterations"]).default("ok"),
  note: z.string().default(""),
});

export type WatcherRunLog = z.infer<typeof WatcherRunLogSchema>;

export const WatcherAnalysisResponseSchema = z.object({
  user_id: z.string(),
  analysis: TownAnalysisSchema.nullable().default(null),
  latest_run: WatcherRunLogSchema.nullable().default(null),
});

export type WatcherAnalysisResponse = z.infer<
  typeof WatcherAnalysisResponseSchema
>;

export const WatchlistSchema = z.object({
  user_id: z.string(),
  age_group: z.string(),
  interests: z.array(z.string()).default([]),
  home_municipality_code: z.string(),
  watched_codes: z.array(z.string()).default([]),
});

export type Watchlist = z.infer<typeof WatchlistSchema>;

/** PUT / POST run の body (user_id は path から取るので含めない)。 */
export type WatchlistBody = {
  age_group: string;
  interests: string[];
  home_municipality_code: string;
  watched_codes: string[];
  // TASK-ONBOARDING: 前提整理 (全て optional・後方互換)
  priorities?: string[];
  household?: string;
  budget_man?: number | null;
  free_form_context?: string;
};

export const WatcherRunResponseSchema = z.object({
  run_log: WatcherRunLogSchema,
  analysis: TownAnalysisSchema.nullable().default(null),
});

export type WatcherRunResponse = z.infer<typeof WatcherRunResponseSchema>;

// ----- 街比較レーダー (TASK-FISCAL) — 財政5指標 raw + 全国percentile score -----
export const CompareStatMetricSchema = z.object({
  key: z.string(),
  label: z.string(),
  direction: z.enum(["higher", "lower"]),
  national_median: z.number().nullable().optional(),
});
export type CompareStatMetric = z.infer<typeof CompareStatMetricSchema>;

export const CompareStatValueSchema = z.object({
  raw: z.number().nullable(),
  score: z.number().nullable(),
  rank: z.number().int().nullable().optional(),
  total: z.number().int().nullable().optional(),
});

export const CompareStatTownSchema = z.object({
  municipality_code: z.string(),
  municipality_name: z.string(),
  values: z.record(z.string(), CompareStatValueSchema),
});
export type CompareStatTown = z.infer<typeof CompareStatTownSchema>;

export const CompareStatsResponseSchema = z.object({
  metrics: z.array(CompareStatMetricSchema).default([]),
  towns: z.array(CompareStatTownSchema).default([]),
});
export type CompareStatsResponse = z.infer<typeof CompareStatsResponseSchema>;

/** 街比較レーダー用の5指標(財政力/所得/持ち家/財政健全度/治安)を取得。 */
export async function fetchCompareStats(
  codes: string[],
): Promise<CompareStatsResponse> {
  const qs = encodeURIComponent(codes.join(","));
  return fetchJson(
    `${API_BASE}/v1/cities/compare-stats?codes=${qs}`,
    CompareStatsResponseSchema,
  );
}

function watcherHeaders(userId: string): HeadersInit {
  return { Accept: "application/json", "x-user-id": userId };
}

/** エージェントの街選び分析 (比較+生きた結論) + 最新実行ログ (自律証跡) を取得。 */
export async function fetchWatcherAnalysis(
  userId: string,
): Promise<WatcherAnalysisResponse> {
  return fetchJson(
    `${API_BASE}/v1/watcher/${encodeURIComponent(userId)}/analysis`,
    WatcherAnalysisResponseSchema,
    { headers: watcherHeaders(userId), cache: "no-store" },
  );
}

/** 保存済ウォッチ街を取得 (未設定なら null)。 */
export async function fetchWatchlist(userId: string): Promise<Watchlist | null> {
  const res = await fetch(
    `${API_BASE}/v1/watcher/${encodeURIComponent(userId)}/watchlist`,
    { headers: watcherHeaders(userId), cache: "no-store" },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  return data == null ? null : WatchlistSchema.parse(data);
}

/** ウォッチ街を保存。 */
export async function putWatchlist(
  userId: string,
  body: WatchlistBody,
): Promise<Watchlist> {
  return fetchJson(
    `${API_BASE}/v1/watcher/${encodeURIComponent(userId)}/watchlist`,
    WatchlistSchema,
    {
      method: "PUT",
      headers: { ...watcherHeaders(userId), "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    },
  );
}

const RUN_POLL_INTERVAL_MS = 4000;
const RUN_POLL_TIMEOUT_MS = 240000; // 4 分 (分析は通常 2-3 分)

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * エージェントを **非同期** に自律実行する (アドバイザーが裏で調べてレポートを出す体験)。
 *
 * POST /run は即時 202 を返し、重い分析はサーバのバックグラウンドで走る。
 * ここでは GET /analysis を **新しい run_id が現れるまでポーリング** して完了を検知する
 * (同期 2-3 分待ちの解消)。返却 run_log.tool_calls がライブ自律の証跡。
 * body 省略時は保存済 watchlist を使用。
 */
export async function runWatcher(
  userId: string,
  body?: WatchlistBody,
): Promise<WatcherRunResponse> {
  // 直前の run_id を控える (完了=新しい run_id の出現で検知)
  const before = await fetchWatcherAnalysis(userId).catch(() => null);
  const prevRunId = before?.latest_run?.run_id ?? null;

  // 非同期実行を開始 (202 Accepted)。本体はサーバの背景タスク。
  const res = await fetch(
    `${API_BASE}/v1/watcher/${encodeURIComponent(userId)}/run`,
    {
      method: "POST",
      headers: { ...watcherHeaders(userId), "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
    },
  );
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, `HTTP ${res.status}: ${text.slice(0, 200)}`);
  }

  // 新しい分析(run_id 変化)が現れるまでポーリング
  const deadline = Date.now() + RUN_POLL_TIMEOUT_MS;
  while (Date.now() < deadline) {
    await sleep(RUN_POLL_INTERVAL_MS);
    const cur = await fetchWatcherAnalysis(userId).catch(() => null);
    const runId = cur?.latest_run?.run_id ?? null;
    if (cur?.latest_run && runId !== prevRunId) {
      return { run_log: cur.latest_run, analysis: cur.analysis };
    }
  }
  throw new ApiError(
    504,
    "分析がタイムアウトしました。少し時間をおいて再度お試しください。",
  );
}

// ----- 前提整理: 自由記述抽出 (TASK-ONBOARDING / F) -----
export const ExtractedPreferencesSchema = z.object({
  interests: z.array(z.string()).default([]),
  priorities: z.array(z.string()).default([]),
  household: z.string().default(""),
  budget_man: z.number().nullable().default(null),
  background_summary: z.string().default(""),
});
export type ExtractedPreferences = z.infer<typeof ExtractedPreferencesSchema>;

const ExtractResponseSchema = z.object({
  extracted: ExtractedPreferencesSchema,
});

/** 自由記述から移住の前提を抽出 (フォーム自動プリフィル用)。失敗時は空。 */
export async function extractPreferences(
  text: string,
): Promise<ExtractedPreferences> {
  const res = await fetchJson(
    `${API_BASE}/v1/preferences/extract`,
    ExtractResponseSchema,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      cache: "no-store",
    },
  );
  return res.extracted;
}

// ----- 移住アクションプラン (TASK-ACTIONPLAN) -----
export const OfficialLinkSchema = z.object({
  label: z.string(),
  url: z.string(),
});
export type OfficialLink = z.infer<typeof OfficialLinkSchema>;

// TASK-SUPPORT: 移住支援金マッチング
export const NationalSupportSchema = z.object({
  eligibility: z.enum(["likely", "conditional", "unlikely"]).default("unlikely"),
  amount_man: z.number().int().nullable().optional(),
  child_addition: z.boolean().default(false),
  requirements: z.string().default(""),
  official_url: z.string().default(""),
  note: z.string().default(""),
});
export const LocalSupportSchema = z.object({
  name: z.string(),
  summary: z.string().default(""),
  official_url: z.string().default(""),
  source_url: z.string().default(""),
});
export const RelocationSupportSchema = z.object({
  national: NationalSupportSchema.nullable().optional(),
  local: z.array(LocalSupportSchema).default([]),
});
export type RelocationSupport = z.infer<typeof RelocationSupportSchema>;

export const ActionPlanSchema = z.object({
  mode: z.enum(["relocate", "stay"]).default("relocate"),
  recommended_code: z.string(),
  recommended_name: z.string(),
  role: z.enum(["home", "candidate"]).default("candidate"),
  decision_summary: z.string().default(""),
  reasons: z.array(z.string()).default([]),
  open_questions: z.array(z.string()).default([]),
  visit_checklist: z.array(z.string()).default([]),
  official_links: z.array(OfficialLinkSchema).default([]),
  support: RelocationSupportSchema.nullable().optional(),
  run_id: z.string().default(""),
  generated_at: z.string().default(""),
});
export type ActionPlan = z.infer<typeof ActionPlanSchema>;

export const ActionPlanResponseSchema = z.object({
  user_id: z.string(),
  plan: ActionPlanSchema.nullable().default(null),
});
export type ActionPlanResponse = z.infer<typeof ActionPlanResponseSchema>;

/** 移住アクションプラン (最新分析の出口) を取得。分析未生成なら plan=null。 */
export async function fetchActionPlan(
  userId: string,
): Promise<ActionPlanResponse> {
  return fetchJson(
    `${API_BASE}/v1/watcher/${encodeURIComponent(userId)}/plan`,
    ActionPlanResponseSchema,
    { headers: watcherHeaders(userId), cache: "no-store" },
  );
}

/**
 * アクションプランを家族共有用の平文に整形 (純関数、テスト対象)。
 * checked はチェック済み項目を [x] にする (持ち帰り用)。
 */
export function formatActionPlanForCopy(
  plan: ActionPlan,
  checked?: { questions?: Set<string>; visit?: Set<string> },
): string {
  const lines: string[] = [];
  const mark = (text: string, set?: Set<string>) =>
    `${set?.has(text) ? "[x]" : "[ ]"} ${text}`;
  lines.push(`■ 移住アクションプラン: ${plan.recommended_name}`);
  if (plan.decision_summary) lines.push(plan.decision_summary);
  if (plan.reasons.length) {
    lines.push("", "【決め手】");
    for (const r of plan.reasons) lines.push(`・${r}`);
  }
  if (plan.open_questions.length) {
    lines.push("", "【残る確認事項】");
    for (const q of plan.open_questions) lines.push(mark(q, checked?.questions));
  }
  if (plan.visit_checklist.length) {
    lines.push("", "【現地で確かめる】");
    for (const v of plan.visit_checklist) lines.push(mark(v, checked?.visit));
  }
  if (plan.official_links.length) {
    lines.push("", "【相談窓口】");
    for (const l of plan.official_links) lines.push(`・${l.label}: ${l.url}`);
  }
  lines.push("", "※ AIが中立な検討材料として作成。最終判断はご自身の価値観で。");
  return lines.join("\n");
}
