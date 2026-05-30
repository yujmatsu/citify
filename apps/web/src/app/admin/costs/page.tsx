"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  fetchCostHealth,
  type CostHealthEntry,
  type CostHealthResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const SEVERITY_COLORS = {
  critical: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  high: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300",
  medium: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  low: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
} as const;

const RISK_COLORS = {
  safe: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  moderate: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  risky: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
} as const;

const ANOMALY_BADGE = {
  spike: "📈 spike",
  drift_up: "↗ drift_up",
  drift_down: "↘ drift_down",
  normal: "→ normal",
} as const;

export default function CostHealthPage() {
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center">
          <p className="text-sm text-zinc-500">読み込み中...</p>
        </main>
      }
    >
      <CostHealthInner />
    </Suspense>
  );
}

function CostHealthInner() {
  const searchParams = useSearchParams();
  const [data, setData] = useState<CostHealthResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 簡易 admin ガード (Plan F と同パターン)
  const expectedToken = process.env.NEXT_PUBLIC_ADMIN_TOKEN ?? "";
  const providedToken = searchParams.get("token") ?? "";
  const authorized = expectedToken === "" || providedToken === expectedToken;

  useEffect(() => {
    if (!authorized) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchCostHealth({ days: 30, limitEntries: 20 })
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
                : "取得失敗";
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
  }, [authorized]);

  if (!authorized) {
    return (
      <main className="flex flex-1 items-center justify-center px-6">
        <div className="rounded-2xl border border-rose-300 bg-rose-50 p-6 text-sm text-rose-800 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200">
          ❌ This admin page is restricted. URL に `?token=...`
          を付与してアクセスしてください。
          <div className="mt-2 text-xs text-rose-600 dark:text-rose-400">
            (production では IAM 認証に置換予定、MVP は env-based 簡易ガード)
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col px-6 pb-6 pt-6 sm:px-10">
      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col space-y-6">
        <div className="flex items-center justify-between">
          <Link
            href="/feed"
            className="text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← フィードに戻る
          </Link>
          <span className="text-xs text-zinc-500">
            💸 Cost Health (Plan CC、admin)
          </span>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            💸 Cost Anomaly Hunter
          </h1>
          <p className="text-sm text-zinc-500">
            GCP リソース cost data から 2 段階 Agent (Detector + RootCause)
            が異常スパイク検知 + 削減提案。 **自動 cost
            削減は実装されません**、人間レビュー後に手動で適用してください。
          </p>
        </header>

        {data?.disclaimer && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
            ⚠️ {data.disclaimer}
          </div>
        )}

        {loading && (
          <div className="rounded-xl border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            ⏳ Agent が cost data を分析し、異常を診断中...
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200">
            ❌ {error}
          </div>
        )}

        {!loading && !error && data && (
          <>
            <StatsSummary data={data} />

            {data.cross_service_pattern && (
              <CrossServicePattern pattern={data.cross_service_pattern} />
            )}

            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                異常パターン詳細 ({data.entries.length} 件)
              </h2>
              {data.entries.length === 0 ? (
                <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200">
                  ✅ 過去 30 日に重要 cost 異常は検出されませんでした
                </div>
              ) : (
                data.entries.map((entry, idx) => (
                  <AnomalyCard
                    key={`${entry.anomaly.service}-${entry.anomaly.date}-${idx}`}
                    entry={entry}
                  />
                ))
              )}
            </div>
          </>
        )}
      </div>
    </main>
  );
}

function StatsSummary({
  data,
}: {
  data: CostHealthResponse;
}): React.ReactElement {
  const categoryEntries = useMemo(
    () => Object.entries(data.by_service).sort((a, b) => b[1] - a[1]),
    [data.by_service],
  );
  const severityEntries = useMemo(
    () => Object.entries(data.by_severity).sort((a, b) => b[1] - a[1]),
    [data.by_severity],
  );

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="text-xs text-zinc-500">検出された異常</div>
        <div className="mt-1 text-2xl font-bold">{data.total_anomalies}</div>
        <div className="text-[10px] text-zinc-500">過去 30 日 (重要のみ)</div>
      </div>
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950">
        <div className="text-xs text-emerald-700 dark:text-emerald-300">
          推定月次削減額
        </div>
        <div className="mt-1 text-2xl font-bold text-emerald-900 dark:text-emerald-100">
          ¥{data.estimated_total_savings_jpy.toLocaleString()}
        </div>
        <div className="text-[10px] text-emerald-600 dark:text-emerald-400">
          Agent 推定 (人間レビュー必須)
        </div>
      </div>
      <div className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="text-xs text-zinc-500">severity 別</div>
        <ul className="mt-1 space-y-0.5 text-xs">
          {severityEntries.map(([s, n]) => (
            <li key={s} className="flex justify-between">
              <span>{s}</span>
              <span className="font-mono">{n}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900 sm:col-span-3">
        <div className="text-xs text-zinc-500">service 別</div>
        <ul className="mt-1 grid grid-cols-3 gap-2 text-xs">
          {categoryEntries.map(([sc, n]) => (
            <li key={sc} className="flex justify-between">
              <span className="font-mono">{sc}</span>
              <span className="font-mono">{n}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function CrossServicePattern({
  pattern,
}: {
  pattern: string;
}): React.ReactElement {
  return (
    <div className="rounded-xl border border-purple-200 bg-purple-50 p-4 dark:border-purple-800 dark:bg-purple-950">
      <h3 className="text-sm font-semibold text-purple-900 dark:text-purple-100">
        🔗 Cross-service 横断パターン (Plan F との差別化)
      </h3>
      <p className="mt-1 text-xs text-purple-700 dark:text-purple-300">
        {pattern}
      </p>
    </div>
  );
}

function AnomalyCard({
  entry,
}: {
  entry: CostHealthEntry;
}): React.ReactElement {
  const [copied, setCopied] = useState(false);
  const { anomaly, proposal } = entry;

  function handleCopy() {
    navigator.clipboard?.writeText(
      `${proposal.proposed_action}: ${proposal.rationale}`,
    );
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <details className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <summary className="cursor-pointer space-y-1 list-none">
        <div className="flex items-baseline justify-between gap-2">
          <div className="font-mono text-xs text-zinc-700 dark:text-zinc-300">
            {anomaly.service}{" "}
            <span className="text-zinc-500">/ {anomaly.date}</span>
          </div>
          <div className="flex items-center gap-1 text-[10px]">
            <span
              className={cn(
                "rounded px-1.5 py-0.5",
                SEVERITY_COLORS[anomaly.severity],
              )}
            >
              {anomaly.severity}
            </span>
            <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
              {ANOMALY_BADGE[anomaly.anomaly_type]}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs text-zinc-600 dark:text-zinc-400">
          <span>当日 ¥{anomaly.cost_jpy.toLocaleString()}</span>
          <span>baseline ¥{anomaly.baseline_avg_7d.toFixed(0)}</span>
          <span>spike {anomaly.spike_ratio.toFixed(2)}x</span>
          <span>z={anomaly.z_score.toFixed(1)}</span>
        </div>
      </summary>

      <div className="mt-3 space-y-3">
        {/* Diagnostic (root cause) */}
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-2 dark:border-blue-800 dark:bg-blue-950">
          <h4 className="text-xs font-semibold text-blue-900 dark:text-blue-100">
            🩺 Root cause hypothesis
          </h4>
          <p className="mt-1 text-xs leading-relaxed text-blue-800 dark:text-blue-200">
            {proposal.root_cause_hypothesis}
          </p>
        </div>

        {/* Proposal */}
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-2 dark:border-emerald-800 dark:bg-emerald-950">
          <div className="flex items-baseline justify-between gap-2">
            <h4 className="text-xs font-semibold text-emerald-900 dark:text-emerald-100">
              🔧 削減提案
            </h4>
            <div className="flex items-center gap-1 text-[10px]">
              <span
                className={cn(
                  "rounded px-1.5 py-0.5",
                  RISK_COLORS[proposal.risk_assessment],
                )}
              >
                {proposal.risk_assessment}
              </span>
              <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300">
                {proposal.proposed_action}
              </span>
              <span className="text-emerald-700 dark:text-emerald-300">
                {proposal.source === "llm" ? "🤖" : "📐"}
              </span>
            </div>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-emerald-800 dark:text-emerald-200">
            {proposal.rationale}
          </p>
          <div className="mt-2 flex items-baseline justify-between gap-2 rounded border border-emerald-300 bg-white p-2 dark:border-emerald-700 dark:bg-zinc-950">
            <div className="text-xs">
              <span className="text-emerald-700 dark:text-emerald-300">
                推定月次削減:{" "}
              </span>
              <span className="font-mono font-bold text-emerald-900 dark:text-emerald-100">
                ¥{proposal.monthly_savings_estimate_jpy.toLocaleString()}
              </span>
              <span className="ml-1 text-[10px] text-zinc-500">
                (上限 ¥100,000)
              </span>
            </div>
            <button
              type="button"
              onClick={handleCopy}
              className="text-[10px] text-emerald-600 hover:underline dark:text-emerald-400"
            >
              {copied ? "✓ コピー済" : "📋 提案をコピー"}
            </button>
          </div>
          <div className="mt-1 text-[10px] text-emerald-700 dark:text-emerald-300">
            ⚠️ requires_human_review: {String(proposal.requires_human_review)}{" "}
            (自動削減は実装されません)
          </div>
        </div>
      </div>
    </details>
  );
}
