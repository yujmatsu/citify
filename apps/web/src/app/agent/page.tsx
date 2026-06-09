"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AutonomyTrace } from "@/components/watcher/autonomy-trace";
import { RunProgress } from "@/components/watcher/run-progress";
import { SpecialistFindings } from "@/components/watcher/specialist-findings";
import { TownAssessmentCard } from "@/components/watcher/town-assessment-card";
import { TownRadar } from "@/components/watcher/town-radar";
import { VerdictCard } from "@/components/watcher/verdict-card";
import {
  fetchCompareStats,
  fetchWatcherAnalysis,
  runWatcher,
  type CompareStatsResponse,
  type TownAnalysis,
  type WatchlistBody,
  type WatcherRunLog,
} from "@/lib/api";
import {
  findByCode,
  loadMunicipalities,
  type Municipality,
} from "@/lib/municipalities";
import {
  homeCode,
  loadPersona,
  watchedCodes,
  type Persona,
} from "@/lib/persona";

const NATIONAL_DIET_CODE = "00000";

type LoadState =
  | { kind: "loading" }
  | { kind: "needs_town"; persona: Persona }
  | {
      kind: "ready";
      persona: Persona;
      munis: Municipality[];
      analysis: TownAnalysis | null;
      latestRun: WatcherRunLog | null;
      compareStats: CompareStatsResponse | null;
    }
  | { kind: "error"; message: string };

/** persona から「国会を除いた」住む街+候補を取り出す。home が国会なら候補先頭を昇格。 */
function realTowns(persona: Persona): {
  home: string | null;
  watched: string[];
} {
  const watched = watchedCodes(persona).filter((c) => c !== NATIONAL_DIET_CODE);
  let home = homeCode(persona);
  if (home === NATIONAL_DIET_CODE || !home) {
    home = watched.shift() ?? null;
  }
  return { home, watched };
}

function toBody(persona: Persona): WatchlistBody | null {
  const { home, watched } = realTowns(persona);
  if (!home) return null;
  return {
    age_group: persona.age_group,
    interests: persona.interests,
    home_municipality_code: home,
    watched_codes: watched,
    // TASK-ONBOARDING: 前提整理を Watcher に渡す
    priorities: persona.priorities,
    household: persona.household ?? "",
    budget_man: persona.budget_man,
    free_form_context: persona.free_form_context,
  };
}

export default function AgentHomePage(): React.JSX.Element {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  useEffect(() => {
    const persona = loadPersona();
    if (!persona) {
      router.replace("/onboarding");
      return;
    }
    if (!realTowns(persona).home) {
      setState({ kind: "needs_town", persona });
      return;
    }
    const { home, watched } = realTowns(persona);
    const codes = [home, ...watched].filter((c): c is string => Boolean(c));
    let cancelled = false;
    Promise.all([
      loadMunicipalities(),
      fetchWatcherAnalysis(persona.user_id),
      // 比較レーダーは分析の有無に関係なく出す。失敗しても致命的でないので空で握りつぶす
      fetchCompareStats(codes).catch(() => null),
    ])
      .then(([munis, res, compareStats]) => {
        if (cancelled) return;
        setState({
          kind: "ready",
          persona,
          munis,
          analysis: res.analysis,
          latestRun: res.latest_run,
          compareStats,
        });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  const handleRun = useCallback(async () => {
    if (state.kind !== "ready") return;
    const body = toBody(state.persona);
    if (!body) return;
    setRunning(true);
    setRunError(null);
    try {
      const res = await runWatcher(state.persona.user_id, body);
      setState({ ...state, analysis: res.analysis, latestRun: res.run_log });
    } catch (err) {
      setRunError(err instanceof Error ? err.message : String(err));
    } finally {
      setRunning(false);
    }
  }, [state]);

  if (state.kind === "loading") {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">エージェントを起動中...</p>
      </main>
    );
  }

  if (state.kind === "needs_town") {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">住む街を登録してください</h1>
          <p className="text-sm text-zinc-500">
            街選びアナリストは「住む街（基準）」と「気になる街（候補）」を比較します。
            国会以外の実在する街を登録してください。
          </p>
          <Link
            href="/onboarding"
            className="inline-flex items-center justify-center rounded-full bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-emerald-700"
          >
            街を登録する
          </Link>
        </div>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">読み込みに失敗しました</h1>
          <p className="text-sm text-zinc-500">{state.message}</p>
          <Link
            href="/"
            className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            トップに戻る
          </Link>
        </div>
      </main>
    );
  }

  const { persona, munis, analysis, latestRun, compareStats } = state;
  const nameOf = (code: string): string =>
    findByCode(munis, code)?.name ?? `自治体 ${code}`;
  const { home, watched } = realTowns(persona);
  const recommendedCode = analysis?.verdict.recommended_code ?? null;

  return (
    <main className="flex flex-1 flex-col px-5 pb-24 pt-6">
      <div className="mx-auto w-full max-w-md space-y-5">
        {/* ヒーロー */}
        <header className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
            マイ街エージェント・街選びアナリスト
          </p>
          <h1 className="text-2xl font-semibold leading-tight tracking-tight">
            住み続ける？
            <br />
            それとも移る？
          </h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            住む街{home ? `（${nameOf(home)}）` : ""}を基準に、気になる街
            {watched.length > 0 ? `（${watched.map(nameOf).join("・")}）` : ""}
            と比較して、AI が「どこが今のあなたに合うか」を考え続けます。
          </p>
        </header>

        {/* ライブ実行ボタン (① 自律性を体感させる) */}
        <button
          type="button"
          onClick={handleRun}
          disabled={running}
          className="flex h-12 w-full items-center justify-center gap-2 rounded-full bg-emerald-600 text-base font-medium text-white transition-colors hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-emerald-400"
        >
          {running ? (
            <>
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              街を比較・分析中...
            </>
          ) : analysis ? (
            <>🔄 もう一度分析してもらう</>
          ) : (
            <>🔍 今すぐ分析してもらう</>
          )}
        </button>
        {running && (
          <RunProgress
            townLabel={[home, ...watched]
              .filter(Boolean)
              .map((c) => nameOf(c as string))
              .join("・")}
          />
        )}
        {runError && (
          <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            実行に失敗しました: {runError}
          </p>
        )}

        {/* 自律の証跡 */}
        {latestRun && <AutonomyTrace runLog={latestRun} />}

        {/* 街比較レーダー (財政力・所得・持ち家・財政健全度・治安) */}
        {compareStats && compareStats.towns.length > 0 && (
          <section className="space-y-2 rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              街の総合比較
            </h2>
            <TownRadar data={compareStats} />
          </section>
        )}

        {analysis ? (
          <>
            {/* 前回からの変化 (A3) */}
            {analysis.changes_since_last.length > 0 && (
              <section className="space-y-1 rounded-2xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950">
                <h2 className="text-sm font-semibold text-amber-800 dark:text-amber-300">
                  🔔 前回からの変化
                </h2>
                <ul className="space-y-0.5 text-sm text-amber-900 dark:text-amber-200">
                  {analysis.changes_since_last.map((c, i) => (
                    <li key={i} className="flex gap-1.5">
                      <span aria-hidden>・</span>
                      <span>{c}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* 生きた結論 (払いの瞬間: 上品にリビール) */}
            <div className="reveal-up">
              <VerdictCard
                verdict={analysis.verdict}
                recommendedName={
                  recommendedCode ? nameOf(recommendedCode) : undefined
                }
              />
            </div>

            {/* データ薄の正直表示: 議題が拾えていない時は統計中心と明示 (空振り回避) */}
            {analysis.town_assessments.length > 0 &&
              analysis.town_assessments.every(
                (a) => (a.source_speech_ids?.length ?? 0) === 0,
              ) && (
                <p className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
                  ℹ️ この街は議題データが少なめのため、統計（人口・財政・暮らし）中心の評価です。
                </p>
              )}

            {/* 出口: この結論を行動に変える移住アクションプランへ (TASK-ACTIONPLAN) */}
            <Link
              href="/plan"
              className="block rounded-2xl border border-emerald-300 bg-emerald-50 p-4 text-center text-sm font-semibold text-emerald-800 transition-colors hover:bg-emerald-100 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200 dark:hover:bg-emerald-900"
            >
              📋 この結論を「次にやること」に — 移住アクションプランを作る →
            </Link>

            {/* 専門エージェントの所見 (A5 マルチエージェント) */}
            <SpecialistFindings findings={analysis.specialist_findings} />

            {/* 検証と反論 (A1 自己批判 / A9 悪魔の代弁者) */}
            {(analysis.critique_note || analysis.devils_advocate) && (
              <section className="space-y-2 rounded-2xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900">
                <h2 className="text-sm font-semibold">⚖️ AI の自己検証と反論</h2>
                {analysis.critique_note && (
                  <p className="text-xs text-zinc-600 dark:text-zinc-400">
                    <span className="font-medium">🔍 自己検証:</span>{" "}
                    {analysis.critique_note}
                  </p>
                )}
                {analysis.devils_advocate && (
                  <p className="text-xs text-zinc-600 dark:text-zinc-400">
                    <span className="font-medium">😈 反対意見:</span>{" "}
                    {analysis.devils_advocate}
                  </p>
                )}
              </section>
            )}

            {/* 街の比較 */}
            {analysis.town_assessments.length > 0 && (
              <section className="space-y-3">
                <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                  街の比較
                </h2>
                {/* TownAssessmentCard rows below */}
                {analysis.town_assessments.map((a) => (
                  <TownAssessmentCard
                    key={a.municipality_code}
                    assessment={a}
                    municipalityName={nameOf(a.municipality_code)}
                    isRecommended={a.municipality_code === recommendedCode}
                  />
                ))}
              </section>
            )}

            {/* 次の決め手 */}
            {analysis.watch_points.length > 0 && (
              <section className="space-y-2 rounded-2xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-900">
                <h2 className="text-sm font-semibold">
                  👀 次の決め手になる変化
                </h2>
                <ul className="space-y-1 text-sm text-zinc-600 dark:text-zinc-400">
                  {analysis.watch_points.map((w, i) => (
                    <li key={i} className="flex gap-2">
                      <span aria-hidden className="text-zinc-400">
                        ・
                      </span>
                      <span>{w}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {/* もっと確かにするには (A7: エージェントが認識する不確実性) */}
            {analysis.open_questions.length > 0 && (
              <section className="space-y-2 rounded-2xl border border-dashed border-zinc-300 p-4 dark:border-zinc-700">
                <h2 className="text-sm font-semibold text-zinc-600 dark:text-zinc-400">
                  ❓ もっと確かにするには
                </h2>
                <ul className="space-y-1 text-sm text-zinc-500">
                  {analysis.open_questions.map((q, i) => (
                    <li key={i} className="flex gap-2">
                      <span aria-hidden>・</span>
                      <span>{q}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </>
        ) : (
          <div className="space-y-3 rounded-2xl border border-dashed border-zinc-300 p-6 text-center dark:border-zinc-700">
            <p className="text-sm font-medium">まだ分析がありません</p>
            <p className="text-xs text-zinc-500">
              「今すぐ分析してもらう」を押すと、エージェントが住む街と候補を比較して
              「住み続けるか/移るならどこか」の結論を出します。
            </p>
          </div>
        )}

        <footer className="pt-2 text-center text-xs text-zinc-500">
          <p className="flex flex-wrap justify-center gap-4">
            <Link
              href="/concierge"
              className="font-medium text-blue-600 underline hover:text-blue-800 dark:text-blue-400"
            >
              💬 もっと相談する
            </Link>
            <Link
              href="/feed"
              className="underline hover:text-zinc-700 dark:hover:text-zinc-300"
            >
              フィードを見る
            </Link>
            <Link
              href="/onboarding"
              className="underline hover:text-zinc-700 dark:hover:text-zinc-300"
            >
              街・関心を変更
            </Link>
          </p>
        </footer>
      </div>
    </main>
  );
}
