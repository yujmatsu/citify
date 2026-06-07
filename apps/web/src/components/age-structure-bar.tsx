"use client";

import type React from "react";
import type { MunicipalityStats } from "@/lib/api";

/**
 * 年齢構成の横棒 (設計B B2c)。若年(15-29)/中間/高齢(65+) の構成比を可視化。
 * youth_share_pct / elderly_share_pct が無ければ非表示。自前 div(依存なし)。
 */
export function AgeStructureBar({
  stats,
}: {
  stats: MunicipalityStats;
}): React.JSX.Element | null {
  const youth = stats.youth_share_pct;
  const elderly = stats.elderly_share_pct;
  if (youth == null || elderly == null) return null;
  const middle = Math.max(0, 100 - youth - elderly);

  const segs = [
    { label: "若年 (15-29)", pct: youth, cls: "bg-emerald-500" },
    { label: "中間層", pct: middle, cls: "bg-zinc-300 dark:bg-zinc-600" },
    { label: "高齢 (65+)", pct: elderly, cls: "bg-rose-400" },
  ];

  return (
    <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-lg font-semibold">👥 年齢構成</h2>
      <div className="flex h-6 w-full overflow-hidden rounded-full">
        {segs.map((s) => (
          <div
            key={s.label}
            className={s.cls}
            style={{ width: `${s.pct}%` }}
            title={`${s.label}: ${s.pct.toFixed(1)}%`}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {segs.map((s) => (
          <span key={s.label} className="inline-flex items-center gap-1.5">
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${s.cls}`}
            />
            {s.label}: {s.pct.toFixed(1)}%
          </span>
        ))}
      </div>
    </section>
  );
}
