"use client";

import Link from "next/link";
import { useState } from "react";

import {
  ApiError,
  fetchOpsHealth,
  type OpsFinding,
  type OpsHealthResponse,
  type OpsRemediationProposal,
  type OpsRunLog,
  type OpsVerdict,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
  high: "bg-orange-100 text-orange-700 dark:bg-orange-950 dark:text-orange-300",
  medium: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  low: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  none: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-500",
};

const RISK_COLORS = {
  safe: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  moderate: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  risky: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
} as const;

const DOMAIN_LABEL: Record<string, string> = {
  scraper_health: "🩺 スクレイパー健全性",
  cost: "💸 コスト",
  data_freshness: "🕐 データ鮮度",
};

const FRESHNESS_STALE_HOURS = 30;

export default function OpsCrewPage() {
  const [data, setData] = useState<OpsHealthResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function handleRun() {
    setLoading(true);
    setError(null);
    fetchOpsHealth({ days: 7, useSample: true })
      .then((res) => {
        setData(res);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          setError(
            "🔒 管理トークンが必要です (OPS_ADMIN_TOKEN が server 側で設定されています)。",
          );
        } else if (err instanceof ApiError) {
          setError(`API エラー (${err.status}): ${err.message}`);
        } else if (err instanceof Error) {
          setError(err.message);
        } else {
          setError("取得失敗");
        }
        setData(null);
      })
      .finally(() => {
        setLoading(false);
      });
  }

  const assessment = data?.assessment ?? null;
  const runLog = data?.run_log ?? null;
  const isEmpty = runLog?.status === "empty";

  return (
    <main className="flex flex-1 flex-col px-6 pb-6 pt-6 sm:px-10">
      <div className="mx-auto flex w-full max-w-4xl flex-1 flex-col space-y-6">
        <div className="flex items-center justify-between">
          <Link
            href="/admin"
            className="text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← 開発者向けに戻る
          </Link>
          <span className="text-xs text-zinc-500">
            🛠️ Ops Crew (DevOps × AI Agent、admin)
          </span>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            🛠️ 運用SREクルー
          </h1>
          <p className="text-sm text-zinc-500">
            Watcher と同じ設計 (計画 → 並列専門家 → 統合 → 批判 → 人間ゲート)
            を、自分たちの運用 (スクレイパー健全性 / コスト異常 / データ鮮度)
            に適用します。<b>自動実行は一切しません</b>、人間レビュー後に手動で
            対応してください。
          </p>
        </header>

        <div>
          <button
            type="button"
            onClick={handleRun}
            disabled={loading}
            className="rounded-xl bg-zinc-900 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            {loading ? "⏳ 実行中..." : "▶ 運用アセスメントを実行"}
          </button>
        </div>

        {loading && (
          <div className="rounded-xl border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            ⏳ クルーが計画を立て、専門家を並列実行し、結果を統合中...
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200">
            ❌ {error}
          </div>
        )}

        {!loading && !error && data && (
          <>
            <FreshnessBanner hours={data.freshness_hours} />

            {isEmpty && (
              <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200">
                ✅ 対処すべき運用課題は検出されませんでした
              </div>
            )}

            {assessment && (
              <>
                <VerdictCard verdict={assessment.verdict} />

                {assessment.findings.length > 0 && (
                  <FindingsList findings={assessment.findings} />
                )}

                {assessment.proposals.length > 0 && (
                  <ProposalsList proposals={assessment.proposals} />
                )}

                {assessment.critique_note && (
                  <CritiqueBox note={assessment.critique_note} />
                )}
              </>
            )}

            {runLog && <AutonomyTraceSection runLog={runLog} />}
          </>
        )}
      </div>
    </main>
  );
}

// ============================================================================
// FreshnessBanner
// ============================================================================

function FreshnessBanner({
  hours,
}: {
  hours: number | null;
}): React.ReactElement | null {
  if (hours == null) return null;
  const stale = hours > FRESHNESS_STALE_HOURS;

  return (
    <div
      className={cn(
        "rounded-xl border px-4 py-3 text-sm",
        stale
          ? "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200"
          : "border-zinc-200 bg-white text-zinc-600 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-400",
      )}
    >
      {stale ? "⚠️" : "🕐"} データ鮮度: 最終取込から {hours.toFixed(1)} 時間
      {stale && " (30時間超、データが古い可能性があります)"}
    </div>
  );
}

// ============================================================================
// VerdictCard
// ============================================================================

function VerdictCard({ verdict }: { verdict: OpsVerdict }): React.ReactElement {
  return (
    <div className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-bold">
          {verdict.headline || "(結論なし)"}
        </h2>
        {verdict.top_priority_domain && (
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[11px] font-semibold text-blue-700 dark:bg-blue-950 dark:text-blue-300">
            優先対応:{" "}
            {DOMAIN_LABEL[verdict.top_priority_domain] ??
              verdict.top_priority_domain}
          </span>
        )}
        <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
          確信度: {verdict.confidence}
        </span>
        {verdict.requires_human_review && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
            ✅ 人間レビュー必須
          </span>
        )}
      </div>
      {verdict.reasoning && (
        <p className="mt-2 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
          {verdict.reasoning}
        </p>
      )}
    </div>
  );
}

// ============================================================================
// FindingsList
// ============================================================================

function FindingsList({
  findings,
}: {
  findings: OpsFinding[];
}): React.ReactElement {
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
        専門家の所見 ({findings.length} 件)
      </h2>
      {findings.map((f, i) => (
        <div
          key={`${f.domain}-${i}`}
          className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
              {DOMAIN_LABEL[f.domain] ?? f.domain}
            </span>
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px]",
                SEVERITY_COLORS[f.severity] ?? SEVERITY_COLORS.none,
              )}
            >
              {f.severity}
            </span>
          </div>
          {f.headline && (
            <p className="mt-1 text-sm text-zinc-800 dark:text-zinc-200">
              {f.headline}
            </p>
          )}
          {f.key_points.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs text-zinc-600 dark:text-zinc-400">
              {f.key_points.map((kp, j) => (
                <li key={j}>・{kp}</li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

// ============================================================================
// ProposalsList
// ============================================================================

function ProposalsList({
  proposals,
}: {
  proposals: OpsRemediationProposal[];
}): React.ReactElement {
  return (
    <div className="space-y-3">
      <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
        改善提案 ({proposals.length} 件)
      </h2>
      {proposals.map((p, i) => (
        <div
          key={`${p.domain}-${i}`}
          className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-xs font-semibold text-emerald-900 dark:text-emerald-100">
              {DOMAIN_LABEL[p.domain] ?? p.domain} — {p.action}
            </h3>
            <div className="flex items-center gap-1 text-[10px]">
              <span
                className={cn(
                  "rounded px-1.5 py-0.5",
                  RISK_COLORS[p.risk_assessment],
                )}
              >
                {p.risk_assessment}
              </span>
              <span className="text-emerald-700 dark:text-emerald-300">
                {p.source === "llm" ? "🤖" : "📐"}
              </span>
            </div>
          </div>
          {p.rationale && (
            <p className="mt-1 text-xs leading-relaxed text-emerald-800 dark:text-emerald-200">
              {p.rationale}
            </p>
          )}
          <div className="mt-1 text-[10px] text-emerald-700 dark:text-emerald-300">
            ⚠️ requires_human_review: {String(p.requires_human_review)}{" "}
            (自動実行はしません / 人間レビュー前提)
          </div>
        </div>
      ))}
    </div>
  );
}

// ============================================================================
// CritiqueBox
// ============================================================================

function CritiqueBox({ note }: { note: string }): React.ReactElement {
  return (
    <div className="rounded-xl border border-purple-200 bg-purple-50 p-4 dark:border-purple-800 dark:bg-purple-950">
      <h3 className="text-sm font-semibold text-purple-900 dark:text-purple-100">
        🔍 批判エージェントの指摘
      </h3>
      <p className="mt-1 text-xs leading-relaxed text-purple-700 dark:text-purple-300">
        {note}
      </p>
    </div>
  );
}

// ============================================================================
// AutonomyTraceSection (autonomy-trace.tsx と同一パターン、OpsRunLog 用)
// ============================================================================

function AutonomyTraceSection({
  runLog,
}: {
  runLog: OpsRunLog;
}): React.ReactElement {
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
          クルーの自律的な調査ステップ
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
                    <span className="font-medium">{tc.tool}</span>
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
            <span>調査対象: {runLog.targets_checked.join(", ") || "-"}</span>
            <span>所見件数: {runLog.n_findings} 件</span>
            {runLog.token_cost != null && (
              <span>消費トークン: {runLog.token_cost.toLocaleString()}</span>
            )}
            <span>状態: {runLog.status}</span>
          </div>
          {runLog.status !== "ok" && runLog.note && (
            <p className="break-all rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-700 dark:bg-amber-950 dark:text-amber-300">
              診断: {runLog.note}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
