"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { loadPersona, type Persona } from "@/lib/persona";

export default function Home() {
  const [persona, setPersona] = useState<Persona | null | undefined>(undefined);

  useEffect(() => {
    setPersona(loadPersona());
  }, []);

  // SSR / 初期 hydration 中はスケルトン
  if (persona === undefined) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">読み込み中...</p>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col items-center justify-center px-8 py-16">
      <div className="max-w-md text-center space-y-8">
        <div className="space-y-3">
          <h1 className="text-4xl font-bold tracking-tight">Citify</h1>
          <p className="text-lg text-zinc-600 dark:text-zinc-400">
            自分の街、自分の世代の話を、60 秒で。
          </p>
        </div>
        <div className="space-y-3 text-sm text-zinc-700 dark:text-zinc-300">
          <p>
            自治体議事録を若者向けに翻訳して TikTok
            風フィードで配信する、マルチエージェント AI プロダクトです。
          </p>
        </div>
        {persona ? (
          <div className="space-y-3">
            <p className="text-sm text-zinc-500">
              {persona.user_id} ({persona.age_group}) として続行
            </p>
            <Link
              href="/feed"
              className="inline-flex h-12 w-full items-center justify-center rounded-full bg-zinc-900 px-6 text-base font-medium text-zinc-50 transition-colors hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
            >
              フィードを見る
            </Link>
            <div className="flex flex-wrap justify-center gap-4 text-sm text-zinc-500">
              <Link
                href="/compare"
                className="font-medium text-emerald-700 underline hover:text-emerald-900 dark:text-emerald-300 dark:hover:text-emerald-200"
              >
                🔀 比較ビュー
              </Link>
              <Link
                href="/municipalities"
                className="underline hover:text-zinc-700 dark:hover:text-zinc-300"
              >
                マイ自治体
              </Link>
              <Link
                href="/onboarding"
                className="underline hover:text-zinc-700 dark:hover:text-zinc-300"
              >
                ペルソナを変更
              </Link>
            </div>
          </div>
        ) : (
          <Link
            href="/onboarding"
            className="inline-flex h-12 w-full items-center justify-center rounded-full bg-zinc-900 px-6 text-base font-medium text-zinc-50 transition-colors hover:bg-zinc-800 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-200"
          >
            はじめる
          </Link>
        )}
      </div>
    </main>
  );
}
