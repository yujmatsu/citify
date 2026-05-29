/** Citify BFF (FastAPI) クライアント — TypeScript + zod 型安全。
 *
 * 環境変数:
 *   NEXT_PUBLIC_API_BASE (例: https://citify-api-xxxxx.a.run.app, default: http://localhost:8080)
 */

import { z } from "zod";

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
  const res = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
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
    headers: { "Content-Type": "application/json" },
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
  medical_facility_count: z.number().int().nullable().optional(),
  population_change_2025_2050_pct: z.number().nullable().optional(),
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
