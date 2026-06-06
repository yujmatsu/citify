"use client";

import Link from "next/link";
import type { TownAssessment } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 1 つの街(住む街=基準 or 候補)の多軸評価カード。
 * 住む街と候補を並べることで「移るべきか/どこへ」の比較を可視化する。
 */
export function TownAssessmentCard({
  assessment,
  municipalityName,
  isRecommended,
}: {
  assessment: TownAssessment;
  municipalityName?: string;
  isRecommended?: boolean;
}): React.JSX.Element {
  const muni = municipalityName ?? `自治体 ${assessment.municipality_code}`;
  const isHome = assessment.role === "home";

  return (
    <article
      className={cn(
        "space-y-3 rounded-2xl border bg-white p-4 shadow-sm dark:bg-zinc-900",
        isRecommended
          ? "border-emerald-400 dark:border-emerald-700"
          : "border-zinc-200 dark:border-zinc-800",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Link
            href={`/cities/${assessment.municipality_code}`}
            className="font-semibold hover:underline"
          >
            {muni}
          </Link>
          <span
            className={cn(
              "rounded-full px-2 py-0.5 text-[10px] font-semibold",
              isHome
                ? "bg-zinc-200 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-200"
                : "bg-sky-100 text-sky-700 dark:bg-sky-950 dark:text-sky-300",
            )}
          >
            {isHome ? "🏠 住む街（基準）" : "⭐ 候補"}
          </span>
        </div>
        <span className="shrink-0 text-xs font-semibold tabular-nums text-emerald-700 dark:text-emerald-300">
          適合 {assessment.fit_score}
        </span>
      </div>

      <p className="text-sm font-medium">{assessment.headline}</p>

      {assessment.population_outlook && (
        <p className="text-xs text-zinc-500">
          📉 人口見通し: {assessment.population_outlook}
        </p>
      )}

      <div className="grid grid-cols-2 gap-2 text-xs">
        {assessment.strengths.length > 0 && (
          <div className="space-y-1">
            <p className="font-semibold text-emerald-700 dark:text-emerald-300">
              強み
            </p>
            <ul className="space-y-0.5 text-zinc-600 dark:text-zinc-400">
              {assessment.strengths.map((s, i) => (
                <li key={i}>+ {s}</li>
              ))}
            </ul>
          </div>
        )}
        {assessment.concerns.length > 0 && (
          <div className="space-y-1">
            <p className="font-semibold text-rose-700 dark:text-rose-300">
              懸念
            </p>
            <ul className="space-y-0.5 text-zinc-600 dark:text-zinc-400">
              {assessment.concerns.map((c, i) => (
                <li key={i}>- {c}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {assessment.recent_signal && (
        <p className="rounded-lg bg-zinc-50 px-3 py-2 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          🆕 {assessment.recent_signal}
        </p>
      )}

      {assessment.source_speech_ids.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-zinc-400">
          <span>📄 根拠:</span>
          {assessment.source_speech_ids.slice(0, 3).map((sid, i) => (
            <Link
              key={sid}
              href={`/feed/${encodeURIComponent(sid)}`}
              className="underline decoration-dotted hover:text-emerald-600 dark:hover:text-emerald-400"
            >
              議題 {i + 1}
            </Link>
          ))}
        </div>
      )}
    </article>
  );
}
