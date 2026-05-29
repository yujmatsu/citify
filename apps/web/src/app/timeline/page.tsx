"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  ApiError,
  fetchTimeline,
  type TimelineEvent,
  type TimelineResponse,
} from "@/lib/api";
import { loadPersona, type Persona } from "@/lib/persona";
import { cn } from "@/lib/utils";

const INTERESTS = [
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

const DAYS_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 30, label: "30 日" },
  { value: 90, label: "90 日" },
  { value: 365, label: "1 年" },
];

export default function TimelinePage() {
  const router = useRouter();
  const [persona, setPersona] = useState<Persona | null>(null);
  const [themeInterest, setThemeInterest] = useState<string>("住居");
  const [municipalityCode, setMunicipalityCode] = useState<string>("");
  const [days, setDays] = useState<number>(90);
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const p = loadPersona();
    if (!p) {
      router.replace("/onboarding");
      return;
    }
    setPersona(p);
    if (p.interests.length > 0) setThemeInterest(p.interests[0]);
    if (p.municipality_codes.length > 0) {
      setMunicipalityCode(p.municipality_codes[0]);
    }
  }, [router]);

  useEffect(() => {
    if (!persona) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTimeline({
      themeInterest,
      userId: persona.user_id,
      municipalityCode: municipalityCode || null,
      days,
    })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) {
          const msg =
            err instanceof ApiError
              ? `API エラー (${err.status}): ${err.message}`
              : err instanceof Error
                ? err.message
                : "取得に失敗しました";
          setError(msg);
          setData(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [persona, themeInterest, municipalityCode, days]);

  if (persona === null) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">読み込み中...</p>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col px-6 pb-6 pt-6 sm:px-10">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col space-y-6">
        {/* Top nav */}
        <div className="flex items-center justify-between">
          <Link
            href="/feed"
            className="text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← フィードに戻る
          </Link>
          <span className="text-xs text-zinc-500">
            議論タイムライン (Plan N)
          </span>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            🕰 議論タイムライン
          </h1>
          <p className="text-sm text-zinc-500">
            関心軸 + 自治体 + 期間で議論の流れを Agent
            が物語化します。イベントクリックで議題詳細へ。
          </p>
        </header>

        {/* Selectors */}
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">
              関心軸:
            </span>
            {INTERESTS.map((i) => (
              <button
                key={i}
                type="button"
                onClick={() => setThemeInterest(i)}
                disabled={loading}
                className={cn(
                  "rounded-lg border px-3 py-1 text-xs transition disabled:opacity-50",
                  themeInterest === i
                    ? "border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                    : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800",
                )}
              >
                {i}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-zinc-600 dark:text-zinc-400">
                自治体:
              </span>
              <input
                type="text"
                placeholder="5 桁コード (空 = 全国)"
                value={municipalityCode}
                onChange={(e) => setMunicipalityCode(e.target.value)}
                className="w-32 rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-zinc-600 dark:text-zinc-400">
                期間:
              </span>
              {DAYS_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setDays(opt.value)}
                  disabled={loading}
                  className={cn(
                    "rounded px-2 py-1 text-xs transition disabled:opacity-50",
                    days === opt.value
                      ? "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                      : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300",
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Narrative banner */}
        {data?.narrative && (
          <NarrativeBanner
            narrative={data.narrative}
            candidateCount={data.candidate_count}
          />
        )}

        {/* Status */}
        {loading && (
          <div className="rounded-xl border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            ⏳ Agent が候補議題を集約し、議論変遷を物語化中...
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200">
            ❌ {error}
          </div>
        )}

        {/* Timeline */}
        {!loading && !error && data && data.narrative.events.length > 0 && (
          <TimelineList events={data.narrative.events} />
        )}
        {!loading && !error && data && data.narrative.events.length === 0 && (
          <div className="rounded-xl border border-zinc-200 bg-zinc-50 p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            📭
            この条件ではイベントが見つかりませんでした。期間を伸ばすか別の関心軸をお試しください。
          </div>
        )}
      </div>
    </main>
  );
}

// ============================================================================
// Narrative banner (Agent reasoning + source 区別)
// ============================================================================

function NarrativeBanner({
  narrative,
  candidateCount,
}: {
  narrative: TimelineResponse["narrative"];
  candidateCount: number;
}): React.ReactElement {
  const isLlm = narrative.source === "llm";
  return (
    <div
      className={cn(
        "rounded-2xl border p-4 text-sm space-y-2",
        isLlm
          ? "border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950"
          : "border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-semibold text-zinc-900 dark:text-zinc-100">
          📖 {narrative.theme_label} (期間: {narrative.period_start} 〜{" "}
          {narrative.period_end})
        </div>
        <div className="text-[10px] font-mono text-zinc-500">
          {isLlm ? "🤖 Agent 物語化" : "📐 raw データ表示"} ({candidateCount}{" "}
          件候補)
        </div>
      </div>
      <p className="leading-relaxed text-zinc-700 dark:text-zinc-300">
        {narrative.overall_summary}
      </p>
    </div>
  );
}

// ============================================================================
// Timeline event list (縦タイムライン)
// ============================================================================

function TimelineList({
  events,
}: {
  events: TimelineEvent[];
}): React.ReactElement {
  // event_date 昇順でソート (BQ は ASC で送ってくる想定だが念のため)
  const sorted = [...events].sort((a, b) =>
    a.event_date.localeCompare(b.event_date),
  );
  return (
    <ol className="relative ml-3 space-y-4 border-l-2 border-blue-200 dark:border-blue-900">
      {sorted.map((event, idx) => (
        <TimelineEventCard key={event.source_speech_id + idx} event={event} />
      ))}
    </ol>
  );
}

function TimelineEventCard({
  event,
}: {
  event: TimelineEvent;
}): React.ReactElement {
  return (
    <li className="relative pl-6">
      {/* Timeline dot */}
      <span
        className={cn(
          "absolute left-0 top-2 -translate-x-1/2 inline-block rounded-full border-2 border-white dark:border-zinc-900",
          event.importance >= 70
            ? "h-4 w-4 bg-blue-600"
            : "h-3 w-3 bg-blue-400",
        )}
        aria-hidden="true"
      />
      <div className="rounded-xl border border-zinc-200 bg-white p-3 transition hover:border-blue-400 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-blue-600">
        <div className="flex items-baseline justify-between gap-2">
          <time className="text-xs text-zinc-500">{event.event_date}</time>
          <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
            {event.municipality_name || `自治体${event.municipality_code}`}
          </span>
        </div>
        <h3 className="mt-1 font-semibold leading-tight text-zinc-900 dark:text-zinc-100">
          {event.headline}
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
          {event.detail}
        </p>
        <Link
          href={`/feed/${encodeURIComponent(event.source_speech_id)}`}
          className="mt-2 inline-block text-xs text-blue-600 hover:underline dark:text-blue-400"
        >
          → 議題詳細を見る
        </Link>
      </div>
    </li>
  );
}
