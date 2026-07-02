"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  formatMunicipalityLabel,
  listPrefectures,
  loadMunicipalities,
  searchMunicipalities,
  type Municipality,
  NATIONAL_DIET,
} from "@/lib/municipalities";
import {
  DEMO_PERSONA,
  loadPersona,
  savePersona,
  type Persona,
} from "@/lib/persona";
import { RECOMMENDED_MUNICIPALITIES } from "@/lib/recommended";
import { cn } from "@/lib/utils";

const MAX_SELECTIONS = 5;

type State =
  | { kind: "loading" }
  | { kind: "ready"; all: Municipality[]; persona: Persona };

export default function MunicipalitiesPage() {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [selected, setSelected] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [prefectureFilter, setPrefectureFilter] = useState<string>("");
  const [tierFilter, setTierFilter] = useState<1 | 2 | 3 | "all">("all");
  const [activeOnly, setActiveOnly] = useState(false);

  useEffect(() => {
    const persona = loadPersona() ?? DEMO_PERSONA;
    loadMunicipalities()
      .then((all) => {
        setState({ kind: "ready", all, persona });
        setSelected(persona.municipality_codes ?? []);
      })
      .catch((err) => {
        console.error("failed to load municipalities", err);
      });
  }, []);

  const prefectures = useMemo(() => {
    if (state.kind !== "ready") return [];
    return listPrefectures(state.all);
  }, [state]);

  const results = useMemo(() => {
    if (state.kind !== "ready") return [];
    const found = searchMunicipalities(state.all, query, {
      tier: tierFilter === "all" ? undefined : tierFilter,
      prefecture: prefectureFilter || undefined,
      limit: 100,
    });
    return activeOnly ? found.filter((m) => m.is_active) : found;
  }, [state, query, prefectureFilter, tierFilter, activeOnly]);

  const selectedDetails = useMemo(() => {
    if (state.kind !== "ready") return [];
    return selected
      .map((code) => state.all.find((m) => m.code === code))
      .filter((m): m is Municipality => Boolean(m));
  }, [state, selected]);

  function toggleCode(code: string) {
    setSelected((prev) => {
      if (prev.includes(code)) {
        return prev.filter((c) => c !== code);
      }
      if (prev.length >= MAX_SELECTIONS) return prev; // 上限超え時は無視
      return [...prev, code];
    });
  }

  function handleSave() {
    if (state.kind !== "ready") return;
    // 国会 (00000) は常に含める (デモで国会データが多いため)
    const finalCodes = selected.includes(NATIONAL_DIET.code)
      ? selected
      : [...selected, NATIONAL_DIET.code];

    const updated: Persona = {
      ...state.persona,
      municipality_codes: finalCodes.slice(0, MAX_SELECTIONS + 1),
    };
    savePersona(updated);
    router.push("/feed");
  }

  if (state.kind === "loading") {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">自治体マスタを読み込み中...</p>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col px-6 pb-24 pt-6 sm:px-10 sm:py-10">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        {/* Top nav */}
        <div className="flex items-center justify-between text-sm">
          <Link
            href="/feed"
            className="text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← フィードに戻る
          </Link>
          <span className="text-xs text-zinc-500">
            登録済み {selectedDetails.length} / {MAX_SELECTIONS}
          </span>
        </div>

        <header className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">
            マイ自治体登録
          </h1>
          <p className="text-sm text-zinc-600 dark:text-zinc-400">
            気になる自治体を最大 {MAX_SELECTIONS} 件登録できます。国会 (🏛️)
            は自動で含まれます。
          </p>
        </header>

        {/* 選択中チップ */}
        {selectedDetails.length > 0 && (
          <section className="space-y-2 rounded-2xl border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950">
            <h2 className="text-xs font-semibold text-emerald-700 dark:text-emerald-300">
              選択中
            </h2>
            <div className="flex flex-wrap gap-2">
              {selectedDetails.map((m) => (
                <button
                  key={m.code}
                  type="button"
                  onClick={() => toggleCode(m.code)}
                  className="inline-flex items-center gap-1 rounded-full bg-emerald-600 px-3 py-1 text-sm font-medium text-emerald-50 transition-colors hover:bg-emerald-700"
                >
                  {formatMunicipalityLabel(m)}
                  <span className="text-emerald-200">×</span>
                </button>
              ))}
            </div>
          </section>
        )}

        {/* フィルタ */}
        <section className="space-y-3">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="自治体名・読み仮名・コード で検索 (例: 新宿、シブヤ、33000)"
            className="w-full rounded-2xl border border-zinc-300 bg-white px-4 py-3 text-base outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
          <div className="flex flex-wrap gap-2">
            <select
              value={prefectureFilter}
              onChange={(e) => setPrefectureFilter(e.target.value)}
              className="rounded-full border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            >
              <option value="">全都道府県</option>
              {prefectures.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            <div className="flex gap-1">
              {(["all", 1, 2, 3] as const).map((t) => (
                <button
                  key={String(t)}
                  type="button"
                  onClick={() => setTierFilter(t)}
                  className={cn(
                    "rounded-full px-3 py-2 text-xs font-medium transition-colors",
                    tierFilter === t
                      ? "bg-zinc-900 text-zinc-50 dark:bg-zinc-100 dark:text-zinc-900"
                      : "border border-zinc-300 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400",
                  )}
                >
                  {t === "all" ? "全 Tier" : `Tier ${t}`}
                </button>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setActiveOnly((prev) => !prev)}
              className={cn(
                "rounded-full px-3 py-2 text-xs font-medium transition-colors",
                activeOnly
                  ? "bg-zinc-900 text-zinc-50 dark:bg-zinc-100 dark:text-zinc-900"
                  : "border border-zinc-300 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400",
              )}
              aria-pressed={activeOnly}
            >
              📡 配信中のみ
            </button>
          </div>
          <p className="text-xs text-zinc-500">
            該当 {results.length} 件 (最大 100 件表示)
          </p>
        </section>

        {/* おすすめ (未検索時のみ) */}
        {query.trim() === "" && !prefectureFilter && (
          <section className="space-y-2">
            <h2 className="text-xs font-semibold text-zinc-500">
              おすすめ (議題データが豊富な街)
            </h2>
            <div className="flex flex-wrap gap-2">
              {RECOMMENDED_MUNICIPALITIES.map((m) => {
                const isSelected = selected.includes(m.code);
                const isFull = selected.length >= MAX_SELECTIONS && !isSelected;
                return (
                  <button
                    key={m.code}
                    type="button"
                    onClick={() => toggleCode(m.code)}
                    disabled={isFull}
                    className={cn(
                      "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                      isSelected
                        ? "border-emerald-500 bg-emerald-600 text-emerald-50 hover:bg-emerald-700"
                        : "border-zinc-300 bg-white text-zinc-600 hover:border-zinc-400 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400 dark:hover:border-zinc-600",
                      isFull && "opacity-40 cursor-not-allowed",
                    )}
                  >
                    {m.name}
                  </button>
                );
              })}
            </div>
          </section>
        )}

        {/* 検索結果リスト */}
        <section className="space-y-2">
          {results.length === 0 ? (
            <p className="rounded-2xl border border-dashed border-zinc-300 p-6 text-center text-sm text-zinc-500 dark:border-zinc-700">
              該当する自治体が見つかりません
            </p>
          ) : (
            <ul className="space-y-1">
              {results.map((m) => {
                const isSelected = selected.includes(m.code);
                const isFull = selected.length >= MAX_SELECTIONS && !isSelected;
                return (
                  <li key={m.code}>
                    <button
                      type="button"
                      onClick={() => toggleCode(m.code)}
                      disabled={isFull}
                      className={cn(
                        "flex w-full items-center justify-between gap-3 rounded-xl border px-4 py-3 text-left transition-colors",
                        isSelected
                          ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950"
                          : "border-zinc-200 bg-white hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-600",
                        isFull && "opacity-40 cursor-not-allowed",
                      )}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-medium">
                          {formatMunicipalityLabel(m)}
                        </div>
                        <div className="text-xs text-zinc-500">
                          {m.code} · {m.kana} · Tier {m.tier}
                          {m.is_active && " · 配信中"}
                        </div>
                      </div>
                      <span
                        className={cn(
                          "shrink-0 text-sm font-semibold",
                          isSelected
                            ? "text-emerald-600 dark:text-emerald-400"
                            : "text-zinc-400",
                        )}
                      >
                        {isSelected ? "✓ 登録済" : isFull ? "上限" : "登録する"}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        {/* 保存ボタン (固定下部) */}
        <div className="sticky bottom-0 -mx-6 border-t border-zinc-200 bg-zinc-50 px-6 py-4 dark:border-zinc-800 dark:bg-black sm:-mx-10 sm:px-10">
          <button
            type="button"
            onClick={handleSave}
            className="h-12 w-full rounded-full bg-zinc-900 text-base font-medium text-zinc-50 transition-colors hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            保存してフィードへ
          </button>
          <p className="mt-2 text-center text-[10px] text-zinc-500">
            ⚠️ 自治体マスタは 1,795 件 (国会 + 都道府県 + 23 区 + 政令市 +
            市町村)。📡 配信中バッジのある自治体 (830件) はフィード配信対応済み。
          </p>
        </div>
      </div>
    </main>
  );
}
