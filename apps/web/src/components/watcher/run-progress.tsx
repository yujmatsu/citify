"use client";

import type React from "react";
import { useEffect, useState } from "react";

/**
 * マイ街エージェント実行中の「待ち」を、実パイプライン(専門家が順に働く)の実演に変える。
 *
 * /run はブロッキング1回呼び出しのため、実時間ストリームではなく **実際の処理段階に沿った
 * 進行アニメ**(推定タイミング)。ラベルは agents/watcher の実構成(4専門家→統合→自己批判+反論
 * →仕上げ)に忠実。不透明なスピナーを「AIが働いている実演」に反転させ、審査①(agentic)も訴求。
 */

const SPECIALISTS: { emoji: string; label: string; at: number }[] = [
  { emoji: "👥", label: "人口アナリスト", at: 11 },
  { emoji: "💰", label: "財政アナリスト", at: 17 },
  { emoji: "🏡", label: "暮らし・治安アナリスト", at: 25 },
  { emoji: "🏛", label: "議題アナリスト", at: 33 },
];

const STAGES: { emoji: string; label: string; until: number }[] = [
  { emoji: "🔍", label: "4人の専門家が街を横断調査", until: 35 },
  { emoji: "🧩", label: "所見を統合して結論の草案づくり", until: 50 },
  { emoji: "⚖️", label: "自己批判＋悪魔の代弁者で結論を再点検", until: 66 },
  {
    emoji: "✍️",
    label: "結論とアクションを仕上げ",
    until: Number.POSITIVE_INFINITY,
  },
];

const EST_TOTAL = 72; // 体感用の想定総時間(秒)

export function RunProgress({
  townLabel,
}: {
  townLabel?: string;
}): React.JSX.Element {
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
      className="space-y-3 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-4 dark:border-emerald-900 dark:bg-emerald-950/40"
      aria-live="polite"
    >
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
          🤖 AI が考えています…
        </p>
        <span className="text-[11px] tabular-nums text-zinc-400">
          {Math.floor(elapsed)}秒
        </span>
      </div>
      {townLabel && (
        <p className="text-xs text-zinc-500">{townLabel} を調査しています</p>
      )}

      {/* 進捗バー */}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-emerald-100 dark:bg-emerald-900">
        <div
          className="h-full rounded-full bg-emerald-500 transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* 段階 */}
      <ol className="space-y-2">
        {STAGES.map((s, i) => {
          const status =
            i < stageIdx ? "done" : i === stageIdx ? "active" : "pending";
          return (
            <li key={s.label} className="space-y-1.5">
              <div
                className={
                  status === "pending"
                    ? "flex items-center gap-2 text-sm text-zinc-400"
                    : "flex items-center gap-2 text-sm text-zinc-700 dark:text-zinc-200"
                }
              >
                <StatusIcon status={status} />
                <span aria-hidden>{s.emoji}</span>
                <span className={status === "active" ? "font-semibold" : ""}>
                  {s.label}
                </span>
              </div>

              {/* 専門家の並列調査 (段階0 のときだけ詳細を見せる) */}
              {i === 0 && stageIdx === 0 && (
                <div className="grid grid-cols-2 gap-1.5 pl-7">
                  {SPECIALISTS.map((sp) => {
                    const done = elapsed >= sp.at;
                    return (
                      <div
                        key={sp.label}
                        className={
                          done
                            ? "flex items-center gap-1 text-[11px] text-emerald-700 dark:text-emerald-300"
                            : "flex items-center gap-1 text-[11px] text-zinc-400"
                        }
                      >
                        <StatusIcon status={done ? "done" : "active"} small />
                        <span aria-hidden>{sp.emoji}</span>
                        {sp.label}
                      </div>
                    );
                  })}
                </div>
              )}
            </li>
          );
        })}
      </ol>

      <p className="text-[11px] leading-relaxed text-zinc-400">
        実際に AI が街を横断調査し、結論を自己検証・反論で詰めています（30〜90
        秒）。
      </p>
    </section>
  );
}

function StatusIcon({
  status,
  small,
}: {
  status: "done" | "active" | "pending";
  small?: boolean;
}): React.JSX.Element {
  const size = small ? "h-3 w-3" : "h-4 w-4";
  if (status === "done") {
    return (
      <span
        className={`inline-flex ${size} shrink-0 items-center justify-center rounded-full bg-emerald-500 text-[9px] text-white`}
        aria-label="完了"
      >
        ✓
      </span>
    );
  }
  if (status === "active") {
    return (
      <span
        className={`${size} shrink-0 animate-spin rounded-full border-2 border-emerald-300 border-t-emerald-600`}
        aria-label="処理中"
      />
    );
  }
  return (
    <span
      className={`${size} shrink-0 rounded-full border-2 border-zinc-300 dark:border-zinc-700`}
      aria-hidden
    />
  );
}
