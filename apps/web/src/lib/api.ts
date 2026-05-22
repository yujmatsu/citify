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
  const res = await fetch(url, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.headers ?? {}),
    },
    // App Router (Server Components) の fetch cache を default 抑制
    cache: init?.cache ?? "no-store",
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
