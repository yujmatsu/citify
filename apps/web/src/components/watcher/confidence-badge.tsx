"use client";

import type React from "react";
import { cn } from "@/lib/utils";

type Confidence = "high" | "medium" | "low";

const STYLE: Record<Confidence, { label: string; cls: string }> = {
  high: {
    label: "確信度 高",
    cls: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  },
  medium: {
    label: "確信度 中",
    cls: "bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  },
  low: {
    label: "確信度 低",
    cls: "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400",
  },
};

/** エージェントの自己申告確信度 (A7)。データの厚みに応じた断定度を可視化。 */
export function ConfidenceBadge({
  confidence,
}: {
  confidence: Confidence;
}): React.JSX.Element {
  const s = STYLE[confidence];
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold",
        s.cls,
      )}
    >
      {s.label}
    </span>
  );
}
