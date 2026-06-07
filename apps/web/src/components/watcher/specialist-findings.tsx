"use client";

import { useState } from "react";
import { ConfidenceBadge } from "@/components/watcher/confidence-badge";
import type { SpecialistFinding } from "@/lib/api";
import { cn } from "@/lib/utils";

const DOMAIN_META: Record<string, { label: string; emoji: string }> = {
  population: { label: "人口アナリスト", emoji: "📊" },
  fiscal: { label: "財政アナリスト", emoji: "💰" },
  living_safety: { label: "暮らし・治安アナリスト", emoji: "🏡" },
  topics: { label: "議題アナリスト", emoji: "📋" },
};

/**
 * マルチエージェント(P3, A5)の専門家所見。4人の専門エージェントが各ドメインを
 * 並行調査した結果を可視化 = 「チームで考えるAI」の証跡。折りたたみ式。
 */
export function SpecialistFindings({
  findings,
}: {
  findings: SpecialistFinding[];
}): React.JSX.Element | null {
  const [open, setOpen] = useState(false);
  if (findings.length === 0) return null;

  return (
    <section className="rounded-2xl border border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 text-sm font-medium">
          <span aria-hidden>👥</span>
          専門エージェント {findings.length} 人の所見
        </span>
        <span
          className={cn(
            "text-zinc-400 transition-transform",
            open && "rotate-180",
          )}
          aria-hidden
        >
          ▾
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-zinc-200 px-4 py-3 dark:border-zinc-800">
          {findings.map((f) => {
            const meta = DOMAIN_META[f.domain] ?? {
              label: f.domain,
              emoji: "🔎",
            };
            return (
              <div key={f.domain} className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold">
                    {meta.emoji} {meta.label}
                  </span>
                  <ConfidenceBadge confidence={f.confidence} />
                </div>
                {f.headline && (
                  <p className="text-sm text-zinc-700 dark:text-zinc-300">
                    {f.headline}
                  </p>
                )}
                {f.key_points.length > 0 && (
                  <ul className="space-y-0.5 text-xs text-zinc-500">
                    {f.key_points.map((p, i) => (
                      <li key={i} className="flex gap-1.5">
                        <span aria-hidden>・</span>
                        <span>{p}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
