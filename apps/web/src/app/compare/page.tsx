"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  fetchCompare,
  type CompareResponse,
  type CompareSpeech,
} from "@/lib/api";
import {
  findByCode,
  formatMunicipalityLabel,
  loadMunicipalities,
  type Municipality,
} from "@/lib/municipalities";
import {
  INTERESTS,
  type Interest,
  loadPersona,
  type Persona,
} from "@/lib/persona";
import { cn } from "@/lib/utils";

const INTEREST_EMOJI: Record<Interest, string> = {
  住居: "🏠",
  雇用: "💼",
  結婚: "💍",
  子育て: "👶",
  税: "💰",
  起業: "🚀",
  防災: "🌊",
  医療: "🏥",
  教育: "📚",
  移住: "🚆",
};

type State =
  | { kind: "init" }
  | { kind: "loading" }
  | { kind: "ok"; data: CompareResponse }
  | { kind: "error"; message: string };

export default function ComparePage() {
  const router = useRouter();
  const [persona, setPersona] = useState<Persona | null>(null);
  const [allMunis, setAllMunis] = useState<Municipality[] | null>(null);
  const [selectedMunis, setSelectedMunis] = useState<string[]>([]);
  const [interest, setInterest] = useState<Interest | null>(null);
  const [state, setState] = useState<State>({ kind: "init" });

  useEffect(() => {
    const p = loadPersona();
    if (!p) {
      router.replace("/onboarding");
      return;
    }
    setPersona(p);
    // デフォルトは登録自治体の先頭 2 つ (国会 00000 除く)
    const eligible = p.municipality_codes.filter((c) => c !== "00000");
    setSelectedMunis(eligible.slice(0, 2));
    // 関心軸の先頭をデフォルト選択
    if (p.interests.length > 0) {
      setInterest(p.interests[0] as Interest);
    }
    loadMunicipalities()
      .then(setAllMunis)
      .catch(() => setAllMunis([]));
  }, [router]);

  const eligibleMunis = useMemo(() => {
    if (!persona) return [];
    return persona.municipality_codes.filter((c) => c !== "00000");
  }, [persona]);

  function toggleMuni(code: string): void {
    setSelectedMunis((prev) => {
      if (prev.includes(code)) {
        return prev.filter((c) => c !== code);
      }
      if (prev.length >= 3) {
        return prev; // 最大 3 つ
      }
      return [...prev, code];
    });
  }

  async function handleCompare(): Promise<void> {
    if (!persona || !interest || selectedMunis.length < 2) return;
    setState({ kind: "loading" });
    try {
      const data = await fetchCompare(persona.user_id, selectedMunis, interest);
      setState({ kind: "ok", data });
    } catch (err) {
      setState({
        kind: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    }
  }

  const canCompare =
    persona !== null && interest !== null && selectedMunis.length >= 2;

  function muniLabel(code: string): string {
    if (!allMunis) return code;
    const m = findByCode(allMunis, code);
    return m ? formatMunicipalityLabel(m) : code;
  }

  return (
    <main className="flex flex-1 flex-col px-6 pb-24 pt-6 sm:px-10 sm:py-10">
      <div className="mx-auto w-full max-w-5xl space-y-8">
        {/* Top nav */}
        <div className="flex items-center justify-between">
          <Link
            href="/feed"
            className="text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← フィードに戻る
          </Link>
          <span className="text-xs text-zinc-500">Citify 比較ビュー</span>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            あなたの街 vs 隣の街
          </h1>
          <p className="text-sm text-zinc-500">
            登録した自治体を 2-3
            つ選んで、同じテーマの議論を横並びで比較できます。 自治体 HP
            では絶対に提供できない体験です。
          </p>
        </header>

        {/* テーマ選択 */}
        <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-sm font-semibold text-zinc-500">テーマを選択</h2>
          <div className="flex flex-wrap gap-2">
            {INTERESTS.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setInterest(t)}
                className={cn(
                  "rounded-full border px-3 py-1.5 text-sm transition-colors",
                  interest === t
                    ? "border-emerald-500 bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
                    : "border-zinc-300 hover:border-zinc-400 dark:border-zinc-700 dark:hover:border-zinc-500",
                )}
              >
                {INTEREST_EMOJI[t]} {t}
              </button>
            ))}
          </div>
        </section>

        {/* 自治体選択 */}
        <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-zinc-500">
              自治体を選択 (2-3 つ)
            </h2>
            <span className="text-xs text-zinc-400">
              選択中: {selectedMunis.length} / 3
            </span>
          </div>
          {eligibleMunis.length < 2 ? (
            <p className="text-sm text-rose-500">
              比較には 2 つ以上の自治体登録が必要です。
              <Link
                href="/municipalities"
                className="ml-2 underline hover:text-rose-700"
              >
                マイ自治体を編集 →
              </Link>
            </p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {eligibleMunis.map((code) => (
                <button
                  key={code}
                  type="button"
                  onClick={() => toggleMuni(code)}
                  className={cn(
                    "rounded-full border px-3 py-1.5 text-sm transition-colors",
                    selectedMunis.includes(code)
                      ? "border-emerald-500 bg-emerald-50 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
                      : "border-zinc-300 hover:border-zinc-400 dark:border-zinc-700 dark:hover:border-zinc-500",
                  )}
                  aria-pressed={selectedMunis.includes(code)}
                >
                  {muniLabel(code)}
                </button>
              ))}
            </div>
          )}
        </section>

        {/* 比較ボタン */}
        <button
          type="button"
          onClick={handleCompare}
          disabled={!canCompare || state.kind === "loading"}
          className={cn(
            "w-full rounded-full px-6 py-3 text-sm font-semibold transition-colors",
            canCompare && state.kind !== "loading"
              ? "bg-emerald-500 text-white hover:bg-emerald-600"
              : "cursor-not-allowed bg-zinc-200 text-zinc-500 dark:bg-zinc-800",
          )}
        >
          {state.kind === "loading" ? "比較中..." : "比較する"}
        </button>

        {/* 結果 */}
        {state.kind === "error" && (
          <p className="rounded-2xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-300">
            比較に失敗しました: {state.message}
          </p>
        )}

        {state.kind === "ok" && (
          <ComparisonResult data={state.data} muniLabel={muniLabel} />
        )}

        {/* 倫理表記 */}
        <p className="pb-8 text-center text-[10px] text-zinc-500">
          AI が説明用に翻訳・採点しました。投票推奨・政治的判断は含みません。
        </p>
      </div>
    </main>
  );
}

function ComparisonResult({
  data,
  muniLabel,
}: {
  data: CompareResponse;
  muniLabel: (code: string) => string;
}): React.JSX.Element {
  const cols = data.columns;
  const hasAnySpeech = cols.some((c) => c.speeches.length > 0);

  if (!hasAnySpeech) {
    return (
      <section className="rounded-2xl border border-zinc-200 bg-white p-6 text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
        このテーマの議題はまだ集まっていません。別のテーマを試してください。
      </section>
    );
  }

  return (
    <section className="space-y-6">
      {/* 観察 (AI 中立コメント) */}
      {data.observation && (
        <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5 dark:border-amber-900 dark:bg-amber-950">
          <h3 className="mb-2 text-xs font-semibold text-amber-700 dark:text-amber-300">
            📋 AI による中立的な観察
          </h3>
          <p className="text-sm leading-relaxed text-amber-900 dark:text-amber-200">
            {data.observation}
          </p>
        </div>
      )}

      {/* 横並びカラム */}
      <div
        className={cn(
          "grid gap-4",
          cols.length === 2 && "grid-cols-1 md:grid-cols-2",
          cols.length === 3 && "grid-cols-1 md:grid-cols-3",
        )}
      >
        {cols.map((col) => (
          <div
            key={col.municipality_code}
            className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900"
          >
            <h3 className="border-b border-zinc-200 pb-2 text-sm font-semibold dark:border-zinc-800">
              {muniLabel(col.municipality_code)}
            </h3>
            {col.speeches.length === 0 ? (
              <p className="text-xs text-zinc-500">
                このテーマの議題はありません
              </p>
            ) : (
              <ul className="space-y-4">
                {col.speeches.map((sp) => (
                  <SpeechCard key={sp.speech_id} sp={sp} />
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function SpeechCard({ sp }: { sp: CompareSpeech }): React.JSX.Element {
  return (
    <li className="space-y-2">
      <p className="text-sm font-semibold leading-snug">
        {sp.title || "(タイトル未生成)"}
      </p>
      {sp.summary.length > 0 && (
        <ul className="space-y-1 text-xs leading-relaxed text-zinc-600 dark:text-zinc-300">
          {sp.summary.map((line, i) => (
            <li key={i}>· {line}</li>
          ))}
        </ul>
      )}
      <div className="flex items-center justify-between gap-2 pt-1 text-[10px] text-zinc-400">
        <span>{sp.meeting_date ?? "—"}</span>
        <span>関連度 {sp.relevance_score}/100</span>
      </div>
      {sp.detail_url && (
        <a
          href={sp.detail_url}
          target="_blank"
          rel="noopener noreferrer"
          className="block text-[10px] text-blue-600 underline hover:text-blue-800 dark:text-blue-400"
        >
          原典 ↗
        </a>
      )}
    </li>
  );
}
