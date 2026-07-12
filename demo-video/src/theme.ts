import { loadFont } from "@remotion/google-fonts/NotoSansJP";

// 日本語字幕・テロップ用フォント。日本語サブセットを明示ロード。
const { fontFamily } = loadFont("normal", {
  weights: ["400", "700", "900"],
  subsets: ["japanese"],
});

export const FONT_FAMILY = fontFamily;

export const COLORS = {
  bg: "#0b0f17",
  panel: "#131b2b",
  panelBorder: "#243049",
  text: "#f5f7fa",
  sub: "#9aa4b2",
  accent: "#10b981", // emerald — Watcher(主役)/CTA
  info: "#58a6ff",
  warn: "#f59e0b",
  danger: "#ef4444",
  captionBg: "rgba(6,10,18,0.82)",
} as const;
