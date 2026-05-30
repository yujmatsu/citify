"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  fetchHeatmap,
  type HeatmapResponse,
  type PrefectureTopMuni,
  type PrefectureValue,
} from "@/lib/api";
import { ReasoningExplainerButton } from "@/components/reasoning-explainer";
import { loadPersona, type Persona } from "@/lib/persona";
import { cn } from "@/lib/utils";

import {
  GRID_COLS,
  GRID_ROWS,
  PREFECTURE_TILES,
  TILE_GAP,
  TILE_SIZE,
  colorForRank,
} from "./prefecture-grid";

// 10 関心軸 (lib/persona.ts と同じ)
const INTERESTS = [
  "住居",
  "雇用",
  "結婚",
  "子育て",
  "税",
  "起業",
  "防災",
  "医療",
  "教育",
  "移住",
] as const;

export default function HeatmapPage() {
  const router = useRouter();
  const [persona, setPersona] = useState<Persona | null>(null);
  const [focusInterest, setFocusInterest] = useState<string>("住居");
  const [data, setData] = useState<HeatmapResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedPref, setSelectedPref] = useState<PrefectureValue | null>(
    null,
  );

  useEffect(() => {
    const p = loadPersona();
    if (!p) {
      router.replace("/onboarding");
      return;
    }
    setPersona(p);
    // 初期 focus_interest は persona.interests[0] があればそれ
    if (p.interests.length > 0) {
      setFocusInterest(p.interests[0]);
    }
  }, [router]);

  // ペルソナ + focus_interest が決まったら heatmap 取得
  useEffect(() => {
    if (!persona) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchHeatmap({
      userId: persona.user_id,
      ageGroup: persona.age_group,
      interests: persona.interests,
      focusInterest,
    })
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((err) => {
        if (!cancelled) {
          const msg =
            err instanceof ApiError
              ? `API エラー (${err.status}): ${err.message}`
              : err instanceof Error
                ? err.message
                : "取得に失敗しました";
          setError(msg);
          setData(null);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [persona, focusInterest]);

  // prefecture_code → PrefectureValue lookup
  const prefByCode = useMemo(() => {
    const map = new Map<string, PrefectureValue>();
    data?.prefecture_values.forEach((p) => map.set(p.prefecture_code, p));
    return map;
  }, [data]);

  // prefecture_code → top municipalities
  const topByCode = useMemo(() => {
    const map = new Map<string, PrefectureTopMuni["municipalities"]>();
    data?.top_municipalities.forEach((t) =>
      map.set(t.prefecture_code, t.municipalities),
    );
    return map;
  }, [data]);

  if (persona === null) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">読み込み中...</p>
      </main>
    );
  }

  const total = data?.prefecture_values.length ?? 0;

  return (
    <main className="flex flex-1 flex-col px-6 pb-6 pt-6 sm:px-10">
      <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col space-y-6">
        {/* Top nav */}
        <div className="flex items-center justify-between">
          <Link
            href="/feed"
            className="text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← フィードに戻る
          </Link>
          <span className="text-xs text-zinc-500">
            全国ヒートマップ (Plan X)
          </span>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            🗾 全国ヒートマップ
          </h1>
          <p className="text-sm text-zinc-500">
            あなたの状況に合う指標を Agent が自動選定し、47
            都道府県を比較します。タイルをクリックで県内 TOP3 自治体を表示。
          </p>
        </header>

        {/* Interest selector */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">
            フォーカス軸:
          </span>
          {INTERESTS.map((i) => (
            <button
              key={i}
              type="button"
              onClick={() => setFocusInterest(i)}
              disabled={loading}
              className={cn(
                "rounded-lg border px-3 py-1 text-xs transition disabled:opacity-50",
                focusInterest === i
                  ? "border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                  : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800",
              )}
            >
              {i}
            </button>
          ))}
        </div>

        {/* Advisor banner (Agent reasoning) */}
        {data?.advice && (
          <div
            className={cn(
              "rounded-2xl border p-4 text-sm space-y-2",
              data.advice.source === "llm"
                ? "border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950"
                : "border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950",
            )}
          >
            <div className="flex items-baseline justify-between gap-2">
              <div className="font-semibold text-zinc-900 dark:text-zinc-100">
                📊 選定指標: {data.advice.metric_label_ja}
                {data.advice.unit && (
                  <span className="ml-1 text-xs text-zinc-500">
                    ({data.advice.unit})
                  </span>
                )}
              </div>
              <div className="text-[10px] font-mono text-zinc-500">
                {data.advice.source === "llm"
                  ? "🤖 Agent 選定"
                  : "📐 ルールベース"}
              </div>
            </div>
            <p className="leading-relaxed text-zinc-700 dark:text-zinc-300">
              {data.advice.reasoning}
            </p>
            <p className="text-[10px] text-zinc-500">
              📌 ペルソナ: {data.advice.persona_summary}・色付け方向性:{" "}
              {data.advice.direction === "lower_is_better"
                ? "低いほど濃い青 (上位)"
                : "高いほど濃い青 (上位)"}
            </p>
          </div>
        )}

        {/* Plan PP: Reasoning Transparency (Meta-Reasoner) */}
        {data?.advice && (
          <div className="flex justify-end">
            <ReasoningExplainerButton
              agentName="heatmap_advisor"
              rawReasoning={data.advice.reasoning}
              agentOutputSummary={`${data.advice.metric_label_ja}${data.advice.unit ? ` (${data.advice.unit})` : ""} を ${data.advice.direction === "lower_is_better" ? "低いほど良い" : "高いほど良い"} 方向で選定`}
              personaContext={data.advice.persona_summary}
            />
          </div>
        )}

        {/* Status */}
        {loading && (
          <div className="rounded-xl border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            ⏳ Agent が指標を選定し、全国データを集計中...
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200">
            ❌ {error}
          </div>
        )}

        {/* Tile map */}
        {!loading && !error && data && (
          <div className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <TileGridMap
              prefByCode={prefByCode}
              total={total}
              direction={data.advice.direction}
              onSelect={setSelectedPref}
            />
          </div>
        )}

        {/* legend */}
        {data && total > 0 && (
          <div className="flex items-center gap-3 text-xs text-zinc-500">
            <span>順位:</span>
            <div className="flex items-center gap-1">
              <span
                className="inline-block h-4 w-4 rounded"
                style={{
                  backgroundColor: colorForRank(
                    1,
                    total,
                    data.advice.direction,
                  ),
                }}
              />
              <span>1 位 (最上位)</span>
            </div>
            <div className="flex items-center gap-1">
              <span
                className="inline-block h-4 w-4 rounded"
                style={{
                  backgroundColor: colorForRank(
                    total,
                    total,
                    data.advice.direction,
                  ),
                }}
              />
              <span>47 位</span>
            </div>
          </div>
        )}
      </div>

      {/* Prefecture detail modal */}
      {selectedPref && data && (
        <PrefectureModal
          pref={selectedPref}
          munis={topByCode.get(selectedPref.prefecture_code) ?? []}
          metricLabel={data.advice.metric_label_ja}
          unit={data.advice.unit}
          onClose={() => setSelectedPref(null)}
        />
      )}
    </main>
  );
}

// ============================================================================
// Tile grid SVG map
// ============================================================================

function TileGridMap({
  prefByCode,
  total,
  direction,
  onSelect,
}: {
  prefByCode: Map<string, PrefectureValue>;
  total: number;
  direction: "lower_is_better" | "higher_is_better";
  onSelect: (pref: PrefectureValue) => void;
}): React.ReactElement {
  const width = GRID_COLS * (TILE_SIZE + TILE_GAP);
  const height = GRID_ROWS * (TILE_SIZE + TILE_GAP);

  return (
    <svg
      role="img"
      aria-label="日本 47 都道府県タイルマップ"
      viewBox={`0 0 ${width} ${height}`}
      className="mx-auto w-full max-w-3xl"
    >
      {PREFECTURE_TILES.map((tile) => {
        const x = tile.col * (TILE_SIZE + TILE_GAP);
        const y = tile.row * (TILE_SIZE + TILE_GAP);
        const pref = prefByCode.get(tile.code);
        const fill = pref
          ? colorForRank(pref.rank, total, direction)
          : "rgba(228, 228, 231, 0.4)";
        const hasData = pref !== undefined;
        return (
          <g
            key={tile.code}
            transform={`translate(${x}, ${y})`}
            className={hasData ? "cursor-pointer" : "cursor-not-allowed"}
            onClick={() => {
              if (pref) onSelect(pref);
            }}
          >
            <rect
              width={TILE_SIZE}
              height={TILE_SIZE}
              rx={6}
              ry={6}
              fill={fill}
              stroke={
                hasData ? "rgba(63, 63, 70, 0.2)" : "rgba(228, 228, 231, 0.7)"
              }
              strokeWidth={1}
            >
              <title>
                {tile.name}
                {pref
                  ? ` (${pref.rank} 位 / 中央値 ${pref.metric_median.toFixed(1)})`
                  : " (データなし)"}
              </title>
            </rect>
            <text
              x={TILE_SIZE / 2}
              y={TILE_SIZE / 2 - 4}
              textAnchor="middle"
              fontSize="12"
              fontWeight="600"
              fill={hasData && pref.rank <= 10 ? "white" : "#27272a"}
              pointerEvents="none"
            >
              {tile.name}
            </text>
            {pref && (
              <text
                x={TILE_SIZE / 2}
                y={TILE_SIZE / 2 + 14}
                textAnchor="middle"
                fontSize="10"
                fill={pref.rank <= 10 ? "rgba(255,255,255,0.85)" : "#52525b"}
                pointerEvents="none"
              >
                #{pref.rank}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ============================================================================
// Prefecture detail modal (TOP3 自治体)
// ============================================================================

function PrefectureModal({
  pref,
  munis,
  metricLabel,
  unit,
  onClose,
}: {
  pref: PrefectureValue;
  munis: {
    municipality_code: string;
    municipality_name: string;
    metric_value: number;
  }[];
  metricLabel: string;
  unit: string;
  onClose: () => void;
}): React.ReactElement {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${pref.prefecture_name} の詳細`}
      className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-900/50 px-4 py-6 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md max-h-[80vh] overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-700 dark:bg-zinc-900"
      >
        <div className="flex items-center justify-between border-b border-zinc-200 px-5 py-3 dark:border-zinc-700">
          <h2 className="text-base font-semibold">
            {pref.prefecture_name}{" "}
            <span className="ml-2 text-xs text-zinc-500">({pref.rank} 位)</span>
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="閉じる"
            className="rounded-lg px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
          >
            ✕ 閉じる
          </button>
        </div>

        <div className="space-y-3 p-4">
          <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 dark:border-zinc-700 dark:bg-zinc-950">
            <div className="text-xs text-zinc-500">
              {metricLabel} (県中央値)
            </div>
            <div className="mt-1 text-2xl font-bold">
              {pref.metric_median.toFixed(1)}
              <span className="ml-1 text-sm font-normal text-zinc-500">
                {unit}
              </span>
            </div>
            <div className="text-[10px] text-zinc-500">
              県内 {pref.muni_count} 自治体の中央値
            </div>
          </div>

          <div>
            <div className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">
              県内 TOP3 自治体
            </div>
            {munis.length === 0 ? (
              <div className="mt-2 text-xs text-zinc-500">
                データ取得中、または該当自治体なし
              </div>
            ) : (
              <ul className="mt-2 space-y-2">
                {munis.map((m, idx) => (
                  <li
                    key={m.municipality_code}
                    className="rounded-lg border border-zinc-200 bg-white p-2 dark:border-zinc-700 dark:bg-zinc-900"
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <Link
                        href={`/cities/${m.municipality_code}`}
                        className="text-sm font-medium text-blue-600 hover:underline dark:text-blue-400"
                      >
                        #{idx + 1} {m.municipality_name}
                      </Link>
                      <span className="text-xs text-zinc-500">
                        {m.metric_value.toFixed(1)} {unit}
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
