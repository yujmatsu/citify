"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { FeedCard } from "@/components/feed-card";
import { fetchFeed, type FeedItem } from "@/lib/api";
import { DEMO_PERSONA, loadPersona, type Persona } from "@/lib/persona";
import { RECOMMENDED_MUNICIPALITIES } from "@/lib/recommended";
import { cn } from "@/lib/utils";

type FeedScope = "my_city" | "national";

type LoadState =
  | { kind: "loading" }
  | { kind: "ok"; items: FeedItem[]; persona: Persona }
  | { kind: "empty"; persona: Persona }
  | { kind: "error"; message: string; persona: Persona };

export default function FeedPage() {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [scope, setScope] = useState<FeedScope>("my_city");

  useEffect(() => {
    const persona = loadPersona();
    if (!persona) {
      router.replace("/onboarding");
      return;
    }
    let cancelled = false;
    fetchFeed(persona.user_id, { limit: 50 })
      .then((res) => {
        if (cancelled) return;
        if (res.items.length === 0) {
          setState({ kind: "empty", persona });
        } else {
          setState({ kind: "ok", items: res.items, persona });
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setState({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
          persona,
        });
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  // マイ街 / 全国 スコープでフィルタリング
  const { displayItems, myCityCount, nationalCount } = useMemo(() => {
    if (state.kind !== "ok") {
      return { displayItems: [], myCityCount: 0, nationalCount: 0 };
    }
    const myCityCodes = new Set(state.persona.municipality_codes);
    const myCity: FeedItem[] = [];
    const national: FeedItem[] = [];
    for (const item of state.items) {
      const code = item.municipality_code ?? "";
      // 「マイ街」: ユーザー登録自治体 (00000 国会も含む) と一致
      // 「全国」: それ以外 = 自分の街にないが採点されたもの
      if (myCityCodes.has(code)) {
        myCity.push(item);
      } else {
        national.push(item);
      }
    }
    return {
      displayItems: scope === "my_city" ? myCity : national,
      myCityCount: myCity.length,
      nationalCount: national.length,
    };
  }, [state, scope]);

  if (state.kind === "loading") {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">フィードを読み込み中...</p>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">
            フィードの取得に失敗しました
          </h1>
          <p className="text-sm text-zinc-500">{state.message}</p>
          <p className="text-xs text-zinc-400">
            user_id: {state.persona.user_id} · API_BASE:{" "}
            {process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8080"}
          </p>
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

  if (state.kind === "empty") {
    const isDemo = state.persona.user_id === DEMO_PERSONA.user_id;
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">まだ議題が届いていません</h1>
          <p className="text-sm text-zinc-500">
            user_id: <span className="font-mono">{state.persona.user_id}</span>
            {isDemo
              ? " — デモ用ペルソナですが、まだスコア対象が無いようです。"
              : " — このペルソナでは未だ採点された議題がありません。"}
          </p>
          <p className="text-xs text-zinc-400">
            scrapers から publish → translator/relevance/bq_sink
            が処理すると、ここに表示されます。
          </p>
          <div className="flex justify-center gap-3 pt-2">
            <Link
              href="/municipalities"
              className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              マイ自治体を編集
            </Link>
            <Link
              href="/"
              className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-sm font-medium hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              トップに戻る
            </Link>
          </div>
        </div>
      </main>
    );
  }

  // OK: For You feed (snap-scroll vertical) + マイ街/全国 タブ
  return (
    <main className="flex flex-1 flex-col">
      {/* Top tab bar (sticky) */}
      <div className="sticky top-0 z-10 border-b border-zinc-200 bg-white/95 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
        <div className="mx-auto flex max-w-md items-center justify-around">
          <TabButton
            active={scope === "my_city"}
            onClick={() => setScope("my_city")}
            label="あなたの街"
            count={myCityCount}
          />
          <TabButton
            active={scope === "national"}
            onClick={() => setScope("national")}
            label="その他"
            count={nationalCount}
          />
        </div>
      </div>

      <div
        className="flex-1 snap-y snap-mandatory overflow-y-auto"
        style={{ scrollbarWidth: "none" }}
      >
        <div className="mx-auto flex max-w-md flex-col gap-4 sm:py-4">
          {displayItems.length === 0 ? (
            <EmptyTabHint scope={scope} persona={state.persona} />
          ) : (
            displayItems.map((item) => (
              <FeedCard key={item.speech_id} item={item} />
            ))
          )}
          <footer className="snap-end px-6 py-12 text-center text-xs text-zinc-500">
            <p>
              {scope === "my_city" ? "あなたの街" : "その他"} は{" "}
              {displayItems.length} 件
            </p>
            <p className="mt-3 flex flex-wrap justify-center gap-4">
              <Link
                href="/compare"
                className="font-medium text-emerald-700 underline hover:text-emerald-900 dark:text-emerald-300 dark:hover:text-emerald-200"
              >
                🔀 自治体を比較する
              </Link>
              <Link
                href="/municipalities"
                className="underline hover:text-zinc-700 dark:hover:text-zinc-300"
              >
                マイ自治体を編集
              </Link>
              <Link
                href="/onboarding"
                className="underline hover:text-zinc-700 dark:hover:text-zinc-300"
              >
                年代・関心軸を変更
              </Link>
            </p>
          </footer>
        </div>
      </div>
    </main>
  );
}

function TabButton({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}): React.JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-1 items-center justify-center gap-2 border-b-2 px-4 py-3 text-sm transition-colors",
        active
          ? "border-emerald-500 font-semibold text-emerald-700 dark:text-emerald-300"
          : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200",
      )}
      aria-pressed={active}
    >
      <span>{label}</span>
      <span
        className={cn(
          "rounded-full px-2 py-0.5 text-[10px] font-medium tabular-nums",
          active
            ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200"
            : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
        )}
      >
        {count}
      </span>
    </button>
  );
}

function EmptyTabHint({
  scope,
  persona,
}: {
  scope: FeedScope;
  persona: Persona;
}): React.JSX.Element {
  if (scope === "my_city") {
    return (
      <div className="mx-4 my-12 space-y-3 rounded-2xl border border-zinc-200 bg-zinc-50 p-6 text-center dark:border-zinc-800 dark:bg-zinc-900">
        <p className="text-sm font-medium">
          あなたの街にはまだ議題がありません
        </p>
        <p className="text-xs text-zinc-500">
          登録自治体: {persona.municipality_codes.join(" / ")}
        </p>
        <p className="text-xs text-zinc-400">
          別の街を登録するか、「その他」タブを見てみてください。
        </p>
        <p className="flex flex-wrap items-center justify-center gap-2 text-xs text-zinc-400">
          <span>例:</span>
          {RECOMMENDED_MUNICIPALITIES.map((m) => (
            <Link
              key={m.code}
              href={`/cities/${m.code}`}
              className="rounded-full border border-zinc-300 px-2 py-0.5 text-zinc-600 hover:bg-white dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              {m.name}
            </Link>
          ))}
        </p>
        <Link
          href="/municipalities"
          className="inline-flex items-center justify-center rounded-full border border-zinc-300 px-4 py-2 text-xs font-medium hover:bg-white dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          マイ自治体を編集
        </Link>
      </div>
    );
  }
  return (
    <div className="mx-4 my-12 rounded-2xl border border-zinc-200 bg-zinc-50 p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
      その他の自治体の議題はまだありません
    </div>
  );
}
