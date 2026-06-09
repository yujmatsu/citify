"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { putWatchlist } from "@/lib/api";
import { loadPersona, type Persona, savePersona } from "@/lib/persona";
import { PRESET_PERSONAS, type PresetPersona } from "@/lib/presets";

export default function Home() {
  const router = useRouter();
  const [persona, setPersona] = useState<Persona | null | undefined>(undefined);
  const [applying, setApplying] = useState<string | null>(null);

  useEffect(() => {
    setPersona(loadPersona());
  }, []);

  // プリセット適用: persona 保存 + watchlist 同期(best-effort) → /agent で即体験
  async function applyPreset(p: PresetPersona) {
    setApplying(p.id);
    savePersona(p.persona);
    try {
      await putWatchlist(p.persona.user_id, {
        age_group: p.persona.age_group,
        interests: p.persona.interests,
        home_municipality_code: p.persona.municipality_codes[0],
        watched_codes: p.persona.municipality_codes.slice(1),
        priorities: p.persona.priorities,
        household: p.persona.household ?? "",
        budget_man: p.persona.budget_man,
        free_form_context: p.persona.free_form_context,
      });
    } catch (err) {
      console.error("preset watchlist sync failed (続行)", err);
    } finally {
      router.push("/agent");
    }
  }

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
        <div className="space-y-2">
          <h1 className="text-4xl font-bold tracking-tight">Citify</h1>
          <p className="text-lg font-medium text-zinc-700 dark:text-zinc-200">
            住む街、どう選ぶ？
          </p>
          <p className="text-sm text-zinc-500">
            60 秒で、あなたに合う街が見えてくる。
          </p>
        </div>
        <div className="space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
          <p>
            あなたの優先順位で、全国の街を客観データと AI
            が比較。「住み続けるか・どこへ移るか」の答えを一緒に出します。
          </p>
          <p className="text-xs text-zinc-500">
            議事録から街が「いま何に投資しているか（＝5 年後の暮らし）」まで見えるのは
            Citify だけ。
          </p>
        </div>
        {persona ? (
          <div className="space-y-3">
            <p className="text-sm text-zinc-500">
              {persona.user_id} ({persona.age_group}) として続行
            </p>
            {/* 主役は1つ: アドバイザー(エージェント)に相談する */}
            <div className="space-y-1.5">
              <Link
                href="/agent"
                className="inline-flex h-12 w-full items-center justify-center gap-2 rounded-full bg-emerald-600 px-6 text-base font-medium text-white transition-colors hover:bg-emerald-700"
              >
                🤖 マイ街エージェントに相談
              </Link>
              <p className="text-xs text-zinc-500">
                あなたの街と候補を比べて「住み続ける／どこへ移るか」を提案します
              </p>
            </div>
            <div className="space-y-4 pt-3 text-left">
              <LinkGroup
                title="街を選ぶ"
                links={[
                  {
                    href: "/concierge",
                    label: "💬 質問して街を診断",
                    hint: "気になることをピンポイントで聞く",
                  },
                  { href: "/municipalities", label: "🏙️ 気になる街を探す・登録" },
                  { href: "/compare", label: "🔀 2つの街を見比べる" },
                  { href: "/heatmap", label: "🗾 全国から条件で探す" },
                ]}
              />
              <LinkGroup
                title="街の動きを知る"
                links={[
                  { href: "/feed", label: "📰 議題フィードを眺める" },
                  { href: "/timeline", label: "🕰 議論の流れを追う" },
                  { href: "/forecast", label: "📈 街の勢い・将来予測" },
                ]}
              />
              <div className="space-y-1 border-t border-zinc-200 pt-3 dark:border-zinc-800">
                <Link
                  href="/onboarding"
                  className="block text-sm text-zinc-500 transition-colors hover:text-zinc-700 dark:hover:text-zinc-300"
                >
                  ⚙️ 設定（年代・関心・街）
                </Link>
                <Link
                  href="/admin"
                  className="block text-xs text-zinc-400 transition-colors hover:text-zinc-600 dark:hover:text-zinc-400"
                >
                  開発者向け →
                </Link>
              </div>
            </div>
          </div>
        ) : (
          <div className="space-y-3 text-left">
            <p className="text-center text-sm font-medium text-zinc-600 dark:text-zinc-400">
              ひとつ選ぶと、設定なしで今すぐ試せます
            </p>
            {PRESET_PERSONAS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => applyPreset(p)}
                disabled={applying !== null}
                className="block w-full rounded-2xl border border-zinc-300 bg-white p-4 text-left transition-colors hover:border-emerald-400 hover:bg-emerald-50/40 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900 dark:hover:border-emerald-700 dark:hover:bg-emerald-950/30"
              >
                <div className="flex items-center gap-2">
                  <span aria-hidden className="text-lg">
                    {p.emoji}
                  </span>
                  <span className="font-semibold">{p.label}</span>
                </div>
                <p className="mt-0.5 text-xs text-zinc-500">
                  {applying === p.id ? "準備中…" : p.description}
                </p>
              </button>
            ))}
            <Link
              href="/onboarding"
              className="block pt-1 text-center text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
            >
              自分で設定する（年代・関心・街を入力）→
            </Link>
          </div>
        )}
      </div>
    </main>
  );
}

function LinkGroup({
  title,
  links,
}: {
  title: string;
  links: { href: string; label: string; hint?: string }[];
}): React.JSX.Element {
  return (
    <div className="space-y-1">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-zinc-400">
        {title}
      </p>
      <div>
        {links.map((l) => (
          <Link
            key={l.href}
            href={l.href}
            className="-mx-2 block rounded-lg px-2 py-1.5 transition-colors hover:bg-zinc-100 dark:hover:bg-zinc-900"
          >
            <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
              {l.label}
            </span>
            {l.hint ? (
              <span className="block text-[11px] text-zinc-400">{l.hint}</span>
            ) : null}
          </Link>
        ))}
      </div>
    </div>
  );
}
