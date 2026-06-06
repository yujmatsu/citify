"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { AutonomyTrace } from "@/components/watcher/autonomy-trace";
import { DiscoveryCard } from "@/components/watcher/discovery-card";
import {
  fetchWatcherDiscoveries,
  runWatcher,
  type WatchlistBody,
  type WatcherDiscovery,
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

type LoadState =
  | { kind: "loading" }
  | {
      kind: "ready";
      persona: Persona;
      munis: Municipality[];
      discoveries: WatcherDiscovery[];
      latestRun: WatcherRunLog | null;
    }
  | { kind: "error"; message: string };

function toBody(persona: Persona): WatchlistBody {
  return {
    age_group: persona.age_group,
    interests: persona.interests,
    home_municipality_code: homeCode(persona) ?? "00000",
    watched_codes: watchedCodes(persona),
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
    let cancelled = false;
    Promise.all([
      loadMunicipalities(),
      fetchWatcherDiscoveries(persona.user_id),
    ])
      .then(([munis, res]) => {
        if (cancelled) return;
        setState({
          kind: "ready",
          persona,
          munis,
          discoveries: res.discoveries,
          latestRun: res.latest_run,
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
    setRunning(true);
    setRunError(null);
    try {
      const res = await runWatcher(
        state.persona.user_id,
        toBody(state.persona),
      );
      setState({
        ...state,
        discoveries: res.discoveries,
        latestRun: res.run_log,
      });
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

  const { persona, munis, discoveries, latestRun } = state;
  const nameOf = (code: string): string =>
    findByCode(munis, code)?.name ?? `自治体 ${code}`;
  const home = homeCode(persona);
  const watched = watchedCodes(persona);

  return (
    <main className="flex flex-1 flex-col px-5 pb-24 pt-6">
      <div className="mx-auto w-full max-w-md space-y-5">
        {/* ヒーロー */}
        <header className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-emerald-600 dark:text-emerald-400">
            マイ街エージェント
          </p>
          <h1 className="text-2xl font-semibold leading-tight tracking-tight">
            あなたの街を、
            <br />
            AI が見張っています
          </h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            住む街
            {home ? `（${nameOf(home)}）` : ""}
            と気になる街
            {watched.length > 0 ? `（${watched.map(nameOf).join("・")}）` : ""}
            の議題から、あなたに意味のある動きを見つけて届けます。
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
              エージェントが調査中...
            </>
          ) : (
            <>🔍 今すぐ調べてもらう</>
          )}
        </button>
        {running && (
          <p className="text-center text-xs text-zinc-500">
            ツールを自分で選んで街を調べています（5〜20 秒ほど）
          </p>
        )}
        {runError && (
          <p className="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            実行に失敗しました: {runError}
          </p>
        )}

        {/* 自律の証跡 */}
        {latestRun && <AutonomyTrace runLog={latestRun} />}

        {/* 発見フィード */}
        {discoveries.length === 0 ? (
          <div className="space-y-3 rounded-2xl border border-dashed border-zinc-300 p-6 text-center dark:border-zinc-700">
            <p className="text-sm font-medium">まだ発見がありません</p>
            <p className="text-xs text-zinc-500">
              「今すぐ調べてもらう」を押すと、エージェントがあなたの街を調査して
              発見を届けます。
            </p>
          </div>
        ) : (
          <section className="space-y-4">
            <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              エージェントからの発見 {discoveries.length} 件
            </h2>
            {discoveries.map((d, i) => (
              <DiscoveryCard
                key={`${d.municipality_code}-${i}`}
                discovery={d}
                municipalityName={nameOf(d.municipality_code)}
              />
            ))}
          </section>
        )}

        <footer className="pt-2 text-center text-xs text-zinc-500">
          <p className="flex flex-wrap justify-center gap-4">
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
