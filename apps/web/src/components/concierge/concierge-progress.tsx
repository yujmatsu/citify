"use client";

import type React from "react";
import { useEffect, useState } from "react";

/**
 * コンシェルジュ応答中(15〜30秒)の待ちを、実処理段階の実演にする。
 *
 * 段階は agents/concierge の実フロー(質問理解→街検索→候補採点・比較→説明生成)に沿う。
 * 単一エージェント+ツールのため Watcher の RunProgress とは別構成(専門家の並列なし)。
 */

const STAGES: { emoji: string; label: string; until: number }[] = [
  { emoji: "🧠", label: "ご相談の内容を理解", until: 4 },
  { emoji: "🔍", label: "条件に合う街を全国から検索", until: 11 },
  { emoji: "📊", label: "候補をあなたの優先順位で採点・比較", until: 18 },
  {
    emoji: "✍️",
    label: "おすすめと理由を生成",
    until: Number.POSITIVE_INFINITY,
  },
];

const EST_TOTAL = 22;

export function ConciergeProgress(): React.JSX.Element {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = performance.now();
    const id = setInterval(() => {
      setElapsed((performance.now() - start) / 1000);
    }, 300);
    return () => clearInterval(id);
  }, []);

  const stageIdx = (() => {
    const i = STAGES.findIndex((s) => elapsed < s.until);
    return i === -1 ? STAGES.length - 1 : i;
  })();
  const pct = Math.min(95, Math.round((elapsed / EST_TOTAL) * 100));

  return (
    <section
      className="space-y-2.5 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-4 dark:border-emerald-900 dark:bg-emerald-950/40"
      aria-live="polite"
    >
      <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
        💬 コンシェルジュが調べています…
      </p>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-emerald-100 dark:bg-emerald-900">
        <div
          className="h-full rounded-full bg-emerald-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
      <ol className="space-y-1.5">
        {STAGES.map((s, i) => {
          const status =
            i < stageIdx ? "done" : i === stageIdx ? "active" : "pending";
          return (
            <li
              key={s.label}
              className={
                status === "pending"
                  ? "flex items-center gap-2 text-sm text-zinc-400"
                  : "flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-200"
              }
            >
              {status === "done" ? (
                <span
                  className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-500 text-[9px] text-white"
                  aria-label="完了"
                >
                  ✓
                </span>
              ) : status === "active" ? (
                <span
                  className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-emerald-300 border-t-emerald-600"
                  aria-label="処理中"
                />
              ) : (
                <span
                  className="h-4 w-4 shrink-0 rounded-full border-2 border-zinc-300 dark:border-zinc-700"
                  aria-hidden
                />
              )}
              <span aria-hidden>{s.emoji}</span>
              <span className={status === "active" ? "font-semibold" : ""}>
                {s.label}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
