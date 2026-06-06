"use client";

import Link from "next/link";
import type { WatcherDiscovery } from "@/lib/api";
import { cn } from "@/lib/utils";

const SIGNIFICANCE_STYLE: Record<
  WatcherDiscovery["significance"],
  { label: string; cls: string }
> = {
  high: {
    label: "重要度 高",
    cls: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  },
  medium: {
    label: "重要度 中",
    cls: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  },
  low: {
    label: "重要度 低",
    cls: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400",
  },
};

/**
 * エージェントの発見 1 件のカード。
 * 差別化の核 = why_surfaced(「なぜあなたに」)を最も目立つ位置に置く。
 */
export function DiscoveryCard({
  discovery,
  municipalityName,
}: {
  discovery: WatcherDiscovery;
  municipalityName?: string;
}): React.JSX.Element {
  const sig = SIGNIFICANCE_STYLE[discovery.significance];
  const muni = municipalityName ?? `自治体 ${discovery.municipality_code}`;

  return (
    <article className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center justify-between gap-2">
        <Link
          href={`/cities/${discovery.municipality_code}`}
          className="inline-flex items-center gap-1 rounded-full bg-zinc-100 px-2.5 py-0.5 text-xs font-medium text-zinc-600 transition-colors hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
        >
          📍 {muni}
        </Link>
        <span
          className={cn(
            "rounded-full px-2.5 py-0.5 text-[10px] font-semibold",
            sig.cls,
          )}
        >
          {sig.label}
        </span>
      </div>

      <h3 className="text-lg font-semibold leading-snug tracking-tight">
        {discovery.title}
      </h3>

      {discovery.summary.length > 0 && (
        <ul className="space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
          {discovery.summary.map((line, i) => (
            <li key={i} className="flex gap-2">
              <span aria-hidden className="text-zinc-400">
                ・
              </span>
              <span>{line}</span>
            </li>
          ))}
        </ul>
      )}

      {/* why_surfaced = 差別化の核。エージェントが「なぜあなたに」を説明 */}
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-900 dark:bg-emerald-950">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
          🤖 なぜあなたに
        </p>
        <p className="mt-1 text-sm text-emerald-900 dark:text-emerald-100">
          {discovery.why_surfaced}
        </p>
      </div>

      {discovery.source_speech_ids.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-zinc-400">
          <span>📄 根拠:</span>
          {discovery.source_speech_ids.slice(0, 3).map((sid, i) => (
            <Link
              key={sid}
              href={`/feed/${encodeURIComponent(sid)}`}
              className="underline decoration-dotted hover:text-emerald-600 dark:hover:text-emerald-400"
            >
              議題 {i + 1}
            </Link>
          ))}
          {discovery.source_speech_ids.length > 3 && (
            <span>ほか {discovery.source_speech_ids.length - 3} 件</span>
          )}
        </div>
      )}
    </article>
  );
}
