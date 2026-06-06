"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  formatMunicipalityLabel,
  loadMunicipalities,
  searchMunicipalities,
  type Municipality,
} from "@/lib/municipalities";
import {
  AGE_GROUPS,
  INTERESTS,
  type AgeGroup,
  type Interest,
  type Persona,
  savePersona,
} from "@/lib/persona";
import { putWatchlist } from "@/lib/api";
import { cn } from "@/lib/utils";

const AGE_LABEL: Record<AgeGroup, string> = {
  "18-24": "18-24 歳",
  "25-29": "25-29 歳",
  "30-39": "30-39 歳",
  "40-49": "40-49 歳",
  "50+": "50 歳以上",
};

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

const MAX_WATCHED = 4;
type TownMode = "home" | "watched";

export default function OnboardingPage(): React.JSX.Element {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [ageGroup, setAgeGroup] = useState<AgeGroup | null>(null);
  const [interests, setInterests] = useState<Set<Interest>>(new Set());

  // step3: 街選択
  const [munis, setMunis] = useState<Municipality[]>([]);
  const [homeSel, setHomeSel] = useState<string | null>(null);
  const [watched, setWatched] = useState<string[]>([]);
  const [townMode, setTownMode] = useState<TownMode>("home");
  const [query, setQuery] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadMunicipalities()
      .then(setMunis)
      .catch((err) => console.error("failed to load municipalities", err));
  }, []);

  const results = useMemo(() => {
    if (munis.length === 0) return [];
    return searchMunicipalities(munis, query, { limit: 60 });
  }, [munis, query]);

  const nameOf = (code: string): string =>
    munis.find((m) => m.code === code)?.name ?? `自治体 ${code}`;

  function toggleInterest(i: Interest) {
    setInterests((prev) => {
      const next = new Set(prev);
      if (next.has(i)) next.delete(i);
      else next.add(i);
      return next;
    });
  }

  function pickTown(code: string) {
    if (townMode === "home") {
      setHomeSel(code);
      // 気になる街に同じ街があれば除去
      setWatched((prev) => prev.filter((c) => c !== code));
      setTownMode("watched");
      setQuery("");
      return;
    }
    if (code === homeSel) return; // 住む街と重複させない
    setWatched((prev) => {
      if (prev.includes(code)) return prev.filter((c) => c !== code);
      if (prev.length >= MAX_WATCHED) return prev;
      return [...prev, code];
    });
  }

  async function handleFinish() {
    if (!ageGroup || !homeSel) return;
    const userId = `demo-${ageGroup}`;
    const interestList = Array.from(interests);
    const persona: Persona = {
      user_id: userId,
      age_group: ageGroup,
      interests: interestList,
      // [住む街, ...気になる街] 順 (persona.homeCode/watchedCodes が解釈)
      municipality_codes: [homeSel, ...watched],
    };
    savePersona(persona);
    // ウォッチ街を backend にも保存 (best-effort、失敗してもホームへ)
    setSaving(true);
    try {
      await putWatchlist(userId, {
        age_group: ageGroup,
        interests: interestList,
        home_municipality_code: homeSel,
        watched_codes: watched,
      });
    } catch (err) {
      console.error("watchlist sync failed (続行)", err);
    } finally {
      setSaving(false);
      router.push("/agent");
    }
  }

  return (
    <main className="flex flex-1 flex-col items-center px-6 pt-16 pb-12">
      <div className="w-full max-w-md space-y-10">
        {/* Step indicator */}
        <div className="flex items-center justify-center gap-3 text-xs text-zinc-500">
          <StepLabel active={step >= 1} text="1. 年代" />
          <span>—</span>
          <StepLabel active={step >= 2} text="2. 関心軸" />
          <span>—</span>
          <StepLabel active={step >= 3} text="3. 街" />
        </div>

        {step === 1 && (
          <section className="space-y-6">
            <header className="space-y-2 text-center">
              <h1 className="text-2xl font-semibold tracking-tight">
                あなたの年代は？
              </h1>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                年代に合わせた言葉遣いでお届けします
              </p>
            </header>
            <div className="grid grid-cols-2 gap-3">
              {AGE_GROUPS.map((ag) => (
                <button
                  key={ag}
                  type="button"
                  onClick={() => setAgeGroup(ag)}
                  className={cn(
                    "rounded-2xl border px-4 py-5 text-base font-medium transition-colors",
                    "hover:border-zinc-900 dark:hover:border-zinc-300",
                    ageGroup === ag
                      ? "border-zinc-900 bg-zinc-900 text-zinc-50 dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                      : "border-zinc-300 bg-white text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100",
                  )}
                >
                  {AGE_LABEL[ag]}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => ageGroup && setStep(2)}
              disabled={!ageGroup}
              className={cn(
                "h-12 w-full rounded-full text-base font-medium transition-colors",
                ageGroup
                  ? "bg-zinc-900 text-zinc-50 hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
                  : "bg-zinc-200 text-zinc-400 cursor-not-allowed dark:bg-zinc-800 dark:text-zinc-600",
              )}
            >
              次へ
            </button>
          </section>
        )}

        {step === 2 && (
          <section className="space-y-6">
            <header className="space-y-2 text-center">
              <h1 className="text-2xl font-semibold tracking-tight">
                気になるトピックは？
              </h1>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                複数選択 OK・あとから変更可能です ({interests.size} 個選択中)
              </p>
            </header>
            <div className="grid grid-cols-2 gap-3">
              {INTERESTS.map((i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => toggleInterest(i)}
                  className={cn(
                    "flex items-center gap-2 rounded-2xl border px-4 py-4 text-base font-medium transition-colors",
                    interests.has(i)
                      ? "border-zinc-900 bg-zinc-900 text-zinc-50 dark:border-zinc-100 dark:bg-zinc-100 dark:text-zinc-900"
                      : "border-zinc-300 bg-white text-zinc-900 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100",
                  )}
                >
                  <span aria-hidden>{INTEREST_EMOJI[i]}</span>
                  <span>{i}</span>
                </button>
              ))}
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setStep(1)}
                className="h-12 flex-1 rounded-full border border-zinc-300 bg-transparent text-base font-medium transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
              >
                戻る
              </button>
              <button
                type="button"
                onClick={() => setStep(3)}
                className="h-12 flex-1 rounded-full bg-zinc-900 text-base font-medium text-zinc-50 transition-colors hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
              >
                次へ
              </button>
            </div>
          </section>
        )}

        {step === 3 && (
          <section className="space-y-5">
            <header className="space-y-2 text-center">
              <h1 className="text-2xl font-semibold tracking-tight">
                どの街を見張る？
              </h1>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">
                住む街を 1 つ、気になる街を最大 {MAX_WATCHED} つ。エージェントが
                ここを調べます。
              </p>
            </header>

            {/* 選択状況 */}
            <div className="space-y-2 rounded-2xl border border-emerald-200 bg-emerald-50 p-3 text-sm dark:border-emerald-900 dark:bg-emerald-950">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                  🏠 住む街
                </span>
                <span>{homeSel ? nameOf(homeSel) : "未選択"}</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                  ⭐ 気になる街
                </span>
                {watched.length === 0 ? (
                  <span className="text-zinc-500">なし</span>
                ) : (
                  watched.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() => pickTown(c)}
                      className="inline-flex items-center gap-1 rounded-full bg-emerald-600 px-2.5 py-0.5 text-xs font-medium text-white"
                    >
                      {nameOf(c)} <span className="text-emerald-200">×</span>
                    </button>
                  ))
                )}
              </div>
            </div>

            {/* モード切替 */}
            <div className="flex gap-1">
              {(
                [
                  ["home", "住む街を選ぶ"],
                  [
                    "watched",
                    `気になる街を追加 (${watched.length}/${MAX_WATCHED})`,
                  ],
                ] as const
              ).map(([m, label]) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setTownMode(m)}
                  className={cn(
                    "flex-1 rounded-full px-3 py-2 text-xs font-medium transition-colors",
                    townMode === m
                      ? "bg-zinc-900 text-zinc-50 dark:bg-zinc-100 dark:text-zinc-900"
                      : "border border-zinc-300 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="街名・読み仮名・コードで検索 (例: 新宿、シブヤ、33000)"
              className="w-full rounded-2xl border border-zinc-300 bg-white px-4 py-3 text-base outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
            />

            <ul className="max-h-64 space-y-1 overflow-y-auto">
              {results.map((m) => {
                const isHome = m.code === homeSel;
                const isWatched = watched.includes(m.code);
                const selected = townMode === "home" ? isHome : isWatched;
                return (
                  <li key={m.code}>
                    <button
                      type="button"
                      onClick={() => pickTown(m.code)}
                      className={cn(
                        "flex w-full items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-colors",
                        selected
                          ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950"
                          : "border-zinc-200 bg-white hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-600",
                      )}
                    >
                      <span className="min-w-0 flex-1">
                        <span className="font-medium">
                          {formatMunicipalityLabel(m)}
                        </span>
                        <span className="block text-xs text-zinc-500">
                          {m.code} · {m.kana}
                        </span>
                      </span>
                      <span className="shrink-0 text-xs font-semibold text-zinc-400">
                        {isHome ? "🏠 住む街" : isWatched ? "✓ 追加済" : ""}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>

            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setStep(2)}
                className="h-12 flex-1 rounded-full border border-zinc-300 bg-transparent text-base font-medium transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
              >
                戻る
              </button>
              <button
                type="button"
                onClick={handleFinish}
                disabled={!homeSel || saving}
                className={cn(
                  "h-12 flex-1 rounded-full text-base font-medium transition-colors",
                  homeSel && !saving
                    ? "bg-emerald-600 text-white hover:bg-emerald-700"
                    : "bg-zinc-200 text-zinc-400 cursor-not-allowed dark:bg-zinc-800 dark:text-zinc-600",
                )}
              >
                {saving ? "保存中..." : "エージェントを始める"}
              </button>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

function StepLabel({
  active,
  text,
}: {
  active: boolean;
  text: string;
}): React.JSX.Element {
  return (
    <span
      className={cn(
        active ? "font-semibold text-zinc-900 dark:text-zinc-100" : "",
      )}
    >
      {text}
    </span>
  );
}
