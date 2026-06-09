"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  type ActionPlan,
  fetchActionPlan,
  formatActionPlanForCopy,
  type RelocationSupport,
  runWatcher,
} from "@/lib/api";
import { RunProgress } from "@/components/watcher/run-progress";
import { loadPersona, type Persona } from "@/lib/persona";

type State =
  | { kind: "loading" }
  | { kind: "empty" }
  | { kind: "ok"; plan: ActionPlan }
  | { kind: "error"; message: string };

function checksKey(plan: ActionPlan, userId: string): string {
  return `plan:${userId}:${plan.run_id}`;
}

export default function ActionPlanPage(): React.JSX.Element {
  const router = useRouter();
  const [persona, setPersona] = useState<Persona | null>(null);
  const [state, setState] = useState<State>({ kind: "loading" });
  const [running, setRunning] = useState(false);
  const [checkedQ, setCheckedQ] = useState<Set<string>>(new Set());
  const [checkedV, setCheckedV] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);

  const loadPlan = useCallback(async (userId: string) => {
    setState({ kind: "loading" });
    try {
      const res = await fetchActionPlan(userId);
      if (!res.plan) {
        setState({ kind: "empty" });
        return;
      }
      const plan = res.plan;
      setState({ kind: "ok", plan });
      // localStorage からチェック状態を復元 (持ち帰り、リロードで消えない)
      try {
        const raw = localStorage.getItem(checksKey(plan, userId));
        if (raw) {
          const saved = JSON.parse(raw) as {
            questions?: string[];
            visit?: string[];
          };
          setCheckedQ(new Set(saved.questions ?? []));
          setCheckedV(new Set(saved.visit ?? []));
        }
      } catch {
        /* ignore */
      }
    } catch (err) {
      setState({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }, []);

  useEffect(() => {
    const p = loadPersona();
    if (!p) {
      router.replace("/onboarding");
      return;
    }
    setPersona(p);
    void loadPlan(p.user_id);
  }, [router, loadPlan]);

  // チェック状態を localStorage に保存
  const persist = useCallback(
    (plan: ActionPlan, q: Set<string>, v: Set<string>) => {
      if (!persona) return;
      try {
        localStorage.setItem(
          checksKey(plan, persona.user_id),
          JSON.stringify({ questions: [...q], visit: [...v] }),
        );
      } catch {
        /* ignore */
      }
    },
    [persona],
  );

  const toggleItem = useCallback((which: "q" | "v", item: string) => {
    const setter = which === "q" ? setCheckedQ : setCheckedV;
    setter((prev) => {
      const next = new Set(prev);
      if (next.has(item)) next.delete(item);
      else next.add(item);
      return next;
    });
  }, []);

  // チェック変更を localStorage に保存 (stale closure を避け effect で)
  useEffect(() => {
    if (state.kind === "ok") persist(state.plan, checkedQ, checkedV);
  }, [state, checkedQ, checkedV, persist]);

  // 空状態からワンタップ分析 (保存済 watchlist で実行→プラン再取得)
  const runAndLoad = async () => {
    if (!persona) return;
    setRunning(true);
    try {
      await runWatcher(persona.user_id);
      await loadPlan(persona.user_id);
    } catch {
      // watchlist 未保存等 → /agent へ誘導
      router.push("/agent");
    } finally {
      setRunning(false);
    }
  };

  const copy = async (plan: ActionPlan) => {
    try {
      await navigator.clipboard.writeText(
        formatActionPlanForCopy(plan, { questions: checkedQ, visit: checkedV }),
      );
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  };

  if (state.kind === "loading") {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">アクションプランを準備中...</p>
      </main>
    );
  }

  if (state.kind === "empty") {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">📋 移住アクションプラン</h1>
          <p className="text-sm text-zinc-500">
            まず街を分析すると、結論を「次にやること」に変えたプランを作れます。
          </p>
          {running ? (
            <RunProgress />
          ) : (
            <>
              <button
                type="button"
                onClick={runAndLoad}
                className="inline-flex items-center justify-center rounded-full bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-700"
              >
                今すぐ分析してプランを作る
              </button>
              <p>
                <Link href="/agent" className="text-xs text-zinc-500 underline">
                  マイ街エージェントへ →
                </Link>
              </p>
            </>
          )}
        </div>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">プランを取得できません</h1>
          <p className="text-sm text-zinc-500">{state.message}</p>
          <Link href="/agent" className="text-sm underline">
            マイ街エージェントに戻る
          </Link>
        </div>
      </main>
    );
  }

  return (
    <PlanView
      plan={state.plan}
      {...{ checkedQ, checkedV, toggleItem, copy, copied }}
    />
  );
}

function PlanView({
  plan,
  checkedQ,
  checkedV,
  toggleItem,
  copy,
  copied,
}: {
  plan: ActionPlan;
  checkedQ: Set<string>;
  checkedV: Set<string>;
  toggleItem: (which: "q" | "v", item: string) => void;
  copy: (plan: ActionPlan) => void;
  copied: boolean;
}): React.JSX.Element {
  const isStay = plan.mode === "stay";
  const totalChecks = plan.open_questions.length + plan.visit_checklist.length;
  const doneChecks = useMemo(() => {
    let n = 0;
    for (const q of plan.open_questions) if (checkedQ.has(q)) n++;
    for (const v of plan.visit_checklist) if (checkedV.has(v)) n++;
    return n;
  }, [plan, checkedQ, checkedV]);
  const allDone = totalChecks > 0 && doneChecks === totalChecks;

  return (
    <main className="flex flex-1 flex-col px-6 pb-24 pt-6 sm:px-10 sm:py-10">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        <div className="flex items-center justify-between print:hidden">
          <Link href="/agent" className="text-sm text-zinc-500 underline">
            ← マイ街エージェント
          </Link>
        </div>

        {/* ヘッダー + 役割 */}
        <header className="space-y-1">
          <h1 className="text-2xl font-bold">📋 移住アクションプラン</h1>
          <p className="text-sm text-zinc-500">
            分析の結論を「次の行動」に変える画面です。
          </p>
        </header>

        {/* 結論ストリップ (コンパクト) */}
        <section className="rounded-2xl border border-emerald-300 bg-emerald-50 p-4 dark:border-emerald-800 dark:bg-emerald-950">
          <div className="flex items-center gap-2">
            <span className="rounded-full bg-emerald-600 px-2 py-0.5 text-[10px] font-semibold text-white">
              {isStay ? "🏠 今の街に留まる" : "⭐ 移住候補"}
            </span>
            <span className="font-semibold">{plan.recommended_name}</span>
          </div>
          {plan.decision_summary && (
            <p className="mt-1 text-sm text-zinc-700 dark:text-zinc-200">
              {plan.decision_summary}
            </p>
          )}
        </section>

        {/* 次にやること (3ステップ) = 主役 */}
        <section className="space-y-2 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-sm font-semibold text-zinc-500">
            ✅ 次にやること
          </h2>
          <ol className="space-y-1 text-sm">
            <li>① 残る確認事項を潰す（下のチェック）</li>
            <li>
              ②{" "}
              {isStay
                ? "自分の街を移住者目線で再点検する"
                : "現地を自分の目で見る"}
            </li>
            {!isStay && <li>③ 公式の移住相談窓口に問い合わせる</li>}
          </ol>
        </section>

        {/* 決め手 (折りたたみ、副次) */}
        {plan.reasons.length > 0 && (
          <details className="rounded-2xl border border-zinc-200 p-4 dark:border-zinc-800">
            <summary className="cursor-pointer text-sm font-semibold text-zinc-600 dark:text-zinc-300">
              なぜ {plan.recommended_name} か（決め手）
            </summary>
            <ul className="mt-2 space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
              {plan.reasons.map((r) => (
                <li key={r}>・{r}</li>
              ))}
            </ul>
          </details>
        )}

        {/* 残る確認事項 (チェック式) */}
        {plan.open_questions.length > 0 && (
          <section className="space-y-2 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-sm font-semibold text-zinc-500">
              🔍 残る確認事項（これが分かれば決められる）
            </h2>
            {plan.open_questions.map((q) => (
              <label key={q} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={checkedQ.has(q)}
                  onChange={() => toggleItem("q", q)}
                  className="mt-1"
                />
                <span
                  className={
                    checkedQ.has(q) ? "text-zinc-400 line-through" : ""
                  }
                >
                  {q}
                </span>
              </label>
            ))}
          </section>
        )}

        {/* 現地訪問チェックリスト */}
        {plan.visit_checklist.length > 0 && (
          <section className="space-y-2 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-sm font-semibold text-zinc-500">
              {isStay ? "🏠 自分の街を再点検" : "🚶 現地で確かめる"}
            </h2>
            {plan.visit_checklist.map((v) => (
              <label key={v} className="flex items-start gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={checkedV.has(v)}
                  onChange={() => toggleItem("v", v)}
                  className="mt-1"
                />
                <span
                  className={
                    checkedV.has(v) ? "text-zinc-400 line-through" : ""
                  }
                >
                  {v}
                </span>
              </label>
            ))}
          </section>
        )}

        {/* 到達フィードバック */}
        {allDone && (
          <p className="rounded-xl bg-emerald-50 px-4 py-3 text-center text-sm font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
            ✅ 確認が揃いました。あとは
            {isStay ? "今の街を見直しましょう" : "現地で確かめましょう"}。
          </p>
        )}

        {/* 💰 受けられる可能性のある支援金 (TASK-SUPPORT) */}
        {plan.support?.national && (
          <SupportSection support={plan.support} />
        )}

        {/* 公式の相談窓口 */}
        {plan.official_links.length > 0 && (
          <section className="space-y-2 rounded-2xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-sm font-semibold text-zinc-500">
              🏛 公式の相談窓口
            </h2>
            {plan.official_links.map((l) => (
              <a
                key={l.url}
                href={l.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block text-sm text-emerald-700 underline hover:text-emerald-800 dark:text-emerald-400"
              >
                {l.label} →
              </a>
            ))}
          </section>
        )}

        {/* 家族と共有 */}
        <section className="flex flex-wrap gap-3 print:hidden">
          <button
            type="button"
            onClick={() => window.print()}
            className="rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            🖨 印刷
          </button>
          <button
            type="button"
            onClick={() => copy(plan)}
            className="rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            {copied ? "✓ コピーしました" : "📋 テキストでコピー（家族に共有）"}
          </button>
        </section>

        <p className="pb-8 text-center text-xs text-zinc-400">
          AI が中立な検討材料として作成しました。最終判断はご自身の価値観で。
        </p>
      </div>
    </main>
  );
}

/** 💰 受けられる可能性のある支援金 (TASK-SUPPORT)。断定せず「可能性」、公式で要確認。 */
function SupportSection({
  support,
}: {
  support: RelocationSupport;
}): React.JSX.Element | null {
  const n = support.national;
  if (!n) return null;
  const eligible = n.eligibility !== "unlikely";
  const amountLabel =
    n.amount_man != null
      ? `最大 ${n.amount_man} 万円`
      : "単身60万・世帯100万（構成により）";
  return (
    <section className="space-y-2 rounded-2xl border border-emerald-200 bg-emerald-50/60 p-5 dark:border-emerald-900 dark:bg-emerald-950/40">
      <h2 className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">
        💰 受けられる可能性のある支援金
      </h2>
      <div className="space-y-1 text-sm">
        <p className="font-medium">国の移住支援金</p>
        {eligible ? (
          <p className="text-zinc-700 dark:text-zinc-200">
            {amountLabel} の対象の<span className="font-semibold">可能性</span>
            {n.child_addition &&
              "（＋18歳未満の子1人あたり最大100万円加算の可能性）"}
          </p>
        ) : (
          <p className="text-zinc-600 dark:text-zinc-400">
            現時点では対象外の可能性
          </p>
        )}
        {n.note && <p className="text-xs text-zinc-500">{n.note}</p>}
        {n.requirements && (
          <p className="text-xs text-zinc-500">要件: {n.requirements}</p>
        )}
        {n.official_url && (
          <a
            href={n.official_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block text-sm font-medium text-emerald-700 underline hover:text-emerald-800 dark:text-emerald-400"
          >
            公式で確認する →
          </a>
        )}
      </div>

      {/* 自治体独自支援 (P2 で抽出。P1 では空) */}
      {support.local.length > 0 && (
        <div className="space-y-1 border-t border-emerald-200 pt-2 dark:border-emerald-900">
          <p className="text-sm font-medium">自治体独自の支援</p>
          {support.local.map((l) => (
            <a
              key={l.official_url || l.name}
              href={l.official_url}
              target="_blank"
              rel="noopener noreferrer"
              className="block text-sm text-emerald-700 underline hover:text-emerald-800 dark:text-emerald-400"
            >
              {l.name} →
            </a>
          ))}
        </div>
      )}

      <p className="text-[11px] leading-relaxed text-zinc-400">
        金額・対象は概算です。最終的な要件・金額は自治体公式で必ずご確認ください。
      </p>
    </section>
  );
}
