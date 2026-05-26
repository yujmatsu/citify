"use client";

import Link from "next/link";
import type { FeedItem } from "@/lib/api";
import { cn } from "@/lib/utils";

interface FeedCardProps {
  item: FeedItem;
  /** 自治体名表示用のマッピング (5 桁コード → 表示名)。未登録は code をそのまま表示。 */
  municipalityName?: Record<string, string>;
}

const MUNICIPALITY_FALLBACK: Record<string, string> = {
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

function scoreColor(score: number): string {
  if (score >= 80) return "bg-emerald-500";
  if (score >= 50) return "bg-amber-500";
  return "bg-zinc-400";
}

export function FeedCard({ item, municipalityName }: FeedCardProps) {
  const muniMap = { ...MUNICIPALITY_FALLBACK, ...(municipalityName ?? {}) };
  const muniLabel = item.municipality_code
    ? (muniMap[item.municipality_code] ?? item.municipality_code)
    : "—";

  return (
    <article
      className={cn(
        "relative flex h-full w-full snap-start snap-always flex-col justify-between",
        "px-6 py-10 sm:px-10 sm:py-12",
        "bg-gradient-to-br from-zinc-900 via-zinc-800 to-zinc-900 text-zinc-50",
        "min-h-[80vh] sm:rounded-3xl sm:shadow-2xl",
      )}
    >
      {/* Header: 自治体 + score badge */}
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-zinc-300">
          <span className="rounded-full border border-zinc-700 bg-zinc-800/60 px-3 py-1 font-medium">
            {muniLabel}
          </span>
          {item.meeting_date && (
            <span className="text-zinc-400">{item.meeting_date}</span>
          )}
        </div>
        <div
          className={cn(
            "flex h-12 w-12 items-center justify-center rounded-full text-sm font-bold text-zinc-50",
            scoreColor(item.relevance_score),
          )}
          title={`関連度 ${item.relevance_score}/100`}
        >
          {item.relevance_score}
        </div>
      </header>

      {/* Body: title + summary */}
      <div className="flex flex-1 flex-col justify-center gap-6 py-8">
        <h2 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
          {item.title || "(タイトル未生成)"}
        </h2>
        <ul className="space-y-3 text-base leading-relaxed text-zinc-200 sm:text-lg">
          {item.summary.length > 0 ? (
            item.summary.map((line, i) => (
              <li key={i} className="flex gap-3">
                <span className="text-zinc-500">L{i + 1}</span>
                <span>{line}</span>
              </li>
            ))
          ) : (
            <li className="text-zinc-500">(要約未生成)</li>
          )}
        </ul>
      </div>

      {/* Footer: matched interests + 詳細リンク */}
      <footer className="space-y-3">
        {item.matched_interests.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {item.matched_interests.map((interest) => (
              <span
                key={interest}
                className="rounded-full bg-emerald-600/20 px-3 py-1 text-xs font-medium text-emerald-300"
              >
                #{interest}
              </span>
            ))}
          </div>
        )}
        {item.speaker_position && (
          <p className="text-xs text-zinc-400">
            発言者: {item.speaker_position}
          </p>
        )}
        <div className="flex items-center justify-between gap-3 pt-2">
          <Link
            href={`/feed/${encodeURIComponent(item.speech_id)}`}
            prefetch
            className="flex-1 rounded-full bg-zinc-50 px-4 py-3 text-center text-sm font-semibold text-zinc-900 transition-colors hover:bg-zinc-200"
          >
            詳しく見る
          </Link>
          {item.detail_url && (
            <a
              href={item.detail_url}
              target="_blank"
              rel="noopener noreferrer"
              className="rounded-full border border-zinc-600 px-4 py-3 text-center text-sm font-medium text-zinc-200 transition-colors hover:bg-zinc-800"
              title="原典 (議会公式サイト) を開く"
            >
              原典 ↗
            </a>
          )}
        </div>
        <p className="pt-2 text-[10px] text-zinc-500">
          ⚠️ AI が翻訳・採点しました。投票推奨・政治的判断は含みません。
        </p>
      </footer>
    </article>
  );
}
