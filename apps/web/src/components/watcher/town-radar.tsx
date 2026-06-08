"use client";

import type React from "react";
import type { CompareStatsResponse } from "@/lib/api";

/** 街ごとの色 (住む街=emerald 基準、候補は青/橙/紫…)。 */
const TOWN_COLORS = ["#059669", "#0284c7", "#ea580c", "#7c3aed", "#db2777"];

const SIZE = 260;
const CENTER = SIZE / 2;
const RADIUS = 92;
const RINGS = [25, 50, 75, 100];

/** key ごとの生値フォーマット。 */
function formatRaw(key: string, raw: number | null): string {
  if (raw == null) return "—";
  switch (key) {
    case "financial_capability_index":
      return raw.toFixed(2);
    case "taxable_income_per_capita_yen":
      return `¥${Math.round(raw / 10000)}万`;
    case "homeownership_rate_pct":
    case "real_debt_service_ratio_pct":
      return `${raw}%`;
    case "future_population_change_pct":
      // 2070年予測の増減率 (符号付き)
      return `${raw > 0 ? "+" : ""}${raw}%`;
    case "crime_rate_per_1000":
      return `${raw}`;
    // TASK-CITYDATA: 暮らしの指標
    case "doctors_per_100k":
      return `${Math.round(raw)}`;
    case "unemployment_rate_pct":
      return `${raw}%`;
    case "dwelling_area_sqm":
      return `${raw}㎡`;
    default:
      return `${raw}`;
  }
}

function angleFor(i: number, n: number): number {
  // 上(-90°)始点で時計回り
  return (-90 + (360 / n) * i) * (Math.PI / 180);
}

function point(score: number, i: number, n: number): [number, number] {
  const a = angleFor(i, n);
  const r = (Math.max(0, Math.min(100, score)) / 100) * RADIUS;
  return [CENTER + r * Math.cos(a), CENTER + r * Math.sin(a)];
}

/**
 * 街比較レーダー (TASK-FISCAL)。自前 SVG (依存追加なし、population-trend-chart と同方針)。
 * score は全国percentile (0-100、外側ほど良い)。生値は下の表で併記。
 */
export function TownRadar({
  data,
}: {
  data: CompareStatsResponse;
}): React.ReactElement {
  const { metrics, towns } = data;
  const n = metrics.length;
  if (n === 0 || towns.length === 0) {
    return (
      <p className="text-center text-sm text-zinc-500">
        比較できる統計データがまだありません
      </p>
    );
  }

  // score が全街 null の指標が1つでもあるか (データ未投入の目安)
  const anyScore = towns.some((t) =>
    metrics.some((m) => t.values[m.key]?.score != null),
  );

  return (
    <div className="space-y-4">
      {/* レーダー */}
      <div className="flex flex-col items-center">
        <svg
          viewBox={`0 0 ${SIZE} ${SIZE}`}
          className="h-64 w-64"
          role="img"
          aria-label="街比較レーダーチャート"
        >
          {/* グリッド */}
          {RINGS.map((ring) => (
            <polygon
              key={ring}
              points={metrics
                .map((_, i) => point(ring, i, n).join(","))
                .join(" ")}
              fill="none"
              stroke="currentColor"
              className="text-zinc-200 dark:text-zinc-700"
              strokeWidth={1}
            />
          ))}
          {/* 軸線 + ラベル */}
          {metrics.map((m, i) => {
            const [x, y] = point(100, i, n);
            const [lx, ly] = point(118, i, n);
            return (
              <g key={m.key}>
                <line
                  x1={CENTER}
                  y1={CENTER}
                  x2={x}
                  y2={y}
                  stroke="currentColor"
                  className="text-zinc-200 dark:text-zinc-700"
                  strokeWidth={1}
                />
                <text
                  x={lx}
                  y={ly}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  className="fill-zinc-600 text-[10px] font-medium dark:fill-zinc-300"
                >
                  {m.label}
                </text>
              </g>
            );
          })}
          {/* 街ごとのポリゴン */}
          {towns.map((t, ti) => {
            const color = TOWN_COLORS[ti % TOWN_COLORS.length];
            const pts = metrics
              .map((m, i) => point(t.values[m.key]?.score ?? 0, i, n).join(","))
              .join(" ");
            return (
              <polygon
                key={t.municipality_code}
                points={pts}
                fill={color}
                fillOpacity={0.15}
                stroke={color}
                strokeWidth={2}
              />
            );
          })}
        </svg>

        {/* 凡例 */}
        <div className="mt-1 flex flex-wrap justify-center gap-3 text-xs">
          {towns.map((t, ti) => (
            <span
              key={t.municipality_code}
              className="inline-flex items-center gap-1"
            >
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{
                  backgroundColor: TOWN_COLORS[ti % TOWN_COLORS.length],
                }}
              />
              {t.municipality_name}
            </span>
          ))}
        </div>
        <p className="mt-1 text-xs text-zinc-400">
          外側ほど全国で上位（指標ごとの望ましい方向で算出。財政力・所得・医療などは高い側、
          負債・治安は低い側を上位とした）
        </p>
      </div>

      {/* 生値テーブル */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-zinc-200 dark:border-zinc-700">
              <th className="py-1.5 pr-2 text-left font-medium text-zinc-500">
                指標
              </th>
              {towns.map((t) => (
                <th
                  key={t.municipality_code}
                  className="px-2 py-1.5 text-right font-medium"
                >
                  {t.municipality_name}
                </th>
              ))}
              <th className="px-2 py-1.5 text-right font-medium text-zinc-400">
                全国中央値
              </th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr
                key={m.key}
                className="border-b border-zinc-100 dark:border-zinc-800"
              >
                <td className="py-1.5 pr-2 text-zinc-600 dark:text-zinc-400">
                  {m.label}
                </td>
                {towns.map((t) => {
                  const v = t.values[m.key];
                  return (
                    <td
                      key={t.municipality_code}
                      className="px-2 py-1.5 text-right tabular-nums"
                    >
                      <div>{formatRaw(m.key, v?.raw ?? null)}</div>
                      {v?.rank != null && v?.total != null && (
                        <div className="text-[11px] font-normal leading-tight text-zinc-400">
                          上位{Math.max(1, Math.round((v.rank / v.total) * 100))}%
                          <span className="block">
                            {v.rank}位/{v.total}
                          </span>
                        </div>
                      )}
                    </td>
                  );
                })}
                <td className="px-2 py-1.5 text-right tabular-nums text-zinc-400">
                  {formatRaw(m.key, m.national_median ?? null)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-xs text-zinc-400">
          「上位X%」「○位/△」は全国での位置（1位＝最も上位）。母数は指標ごとにデータのある市区町村数。
        </p>
      </div>

      {!anyScore && (
        <p className="text-center text-[11px] text-amber-600 dark:text-amber-400">
          財政データを準備中です（投入後に反映されます）
        </p>
      )}
    </div>
  );
}
