"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  ApiError,
  fetchForecast,
  type ForecastPoint,
  type ForecastResponse,
  type MonthCount,
} from "@/lib/api";
import { loadPersona, type Persona } from "@/lib/persona";
import { cn } from "@/lib/utils";

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

const HISTORY_OPTIONS: Array<{ value: number; label: string }> = [
  { value: 6, label: "6 か月" },
  { value: 12, label: "1 年" },
  { value: 24, label: "2 年" },
];

export default function ForecastPage() {
  const router = useRouter();
  const [persona, setPersona] = useState<Persona | null>(null);
  const [themeInterest, setThemeInterest] = useState<string>("住居");
  const [municipalityCode, setMunicipalityCode] = useState<string>("");
  const [historyMonths, setHistoryMonths] = useState<number>(12);
  const [data, setData] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const p = loadPersona();
    if (!p) {
      router.replace("/onboarding");
      return;
    }
    setPersona(p);
    if (p.interests.length > 0) setThemeInterest(p.interests[0]);
    if (p.municipality_codes.length > 0) {
      setMunicipalityCode(p.municipality_codes[0]);
    }
  }, [router]);

  useEffect(() => {
    if (!persona) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchForecast({
      themeInterest,
      userId: persona.user_id,
      ageGroup: persona.age_group,
      municipalityCode: municipalityCode || null,
      historyMonths,
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
                : "取得失敗";
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
  }, [persona, themeInterest, municipalityCode, historyMonths]);

  if (persona === null) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <p className="text-sm text-zinc-500">読み込み中...</p>
      </main>
    );
  }

  return (
    <main className="flex flex-1 flex-col px-6 pb-6 pt-6 sm:px-10">
      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col space-y-6">
        <div className="flex items-center justify-between">
          <Link
            href="/feed"
            className="text-sm text-zinc-500 underline hover:text-zinc-700 dark:hover:text-zinc-300"
          >
            ← フィードに戻る
          </Link>
          <span className="text-xs text-zinc-500">
            議題トレンド予測 (Plan Z)
          </span>
        </div>

        <header className="space-y-2">
          <h1 className="text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
            📈 議題件数の推移と予測
          </h1>
          <p className="text-sm text-zinc-500">
            関心軸別の月別議題件数を集計、3 か月先まで線形外挿で予測 + Agent
            が介入的に説明します。
          </p>
        </header>

        {/* Disclaimer (Reviewer High #1 必須) */}
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-800 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">
          📊
          本グラフは議題件数の数値推移を可視化したものです。特定の自治体への移住・行動を推奨するものではありません。
        </div>

        {/* Selectors */}
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-zinc-600 dark:text-zinc-400">
              関心軸:
            </span>
            {INTERESTS.map((i) => (
              <button
                key={i}
                type="button"
                onClick={() => setThemeInterest(i)}
                disabled={loading}
                className={cn(
                  "rounded-lg border px-3 py-1 text-xs transition disabled:opacity-50",
                  themeInterest === i
                    ? "border-blue-500 bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                    : "border-zinc-300 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800",
                )}
              >
                {i}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-3 text-xs">
            <div className="flex items-center gap-2">
              <span className="font-semibold text-zinc-600 dark:text-zinc-400">
                自治体:
              </span>
              <input
                type="text"
                placeholder="5 桁コード (空 = 全国)"
                value={municipalityCode}
                onChange={(e) => setMunicipalityCode(e.target.value)}
                className="w-32 rounded border border-zinc-300 px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
              />
            </div>
            <div className="flex items-center gap-2">
              <span className="font-semibold text-zinc-600 dark:text-zinc-400">
                期間:
              </span>
              {HISTORY_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setHistoryMonths(opt.value)}
                  disabled={loading}
                  className={cn(
                    "rounded px-2 py-1 text-xs transition disabled:opacity-50",
                    historyMonths === opt.value
                      ? "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300"
                      : "text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300",
                  )}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Narrative banner */}
        {data && (
          <NarrativeBanner
            narrative={data.narrative}
            trend={data.series.trend_classification}
            confidence={data.series.confidence}
            slope={data.series.slope}
          />
        )}

        {/* Status */}
        {loading && (
          <div className="rounded-xl border border-zinc-200 bg-white p-6 text-center text-sm text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            ⏳ Agent が月別集計し、3 か月先を予測中...
          </div>
        )}
        {error && (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-700 dark:bg-rose-950 dark:text-rose-200">
            ❌ {error}
          </div>
        )}

        {/* Chart */}
        {!loading && !error && data && (
          <div className="rounded-2xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <ForecastChart
              historical={data.series.historical}
              forecast={data.series.forecast}
            />
          </div>
        )}
      </div>
    </main>
  );
}

// ============================================================================
// NarrativeBanner + TrendBadge
// ============================================================================

function NarrativeBanner({
  narrative,
  trend,
  confidence,
  slope,
}: {
  narrative: ForecastResponse["narrative"];
  trend: ForecastResponse["series"]["trend_classification"];
  confidence: ForecastResponse["series"]["confidence"];
  slope: number;
}): React.ReactElement {
  const isLlm = narrative.source === "llm";
  return (
    <div
      className={cn(
        "rounded-2xl border p-4 text-sm space-y-2",
        isLlm
          ? "border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-950"
          : "border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950",
      )}
    >
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-semibold text-zinc-900 dark:text-zinc-100">
          {narrative.headline}
        </div>
        <div className="flex items-center gap-2 text-[10px] font-mono text-zinc-500">
          <TrendBadge trend={trend} />
          <span>信頼度: {confidence}</span>
          <span>{isLlm ? "🤖 Agent" : "📐 rule-based"}</span>
        </div>
      </div>
      <p className="leading-relaxed text-zinc-700 dark:text-zinc-300">
        {narrative.reasoning}
      </p>
      <div className="text-[10px] text-zinc-500">
        傾き: {slope >= 0 ? "+" : ""}
        {slope.toFixed(2)} 件/月
      </div>
    </div>
  );
}

function TrendBadge({
  trend,
}: {
  trend: ForecastResponse["series"]["trend_classification"];
}): React.ReactElement {
  const map: Record<typeof trend, { label: string; color: string }> = {
    surge: {
      label: "📈 急騰",
      color: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
    },
    increasing: {
      label: "↗ 増加",
      color: "bg-blue-100 text-blue-700 dark:bg-blue-950 dark:text-blue-300",
    },
    flat: {
      label: "→ 横ばい",
      color: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
    },
    decreasing: {
      label: "↘ 減少",
      color:
        "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
    },
    crash: {
      label: "📉 急減",
      color: "bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300",
    },
  };
  const item = map[trend];
  return (
    <span className={cn("rounded px-1.5 py-0.5", item.color)}>
      {item.label}
    </span>
  );
}

// ============================================================================
// ForecastChart (自前 SVG 折れ線、依存なし)
// ============================================================================

function ForecastChart({
  historical,
  forecast,
}: {
  historical: MonthCount[];
  forecast: ForecastPoint[];
}): React.ReactElement {
  const all = [
    ...historical.map((m) => ({
      ym: m.year_month,
      count: m.speech_count,
      is_forecast: false,
    })),
    ...forecast.map((f) => ({
      ym: f.year_month,
      count: f.speech_count,
      is_forecast: true,
    })),
  ];
  if (all.length < 2) {
    return (
      <p className="text-center text-sm text-zinc-500">
        データ不足のためグラフを表示できません
      </p>
    );
  }
  const width = 600;
  const height = 300;
  const padding = { top: 20, right: 20, bottom: 40, left: 40 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const maxCount = Math.max(...all.map((d) => d.count), 1);
  const yMax = maxCount * 1.2;

  const stepX = innerW / Math.max(all.length - 1, 1);
  const points = all.map((d, i) => ({
    x: padding.left + i * stepX,
    y: padding.top + innerH * (1 - d.count / yMax),
    ym: d.ym,
    count: d.count,
    is_forecast: d.is_forecast,
  }));

  // historical / forecast の path を分割
  const historicalPath = points
    .filter((_, i) => i < historical.length)
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`)
    .join(" ");
  const forecastPath =
    historical.length > 0 && forecast.length > 0
      ? [points[historical.length - 1], ...points.slice(historical.length)]
          .map(
            (p, i) =>
              `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`,
          )
          .join(" ")
      : "";

  // Y axis ticks (5 等分)
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((r) => ({
    value: Math.round(yMax * r),
    y: padding.top + innerH * (1 - r),
  }));

  return (
    <svg
      role="img"
      aria-label="議題件数推移グラフ"
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
    >
      {/* Y axis grid */}
      {yTicks.map((t) => (
        <g key={`ytick-${t.value}`}>
          <line
            x1={padding.left}
            x2={padding.left + innerW}
            y1={t.y}
            y2={t.y}
            stroke="rgba(228, 228, 231, 0.5)"
            strokeWidth={1}
          />
          <text
            x={padding.left - 5}
            y={t.y}
            textAnchor="end"
            dominantBaseline="middle"
            fontSize="10"
            fill="#71717a"
          >
            {t.value}
          </text>
        </g>
      ))}

      {/* historical (実線青) */}
      <path d={historicalPath} stroke="#2563eb" strokeWidth={2} fill="none" />

      {/* forecast (破線オレンジ、historical の末尾から連結) */}
      {forecastPath && (
        <path
          d={forecastPath}
          stroke="#f97316"
          strokeWidth={2}
          fill="none"
          strokeDasharray="6 4"
        />
      )}

      {/* points */}
      {points.map((p) => (
        <circle
          key={`pt-${p.ym}`}
          cx={p.x}
          cy={p.y}
          r={3}
          fill={p.is_forecast ? "#f97316" : "#2563eb"}
        >
          <title>
            {p.ym}: {p.count.toFixed(1)} 件{p.is_forecast ? " (予測)" : ""}
          </title>
        </circle>
      ))}

      {/* X axis labels (3-4 件だけ表示) */}
      {points
        .filter(
          (_, i) =>
            i === 0 || i === Math.floor(all.length / 2) || i === all.length - 1,
        )
        .map((p) => (
          <text
            key={`xlabel-${p.ym}`}
            x={p.x}
            y={height - 10}
            textAnchor="middle"
            fontSize="10"
            fill="#71717a"
          >
            {p.ym}
          </text>
        ))}

      {/* legend */}
      <g transform={`translate(${padding.left + 10}, ${padding.top + 10})`}>
        <line x1={0} x2={20} y1={0} y2={0} stroke="#2563eb" strokeWidth={2} />
        <text x={25} y={4} fontSize="10" fill="#52525b">
          実績
        </text>
        <line
          x1={70}
          x2={90}
          y1={0}
          y2={0}
          stroke="#f97316"
          strokeWidth={2}
          strokeDasharray="6 4"
        />
        <text x={95} y={4} fontSize="10" fill="#52525b">
          予測
        </text>
      </g>
    </svg>
  );
}
