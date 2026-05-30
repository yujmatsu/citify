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
