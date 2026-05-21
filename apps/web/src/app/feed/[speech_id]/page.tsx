"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchSpeech, type FeedItem } from "@/lib/api";
import { loadPersona, type Persona } from "@/lib/persona";
import { cn } from "@/lib/utils";

const REACTIONS = ["👍", "🤔", "😢", "🔥"] as const;
type Reaction = (typeof REACTIONS)[number];

type State =
  | { kind: "loading" }
  | { kind: "ok"; item: FeedItem; persona: Persona }
  | { kind: "error"; message: string };

const MUNICIPALITY_LABEL: Record<string, string> = {
  "00000": "国会",
  "13104": "新宿区",
  "13107": "墨田区",
  "13118": "荒川区",
  "14100": "横浜市",
  "27000": "大阪府",
  "27100": "大阪市",
  "33000": "岡山県",
  "39000": "土佐市",
  "44000": "大分県",
};

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(100, (value / 25) * 100));
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-zinc-500">
        <span>{label}</span>
        <span>{value} / 25</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
        <div
          className="h-full rounded-full bg-emerald-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function SpeechDetailPage() {
  const params = useParams<{ speech_id: string }>();
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [reaction, setReaction] = useState<Reaction | null>(null);

  useEffect(() => {
    const persona = loadPersona();
    if (!persona) {
      router.replace("/onboarding");
      return;
    }
    const sid = decodeURIComponent(params.speech_id);
    let cancelled = false;
    fetchSpeech(sid, persona.user_id)
      .then((item) => {
        if (cancelled) return;
        setState({ kind: "ok", item, persona });
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
  }, [params.speech_id, router]);

  if (state.kind === "loading") {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">読み込み中...</p>
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="flex flex-1 flex-col items-center justify-center px-6 py-16">
        <div className="max-w-md space-y-4 text-center">
          <h1 className="text-xl font-semibold">議題が見つかりません</h1>
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

  const { item } = state;
  const muni =
    (item.municipality_code && MUNICIPALITY_LABEL[item.municipality_code]) ??
    item.municipality_code ??
    "—";

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
          <span className="text-xs text-zinc-500">
            {muni}
            {item.meeting_date ? ` · ${item.meeting_date}` : ""}
          </span>
        </div>

        {/* Title (翻訳タイトル) + 会議名 (正式タイトル代替) */}
        <header className="space-y-3">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            {item.title || "(タイトル未生成)"}
          </h1>
          {item.name_of_meeting && (
            <p className="text-sm text-zinc-500">
              <span className="font-medium">正式会議名:</span>{" "}
              {item.name_of_meeting}
            </p>
          )}
        </header>

        {/* Summary (3 行) */}
        <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-sm font-semibold text-zinc-500">
            かいつまんで言うと
          </h2>
          <ul className="space-y-2 text-base leading-relaxed">
            {item.summary.length > 0 ? (
              item.summary.map((line, i) => (
                <li key={i} className="flex gap-3">
                  <span className="text-zinc-400">L{i + 1}</span>
                  <span>{line}</span>
                </li>
              ))
            ) : (
              <li className="text-zinc-500">(要約未生成)</li>
            )}
          </ul>
          {item.tone && (
            <p className="pt-2 text-xs text-zinc-400">tone: {item.tone}</p>
          )}
        </section>

        {/* Score breakdown */}
        <section className="space-y-4 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-zinc-500">
              あなたへの関連度
            </h2>
            <div className="text-3xl font-bold">
              {item.relevance_score}
              <span className="text-base font-normal text-zinc-500">
                {" "}
                / 100
              </span>
            </div>
          </div>
          <div className="space-y-3">
            <ScoreBar label="トピック関連性" value={item.score_topic} />
            <ScoreBar label="年代適合性" value={item.score_age} />
            <ScoreBar label="地理関連性" value={item.score_geographic} />
            <ScoreBar label="緊急性" value={item.score_urgency} />
          </div>
          {item.matched_interests.length > 0 && (
            <div className="flex flex-wrap gap-2 pt-2">
              {item.matched_interests.map((interest) => (
                <span
                  key={interest}
                  className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-medium text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
                >
                  #{interest}
                </span>
              ))}
            </div>
          )}
          {item.reasoning && (
            <p className="border-t border-zinc-200 pt-3 text-xs text-zinc-500 dark:border-zinc-800">
              <span className="font-medium">AI 採点理由:</span> {item.reasoning}
            </p>
          )}
        </section>

        {/* RAG 検索結果 (mock - 将来 Phase D RAG Engine と統合) */}
        <section className="space-y-3 rounded-2xl border border-dashed border-zinc-300 p-6 dark:border-zinc-700">
          <h2 className="text-sm font-semibold text-zinc-500">
            関連議題 (RAG)
          </h2>
          <p className="text-xs text-zinc-400">
            🚧 Phase D RAG Engine と統合予定 (Week 4)。今は placeholder です。
          </p>
        </section>

        {/* Reactions (UI のみ、永続化は将来) */}
        <section className="space-y-3 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-sm font-semibold text-zinc-500">あなたの反応</h2>
          <div className="flex gap-3">
            {REACTIONS.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setReaction(reaction === r ? null : r)}
                className={cn(
                  "flex h-12 flex-1 items-center justify-center rounded-full border text-2xl transition-colors",
                  reaction === r
                    ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950"
                    : "border-zinc-300 hover:border-zinc-400 dark:border-zinc-700 dark:hover:border-zinc-500",
                )}
                aria-pressed={reaction === r}
              >
                {r}
              </button>
            ))}
          </div>
          {reaction && (
            <p className="text-xs text-zinc-500">
              {reaction} を選択しました (デモ用、サーバには保存していません)
            </p>
          )}
        </section>

        {/* 原典リンク (必須、PROJECT.md §5) */}
        {item.detail_url && (
          <section className="space-y-2 rounded-2xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
            <h2 className="text-sm font-semibold text-zinc-500">原典</h2>
            <a
              href={item.detail_url}
              target="_blank"
              rel="noopener noreferrer"
              className="block break-all text-sm text-blue-600 underline hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300"
            >
              {item.detail_url} ↗
            </a>
            <p className="text-xs text-zinc-400">
              ⚠️ 必ず原典で確認してください。AI
              翻訳は要約のみで、正確性は保証されません。
            </p>
          </section>
        )}

        {/* 倫理表記 */}
        <p className="pb-8 text-center text-[10px] text-zinc-500">
          AI が説明用に翻訳・採点しました。投票推奨・政治的判断は含みません。
        </p>
      </div>
    </main>
  );
}
