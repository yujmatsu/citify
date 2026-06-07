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
              href="/agent"
              className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-full bg-emerald-600 px-6 text-base font-medium text-white transition-colors hover:bg-emerald-700"
            >
              🤖 マイ街エージェント
            </Link>
            <Link
              href="/feed"
              className="inline-flex h-11 w-full items-center justify-center rounded-full border border-zinc-300 px-6 text-sm font-medium transition-colors hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900"
            >
              フィードを見る
            </Link>
            <div className="space-y-4 pt-2 text-left">
              <LinkGroup
                title="街を知る・選ぶ"
                links={[
                  { href: "/concierge", label: "💬 街診断コンシェルジュ" },
                  { href: "/municipalities", label: "🏙️ 街さがし・マイ自治体" },
                  { href: "/compare", label: "🔀 比較ビュー" },
                  { href: "/heatmap", label: "🗾 全国ヒートマップ" },
                ]}
              />
              <LinkGroup
                title="動きを見る"
                links={[
                  { href: "/timeline", label: "🕰 議論タイムライン" },
                  { href: "/forecast", label: "📈 議題件数の推移と予測" },
                ]}
              />
              <LinkGroup
                title="設定・管理"
                muted
                links={[
                  { href: "/onboarding", label: "⚙️ 年代・関心・街を変更" },
                  { href: "/admin/scrapers", label: "🩺 Scraper Health" },
                  { href: "/admin/costs", label: "💸 Cost Health" },
                ]}
              />
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

function LinkGroup({
  title,
  links,
  muted,
}: {
  title: string;
  links: { href: string; label: string }[];
  muted?: boolean;
}): React.JSX.Element {
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
        {title}
      </p>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-sm">
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className={
              muted
                ? "text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
                : "font-medium text-zinc-700 underline hover:text-zinc-900 dark:text-zinc-200"
            }
          >
            {l.label}
          </Link>
        ))}
      </div>
    </div>
  );
}
