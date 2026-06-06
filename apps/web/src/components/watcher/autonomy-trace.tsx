"use client";

import { useState } from "react";
import type { WatcherRunLog } from "@/lib/api";
import { cn } from "@/lib/utils";

const TOOL_LABEL: Record<string, string> = {
  search_speeches: "議題を検索",
  fetch_population_trend: "人口推移を取得",
  compare_towns: "複数の街を比較",
};

/**
 * エージェントの自律実行ログを折りたたみ表示する = ①「AI が自分で考えた」の可視化。
 * tool_calls = LLM が *自分で* 選んだ調査計画。これが「ただのデータ集約」批判への対抗軸。
 */
export function AutonomyTrace({
  runLog,
}: {
  runLog: WatcherRunLog;
}): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const n = runLog.tool_calls.length;

  return (
    <section className="rounded-2xl border border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 text-sm font-medium">
          <span aria-hidden>🧠</span>
          エージェントの自律的な調査ステップ
          <span className="rounded-full bg-zinc-200 px-2 py-0.5 text-[10px] font-semibold tabular-nums text-zinc-600 dark:bg-zinc-700 dark:text-zinc-300">
            {n}
          </span>
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
          {n === 0 ? (
            <p className="text-xs text-zinc-500">
              このランではツールが呼ばれませんでした。
            </p>
          ) : (
            <ol className="space-y-2">
              {runLog.tool_calls.map((tc, i) => (
                <li key={i} className="flex gap-3 text-sm">
                  <span className="shrink-0 font-mono text-xs text-zinc-400">
                    {i + 1}.
                  </span>
                  <div className="min-w-0">
                    <span className="font-medium">
                      {TOOL_LABEL[tc.tool] ?? tc.tool}
                    </span>
                    {Object.keys(tc.args).length > 0 && (
                      <span className="ml-2 break-all font-mono text-[11px] text-zinc-500">
                        {JSON.stringify(tc.args)}
                      </span>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-500">
            <span>調査した街: {runLog.towns_checked.length} 件</span>
            <span>発見: {runLog.n_discoveries} 件</span>
            {runLog.token_cost != null && (
              <span>消費トークン: {runLog.token_cost.toLocaleString()}</span>
            )}
            <span>状態: {runLog.status}</span>
          </div>
        </div>
      )}
    </section>
  );
}
