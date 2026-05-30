"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ReasoningExplainerButton } from "@/components/reasoning-explainer";
import {
  ApiError,
  fetchScraperHealth,
  type ScraperHealthEntry,
  type ScraperHealthResponse,
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

export default function ScraperHealthPage() {
  // useSearchParams() を子に閉じ込めて Suspense でラップ (Next.js 16 要件)
  return (
    <Suspense
      fallback={
        <main className="flex flex-1 items-center justify-center">
          <p className="text-sm text-zinc-500">読み込み中...</p>
        </main>
      }
    >
      <ScraperHealthInner />
    </Suspense>
  );
}

function ScraperHealthInner() {
  const searchParams = useSearchParams();
  const [data, setData] = useState<ScraperHealthResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [useSample, setUseSample] = useState<boolean>(true);

  // Reviewer Medium: 簡易 admin ガード (NEXT_PUBLIC_ADMIN_TOKEN と URL ?token=... を比較)
  const expectedToken = process.env.NEXT_PUBLIC_ADMIN_TOKEN ?? "";
  const providedToken = searchParams.get("token") ?? "";
  const authorized = expectedToken === "" || providedToken === expectedToken;

  useEffect(() => {
    if (!authorized) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchScraperHealth({ days: 7, limit: 50, useSample })
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
  }, [authorized, useSample]);

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
            🩺 Scraper Health (Plan F、admin)
          </span>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            🩺 Self-healing Scraper
          </h1>
          <p className="text-sm text-zinc-500">
            スクレイパー失敗ログを 2 段階 Agent (Diagnostic + RepairProposal)
            で診断 +
            修正提案。**自動修正は適用されません**、人間レビュー後に手動で適用してください。
          </p>
        </header>

        {/* Disclaimer (常設、Reviewer High #1 必須) */}
        {data?.disclaimer && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
            ⚠️ {data.disclaimer}
          </div>
        )}

        {/* Sample toggle */}
        <div className="flex items-center gap-2 text-xs">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={useSample}
              onChange={(e) => setUseSample(e.target.checked)}
            />
            <span>Sample seed を使用 (demo 用、Firestore 未投入時)</span>
          </label>
        </div>

        {loading && (
          <div className="rounded-xl border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            ⏳ Agent が失敗を診断し、修正提案を生成中...
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200">
            ❌ {error}
          </div>
        )}

        {!loading && !error && data && (
          <>
            {/* 統計サマリ */}
            <StatsSummary data={data} />

            {/* Drop 候補 */}
            {data.drop_candidates.length > 0 && (
              <DropCandidates tenants={data.drop_candidates} />
            )}

            {/* 失敗カード一覧 */}
            <div className="space-y-3">
              <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                失敗パターン詳細 ({data.entries.length} 件)
              </h2>
              {data.entries.map((entry) => (
                <FailureCard key={entry.failure.failure_id} entry={entry} />
              ))}
            </div>
          </>
        )}
      </div>
    </main>
  );
}

// ============================================================================
// StatsSummary
// ============================================================================

function StatsSummary({
  data,
}: {
  data: ScraperHealthResponse;
}): React.ReactElement {
  const categoryEntries = useMemo(
    () => Object.entries(data.by_category).sort((a, b) => b[1] - a[1]),
    [data.by_category],
  );
  const scraperEntries = useMemo(
    () => Object.entries(data.by_scraper).sort((a, b) => b[1] - a[1]),
    [data.by_scraper],
  );

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="text-xs text-zinc-500">総失敗パターン数</div>
        <div className="mt-1 text-2xl font-bold">{data.total_failures}</div>
        <div className="text-[10px] text-zinc-500">過去 7 日 (重複排除前)</div>
      </div>
      <div className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="text-xs text-zinc-500">エラーカテゴリ別</div>
        <ul className="mt-1 space-y-0.5 text-xs">
          {categoryEntries.map(([cat, n]) => (
            <li key={cat} className="flex justify-between">
              <span>{cat}</span>
              <span className="font-mono">{n}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
        <div className="text-xs text-zinc-500">スクレイパー別</div>
        <ul className="mt-1 space-y-0.5 text-xs">
          {scraperEntries.map(([sc, n]) => (
            <li key={sc} className="flex justify-between">
              <span>{sc}</span>
              <span className="font-mono">{n}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

// ============================================================================
// DropCandidates
// ============================================================================

function DropCandidates({
  tenants,
}: {
  tenants: string[];
}): React.ReactElement {
  return (
    <div className="rounded-xl border border-rose-200 bg-rose-50 p-4 dark:border-rose-800 dark:bg-rose-950">
      <h3 className="text-sm font-semibold text-rose-900 dark:text-rose-100">
        🗑 Drop 候補 ({tenants.length} 件)
      </h3>
      <p className="mt-1 text-xs text-rose-700 dark:text-rose-300">
        Agent が `drop_tenant` を提案した tenant_id。人間レビュー後に Drop
        判断してください。
      </p>
      <ul className="mt-2 flex flex-wrap gap-1.5">
        {tenants.map((t) => (
          <li
            key={t}
            className="rounded bg-rose-200 px-2 py-0.5 text-xs font-mono text-rose-800 dark:bg-rose-900 dark:text-rose-200"
          >
            {t}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ============================================================================
// FailureCard
// ============================================================================

function FailureCard({
  entry,
}: {
  entry: ScraperHealthEntry;
}): React.ReactElement {
  const [copied, setCopied] = useState(false);
  const { failure, diagnostic, proposal } = entry;

  function handleCopy() {
    navigator.clipboard?.writeText(proposal.code_hint);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <details className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
      <summary className="cursor-pointer space-y-1 list-none">
        <div className="flex items-baseline justify-between gap-2">
          <div className="font-mono text-xs text-zinc-700 dark:text-zinc-300">
            {failure.scraper}
            {failure.tenant_id && (
              <span className="ml-1 text-zinc-500">/ {failure.tenant_id}</span>
            )}
          </div>
          <div className="flex items-center gap-1 text-[10px]">
            <span
              className={cn(
                "rounded px-1.5 py-0.5",
                SEVERITY_COLORS[diagnostic.severity],
              )}
            >
              {diagnostic.severity}
            </span>
            <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
              {diagnostic.error_category}
            </span>
          </div>
        </div>
        <div className="text-xs text-zinc-600 dark:text-zinc-400">
          {failure.error_type}
        </div>
      </summary>

      <div className="mt-3 space-y-3">
        {/* failure metadata */}
        <div className="rounded border border-zinc-200 bg-zinc-50 p-2 text-[10px] dark:border-zinc-700 dark:bg-zinc-950">
          <div className="font-mono text-zinc-500">{failure.failure_id}</div>
          <div>
            🕐 {failure.timestamp}
            {failure.duration_ms != null && ` (${failure.duration_ms}ms)`}
          </div>
          {failure.url && (
            <div className="break-all text-zinc-500">URL: {failure.url}</div>
          )}
        </div>

        {/* Diagnostic */}
        <div className="rounded-lg border border-blue-200 bg-blue-50 p-2 dark:border-blue-800 dark:bg-blue-950">
          <div className="flex items-baseline justify-between gap-2">
            <h4 className="text-xs font-semibold text-blue-900 dark:text-blue-100">
              🩺 Diagnostic ({diagnostic.confidence})
            </h4>
            <span className="text-[10px] text-blue-700 dark:text-blue-300">
              {diagnostic.source === "llm" ? "🤖 Agent" : "📐 rule-based"}
            </span>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-blue-800 dark:text-blue-200">
            {diagnostic.root_cause_text}
          </p>
          {/* Plan PP: Reasoning Transparency (Meta-Reasoner) */}
          <div className="mt-2 flex justify-end">
            <ReasoningExplainerButton
              agentName="scraper_doctor"
              rawReasoning={diagnostic.root_cause_text}
              agentOutputSummary={`${failure.scraper} / ${failure.error_type} → category=${diagnostic.error_category}, severity=${diagnostic.severity}`}
            />
          </div>
        </div>

        {/* Repair proposal */}
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-2 dark:border-emerald-800 dark:bg-emerald-950">
          <div className="flex items-baseline justify-between gap-2">
            <h4 className="text-xs font-semibold text-emerald-900 dark:text-emerald-100">
              🔧 Repair Proposal
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
            </div>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-emerald-800 dark:text-emerald-200">
            {proposal.rationale}
          </p>
          {proposal.code_hint && (
            <div className="mt-2 rounded border border-emerald-300 bg-white p-2 text-[10px] font-mono text-zinc-700 dark:border-emerald-700 dark:bg-zinc-950 dark:text-zinc-300">
              <div className="flex items-baseline justify-between">
                <span className="text-emerald-700 dark:text-emerald-300">
                  Code hint:
                </span>
                <button
                  type="button"
                  onClick={handleCopy}
                  className="text-[10px] text-emerald-600 hover:underline dark:text-emerald-400"
                >
                  {copied ? "✓ コピー済" : "📋 コピー"}
                </button>
              </div>
              <pre className="mt-1 whitespace-pre-wrap">
                {proposal.code_hint}
              </pre>
            </div>
          )}
          <div className="mt-1 text-[10px] text-emerald-700 dark:text-emerald-300">
            ⚠️ requires_human_review: {String(proposal.requires_human_review)}{" "}
            (自動 PR は実装されません)
          </div>
        </div>

        {/* stack trace (折りたたみ) */}
        {failure.stack_trace && (
          <details className="rounded border border-zinc-200 bg-zinc-50 p-2 text-[10px] dark:border-zinc-700 dark:bg-zinc-950">
            <summary className="cursor-pointer text-zinc-600 dark:text-zinc-400">
              📋 Stack trace (PII マスク済)
            </summary>
            <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">
              {failure.stack_trace}
            </pre>
          </details>
        )}
      </div>
    </details>
  );
}
