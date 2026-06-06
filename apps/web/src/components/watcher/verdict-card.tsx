"use client";

import type { WatchVerdict } from "@/lib/api";
import { ConfidenceBadge } from "@/components/watcher/confidence-badge";

/**
 * エージェントの"生きた結論"カード(ヒーロー)。差別化の核。
 * 「移るべきか / 移るならどこか」を 1 行 + 根拠で示す。
 */
export function VerdictCard({
  verdict,
  recommendedName,
}: {
  verdict: WatchVerdict;
  recommendedName?: string;
}): React.JSX.Element {
  return (
    <section className="space-y-3 rounded-2xl border border-emerald-300 bg-gradient-to-b from-emerald-50 to-white p-5 shadow-sm dark:border-emerald-800 dark:from-emerald-950 dark:to-zinc-900">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700 dark:text-emerald-300">
          🤖 エージェントの結論（今のところ）
        </p>
        <ConfidenceBadge confidence={verdict.confidence} />
      </div>
      <h2 className="text-xl font-bold leading-snug tracking-tight">
        {verdict.headline}
      </h2>
      {verdict.reasoning && (
        <p className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
          {verdict.reasoning}
        </p>
      )}
      {recommendedName && (
        <p className="inline-flex items-center gap-1 rounded-full bg-emerald-600 px-3 py-1 text-xs font-semibold text-white">
          現時点の推し: {recommendedName}
        </p>
      )}
    </section>
  );
}
