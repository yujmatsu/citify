"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FeedCard } from "@/components/feed-card";
import { fetchFeed, type FeedItem } from "@/lib/api";
import { DEMO_PERSONA, loadPersona, type Persona } from "@/lib/persona";

type LoadState =
  | { kind: "loading" }
  | { kind: "ok"; items: FeedItem[]; persona: Persona }
  | { kind: "empty"; persona: Persona }
  | { kind: "error"; message: string; persona: Persona };

export default function FeedPage() {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    const persona = loadPersona();
    if (!persona) {
      // ペルソナ未設定なら onboarding へ
      router.replace("/onboarding");
      return;
    }
    let cancelled = false;
    fetchFeed(persona.user_id, { limit: 20 })
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

  // OK: For You feed (snap-scroll vertical)
  return (
    <main className="flex flex-1 flex-col">
      <div
        className="flex-1 snap-y snap-mandatory overflow-y-auto"
        style={{ scrollbarWidth: "none" }}
      >
        <div className="mx-auto flex max-w-md flex-col gap-4 sm:py-4">
          {state.items.map((item) => (
            <FeedCard key={item.speech_id} item={item} />
          ))}
          <footer className="snap-end px-6 py-12 text-center text-xs text-zinc-500">
            <p>これで全部 ({state.items.length} 件)</p>
            <p className="mt-3 flex justify-center gap-4">
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
