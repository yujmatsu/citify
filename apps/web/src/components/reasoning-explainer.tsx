"use client";

import { useState } from "react";

import {
  ApiError,
  fetchReasoningExplanation,
  type AgentName,
  type ReasoningExplanation,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * 各 Agent (Concierge / Forecast / Heatmap / Timeline / Doctor / ...) 内に挿入する
 * 「🔍 Agent の思考を詳しく見る」ボタン + on-demand modal。Plan PP の再利用可能 component。
 */
export function ReasoningExplainerButton({
  agentName,
  rawReasoning,
  agentOutputSummary,
  personaContext,
  buttonClassName,
}: {
  agentName: AgentName;
  rawReasoning: string;
  agentOutputSummary: string;
  personaContext?: string;
  buttonClassName?: string;
}): React.ReactElement {
  const [isOpen, setIsOpen] = useState(false);
  const [data, setData] = useState<ReasoningExplanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleOpen() {
    setIsOpen(true);
    if (data || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetchReasoningExplanation({
        agentName,
        rawReasoning,
        agentOutputSummary,
        personaContext,
      });
      setData(res);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `API エラー (${err.status}): ${err.message}`
          : err instanceof Error
            ? err.message
            : "取得失敗";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        disabled={loading}
        className={cn(
          "inline-flex items-center gap-1 rounded-full border border-purple-300 bg-purple-50 px-3 py-1 text-xs text-purple-700 transition hover:bg-purple-100 disabled:opacity-50 dark:border-purple-700 dark:bg-purple-950 dark:text-purple-300 dark:hover:bg-purple-900",
          buttonClassName,
        )}
      >
        🔍 Agent の思考を詳しく見る
      </button>

      {isOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Agent の思考説明"
          className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/50 px-4 py-6 backdrop-blur-sm"
          onClick={() => setIsOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-2xl max-h-[80vh] overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-700 dark:bg-zinc-900"
          >
            <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-3 dark:border-zinc-700">
              <h2 className="text-sm font-semibold">
                🔍 Agent の思考 ({agentName})
              </h2>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                aria-label="閉じる"
                className="rounded-lg px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                ✕ 閉じる
              </button>
            </div>

            <div className="max-h-[calc(80vh-3rem)] space-y-3 overflow-y-auto p-4 text-sm">
              {loading && (
                <p className="text-center text-zinc-500">
                  ⏳ Meta-Reasoner Agent が思考を平易化中...
                </p>
              )}
              {error && (
                <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-xs text-rose-800 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200">
                  ❌ {error}
                </div>
              )}
              {data && <ExplanationView explanation={data} />}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function ExplanationView({
  explanation,
}: {
  explanation: ReasoningExplanation;
}): React.ReactElement {
  const isLlm = explanation.source === "llm";
  return (
    <div className="space-y-3">
      {/* Source + confidence badge */}
      <div className="flex flex-wrap items-center gap-2 text-[10px]">
        <span
          className={cn(
            "rounded px-1.5 py-0.5",
            isLlm
              ? "bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300"
              : "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
          )}
        >
          {isLlm ? "🤖 Meta-Reasoner" : "📐 rule-based"}
        </span>
        <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
          信頼度: {explanation.confidence}
        </span>
      </div>

      {/* Plain summary */}
      <section className="rounded-xl border border-purple-200 bg-purple-50 p-3 dark:border-purple-800 dark:bg-purple-950">
        <h3 className="text-xs font-semibold text-purple-900 dark:text-purple-100">
          📖 Agent はこう考えた
        </h3>
        <p className="mt-1 leading-relaxed text-zinc-800 dark:text-zinc-200">
          {explanation.plain_summary}
        </p>
      </section>

      {/* Influencing factors */}
      {explanation.influencing_factors.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
            💡 判断に影響した要素
          </h3>
          <ul className="mt-1 space-y-1 list-disc pl-5 text-xs text-zinc-700 dark:text-zinc-300">
            {explanation.influencing_factors.map((f, i) => (
              <li key={`f-${i}-${f.slice(0, 20)}`}>{f}</li>
            ))}
          </ul>
        </section>
      )}

      {/* Counterfactuals */}
      {explanation.counterfactuals.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
            🔄 もし違っていたら
          </h3>
          <ul className="mt-1 space-y-1 list-disc pl-5 text-xs text-zinc-700 dark:text-zinc-300">
            {explanation.counterfactuals.map((c, i) => (
              <li key={`c-${i}-${c.slice(0, 20)}`}>{c}</li>
            ))}
          </ul>
        </section>
      )}

      {/* Caveats */}
      {explanation.caveats.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
            ⚠️ 注意点 / 限界
          </h3>
          <ul className="mt-1 space-y-1 list-disc pl-5 text-xs text-zinc-700 dark:text-zinc-300">
            {explanation.caveats.map((c, i) => (
              <li key={`cv-${i}-${c.slice(0, 20)}`}>{c}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
