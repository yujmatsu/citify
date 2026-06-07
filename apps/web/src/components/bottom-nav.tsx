"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type React from "react";
import { cn } from "@/lib/utils";

const TABS = [
  { href: "/agent", label: "エージェント", emoji: "🤖" },
  { href: "/feed", label: "フィード", emoji: "📰" },
  { href: "/municipalities", label: "街さがし", emoji: "🏙️" },
  { href: "/onboarding", label: "設定", emoji: "⚙️" },
];

/**
 * 共通ボトムナビ (設計B B1)。主要4面への動線を統一。
 * 没入レイアウトの /feed と、フロー中の /onboarding では非表示にして邪魔しない。
 */
export function BottomNav(): React.JSX.Element | null {
  const path = usePathname() || "/";
  if (
    path.startsWith("/feed") ||
    path.startsWith("/onboarding") ||
    path === "/"
  ) {
    return null;
  }
  return (
    <nav className="sticky bottom-0 z-20 border-t border-zinc-200 bg-white/95 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/95">
      <div className="mx-auto flex max-w-md items-center justify-around">
        {TABS.map((t) => {
          const active = path === t.href || path.startsWith(`${t.href}/`);
          return (
            <Link
              key={t.href}
              href={t.href}
              className={cn(
                "flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] transition-colors",
                active
                  ? "font-semibold text-emerald-600 dark:text-emerald-400"
                  : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200",
              )}
              aria-current={active ? "page" : undefined}
            >
              <span className="text-lg" aria-hidden>
                {t.emoji}
              </span>
              {t.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
