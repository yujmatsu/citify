"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import type { FeedItem } from "@/lib/api";
import { firstInterestImageUrl } from "@/lib/interest-images";
import {
  findByCode,
  formatMunicipalityLabel,
  loadMunicipalities,
  type Municipality,
} from "@/lib/municipalities";
import { cn } from "@/lib/utils";

interface FeedCardProps {
  item: FeedItem;
  /** 自治体名表示用のマッピング (5 桁コード → 表示名、優先される)。 */
  municipalityName?: Record<string, string>;
}

function scoreColor(score: number): string {
  if (score >= 80) return "bg-emerald-500";
  if (score >= 50) return "bg-amber-500";
  return "bg-zinc-400";
}

/** municipality_code から表示用ラベル。
 *  1. props.municipalityName が指定されていればそれを優先
 *  2. lib/municipalities.ts の全 1,795 件マスタから引く
 *  3. どちらにもなければコード番号をそのまま表示 */
function resolveMuniLabel(
  code: string | null | undefined,
  override: Record<string, string> | undefined,
  municipalities: Municipality[] | null,
): string {
  if (!code) return "—";
  if (override?.[code]) return override[code];
  if (municipalities) {
    const m = findByCode(municipalities, code);
    if (m) return formatMunicipalityLabel(m);
  }
  return code;
}

export function FeedCard({ item, municipalityName }: FeedCardProps) {
  const [municipalities, setMunicipalities] = useState<Municipality[] | null>(
    null,
  );

  useEffect(() => {
    // loadMunicipalities は内部キャッシュあり、複数回呼んでも fetch 1 回
    loadMunicipalities()
      .then(setMunicipalities)
      .catch(() => setMunicipalities([]));
  }, []);

  const muniLabel = resolveMuniLabel(
    item.municipality_code,
    municipalityName,
    municipalities,
  );
  const interestImage = firstInterestImageUrl(item.matched_interests);

  return (
    <article
      className={cn(
        "relative flex h-full w-full snap-start snap-always flex-col justify-between overflow-hidden",
        "px-6 py-10 sm:px-10 sm:py-12",
        "bg-gradient-to-br from-zinc-900 via-zinc-800 to-zinc-900 text-zinc-50",
        "min-h-[80vh] sm:rounded-3xl sm:shadow-2xl",
      )}
    >
      {/* Background image (関心軸サムネ、暗いオーバーレイで読みやすく) */}
      {interestImage && (
        <>
          <div
            className="pointer-events-none absolute inset-0 z-0 bg-cover bg-center opacity-30"
            style={{ backgroundImage: `url(${interestImage})` }}
            aria-hidden="true"
          />
          <div
            className="pointer-events-none absolute inset-0 z-0 bg-gradient-to-b from-zinc-900/70 via-zinc-900/60 to-zinc-900/95"
            aria-hidden="true"
          />
          <span className="absolute right-3 top-3 z-10 rounded-full bg-black/40 px-2 py-0.5 text-[9px] text-zinc-300 backdrop-blur">
            ✨ AI 生成画像
          </span>
        </>
      )}

      {/* Header: 自治体 + score badge */}
      <header className="relative z-10 flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-zinc-300">
          {item.municipality_code ? (
            <Link
              href={`/cities/${encodeURIComponent(item.municipality_code)}`}
              prefetch
              className="rounded-full border border-zinc-700 bg-zinc-800/60 px-3 py-1 font-medium transition-colors hover:border-emerald-500 hover:bg-emerald-900/40 hover:text-emerald-200"
              title={`${muniLabel} のダッシュボードを見る`}
            >
              🏙️ {muniLabel}
            </Link>
          ) : (
            <span className="rounded-full border border-zinc-700 bg-zinc-800/60 px-3 py-1 font-medium">
              {muniLabel}
            </span>
          )}
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
      <div className="relative z-10 flex flex-1 flex-col justify-center gap-6 py-8">
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
      <footer className="relative z-10 space-y-3">
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
