import type React from "react";

import type { PopulationTrendResponse } from "@/lib/api";

/**
 * 人口推移グラフ (TASK-POPTREND)。
 * - census (国勢調査実績) = 実線青
 * - projection (XKT013 将来推計 2025-2070) = 破線オレンジ
 * - 実績の末尾と予測の先頭を 1 点共有して連結 (視覚的に連続)
 * 依存追加なしの自前 SVG (Plan Z ForecastChart 流用)。
 */
export function PopulationTrendChart({
  data,
}: {
  data: PopulationTrendResponse;
}): React.ReactElement {
  const series = [...data.series].sort((a, b) => a.year - b.year);
  if (series.length < 2) {
    return (
      <p className="text-center text-sm text-zinc-500">
        人口推移データがまだありません
      </p>
    );
  }

  const width = 600;
  const height = 300;
  const padding = { top: 20, right: 20, bottom: 40, left: 52 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const maxPop = Math.max(...series.map((d) => d.population), 1);
  const minPop = Math.min(...series.map((d) => d.population), maxPop);
  // Y 軸は 0 起点だと減少が見えにくいので、min を少し下げた範囲にする
  const yLo = Math.max(0, minPop - (maxPop - minPop) * 0.15);
  const yHi = maxPop + (maxPop - minPop) * 0.15 || maxPop * 1.1;
  const yRange = yHi - yLo || 1;

  const stepX = innerW / Math.max(series.length - 1, 1);
  const points = series.map((d, i) => ({
    x: padding.left + i * stepX,
    y: padding.top + innerH * (1 - (d.population - yLo) / yRange),
    year: d.year,
    population: d.population,
    source: d.source,
  }));

  // census / projection で path を分割。境界 (最後の census) を projection 始点に共有。
  const lastCensusIdx = points.reduce(
    (acc, p, i) => (p.source === "census" ? i : acc),
    -1,
  );
  const censusPts = points.filter((p) => p.source === "census");
  const projPts = points.filter((p) => p.source === "projection");
  const toPath = (pts: typeof points): string =>
    pts
      .map(
        (p, i) => `${i === 0 ? "M" : "L"} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`,
      )
      .join(" ");
  const censusPath = toPath(censusPts);
  // projection は最後の census 点から連結 (連続感)
  const projConnected =
    lastCensusIdx >= 0 && projPts.length > 0
      ? [points[lastCensusIdx], ...projPts]
      : projPts;
  const projPath = toPath(projConnected);

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((r) => ({
    value: Math.round(yLo + yRange * r),
    y: padding.top + innerH * (1 - r),
  }));

  const fmt = (n: number): string => n.toLocaleString("ja-JP");

  return (
    <svg
      role="img"
      aria-label="人口推移グラフ (実績 + 将来推計)"
      viewBox={`0 0 ${width} ${height}`}
      className="w-full"
    >
      {/* Y 軸グリッド + ラベル */}
      {yTicks.map((t) => (
        <g key={`y-${t.value}`}>
          <line
            x1={padding.left}
            x2={padding.left + innerW}
            y1={t.y}
            y2={t.y}
            stroke="rgba(228, 228, 231, 0.5)"
            strokeWidth={1}
          />
          <text
            x={padding.left - 6}
            y={t.y}
            textAnchor="end"
            dominantBaseline="middle"
            fontSize="9"
            fill="#71717a"
          >
            {fmt(t.value)}
          </text>
        </g>
      ))}

      {/* census 実線青 */}
      <path d={censusPath} stroke="#2563eb" strokeWidth={2} fill="none" />
      {/* projection 破線オレンジ */}
      {projPath && (
        <path
          d={projPath}
          stroke="#f97316"
          strokeWidth={2}
          fill="none"
          strokeDasharray="6 4"
        />
      )}

      {/* 各点 */}
      {points.map((p) => (
        <circle
          key={`pt-${p.year}`}
          cx={p.x}
          cy={p.y}
          r={3}
          fill={p.source === "projection" ? "#f97316" : "#2563eb"}
        >
          <title>
            {p.year}年: {fmt(p.population)}人
            {p.source === "projection" ? " (推計)" : " (実績)"}
          </title>
        </circle>
      ))}

      {/* X 軸ラベル (先頭/境界/末尾) */}
      {points
        .filter(
          (_, i) =>
            i === 0 ||
            i === Math.max(lastCensusIdx, 0) ||
            i === points.length - 1,
        )
        .map((p) => (
          <text
            key={`x-${p.year}`}
            x={p.x}
            y={height - 12}
            textAnchor="middle"
            fontSize="10"
            fill="#71717a"
          >
            {p.year}
          </text>
        ))}

      {/* legend */}
      <g transform={`translate(${padding.left + 10}, ${padding.top + 6})`}>
        <line x1={0} x2={20} y1={0} y2={0} stroke="#2563eb" strokeWidth={2} />
        <text x={25} y={4} fontSize="10" fill="#52525b">
          実績(国勢調査)
        </text>
        <line
          x1={120}
          x2={140}
          y1={0}
          y2={0}
          stroke="#f97316"
          strokeWidth={2}
          strokeDasharray="6 4"
        />
        <text x={145} y={4} fontSize="10" fill="#52525b">
          将来推計
        </text>
      </g>
    </svg>
  );
}
