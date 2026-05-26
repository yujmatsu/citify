"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { FeedCard } from "@/components/feed-card";
import { fetchCityDashboard, type CityDashboardResponse } from "@/lib/api";
import { interestImageUrl } from "@/lib/interest-images";
import { loadPersona, type Persona } from "@/lib/persona";
import { cn } from "@/lib/utils";

const INTEREST_EMOJI: Record<string, string> = {
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
  | { kind: "loading" }
  | { kind: "ok"; data: CityDashboardResponse; persona: Persona }
  | { kind: "error"; message: string };

export default function CityDashboardPage() {
  const params = useParams<{ code: string }>();
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const persona = loadPersona();
    if (!persona) {
      router.replace("/onboarding");
      return;
    }
    const code = decodeURIComponent(params.code);
    let cancelled = false;
    fetchCityDashboard(persona.user_id, code, 10)
      .then((data) => {
        if (cancelled) return;
        setState({ kind: "ok", data, persona });
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
  }, [params.code, router]);

  if (state.kind === "loading") {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">街の情報を読み込み中...</p>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">街の情報が取得できません</h1>
          <p className="text-sm text-zinc-500">{state.message}</p>
          <Link
            href="/feed"
            className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
          >
            フィードに戻る
          </Link>
        </div>
      </main>
    );
  }

  return <CityDashboardView data={state.data} persona={state.persona} />;
}

function CityDashboardView({
  data,
  persona,
}: {
  data: CityDashboardResponse;
  persona: Persona;
}): React.JSX.Element {
  const isRegistered = persona.municipality_codes.includes(
    data.municipality_code,
  );

  // 関心軸別カウントを件数順にソート
  const sortedInterests = useMemo(() => {
    return Object.entries(data.interest_counts).sort((a, b) => b[1] - a[1]);
  }, [data.interest_counts]);

  return (
    <main className="flex flex-1 flex-col px-6 pb-24 pt-6 sm:px-10 sm:py-10">
      <div className="mx-auto w-full max-w-2xl space-y-8">
        {/* Top nav */}
        <div className="flex items-center justify-between">
          <Link
            href="/feed"
            className="text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← フィードに戻る
          </Link>
          {isRegistered ? (
            <span className="rounded-full bg-emerald-100 px-3 py-1 text-[10px] font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
              ✓ マイ自治体
            </span>
          ) : (
            <Link
              href="/municipalities"
              className="text-xs text-zinc-500 underline hover:text-zinc-700"
            >
              + マイ自治体に追加
            </Link>
          )}
        </div>

        {/* ヘッダー */}
        <header className="space-y-2">
          <p className="text-sm text-zinc-500">
            あなたの街、今こうなっています
          </p>
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            🏙️ {data.municipality_name}
          </h1>
          <p className="text-sm text-zinc-500">
            あなた ({persona.user_id}) 向けに採点された議題:{" "}
            <span className="font-semibold text-zinc-800 dark:text-zinc-200">
              {data.total_speeches} 件
            </span>
          </p>
        </header>

        {/* 関心軸別カウント */}
        {sortedInterests.length > 0 && (
          <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-sm font-semibold text-zinc-500">
              📊 関心軸別の議題数
            </h2>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {sortedInterests.map(([interest, count]) => {
                const img = interestImageUrl(interest);
                return (
                  <div
                    key={interest}
                    className={cn(
                      "relative flex items-center justify-between gap-2 overflow-hidden rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2 dark:border-zinc-700 dark:bg-zinc-800",
                      count >= 3 &&
                        "border-emerald-300 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950",
                    )}
                  >
                    <div className="flex items-center gap-2">
                      {img ? (
                        <span
                          className="h-7 w-7 flex-shrink-0 rounded-md bg-cover bg-center"
                          style={{ backgroundImage: `url(${img})` }}
                          aria-hidden="true"
                        />
                      ) : (
                        <span className="text-base">
                          {INTEREST_EMOJI[interest] ?? "📌"}
                        </span>
                      )}
                      <span className="text-sm">{interest}</span>
                    </div>
                    <span className="text-sm font-semibold tabular-nums">
                      {count}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* CTA: 比較ビュー */}
        {isRegistered &&
          persona.municipality_codes.filter((c) => c !== "00000").length >=
            2 && (
            <Link
              href="/compare"
              className="block rounded-2xl border border-emerald-300 bg-emerald-50 p-4 text-center text-sm font-semibold text-emerald-800 transition-colors hover:bg-emerald-100 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-200 dark:hover:bg-emerald-900"
            >
              🔀 他の街と比較してみる →
            </Link>
          )}

        {/* 注目の議題 */}
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-zinc-500">
            🔥 注目の議題 (関連度順)
          </h2>
          {data.top_speeches.length === 0 ? (
            <div className="rounded-2xl border border-zinc-200 bg-zinc-50 p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
              <p>まだ議題が届いていません</p>
              <p className="mt-2 text-xs text-zinc-400">
                press_rss / 議事録 から publish → AI
                採点が完了すると表示されます
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {data.top_speeches.map((item) => (
                <FeedCard key={item.speech_id} item={item} />
              ))}
            </div>
          )}
        </section>

        {/* 倫理表記 */}
        <p className="pb-8 text-center text-[10px] text-zinc-500">
          AI が説明用に翻訳・採点しました。投票推奨・政治的判断は含みません。
        </p>
      </div>
    </main>
  );
}
