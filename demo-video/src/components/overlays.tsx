import {
  AbsoluteFill,
  interpolate,
  Sequence,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { Scene } from "../data/scenes";
import { COLORS } from "../theme";

/** 画面下部に焼き込む字幕 (音声OFF視聴対策)。scene 尺に合わせてフェード。 */
export const Caption: React.FC<{ text: string; durationSec: number }> = ({
  text,
  durationSec,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const total = durationSec * fps;
  const fade = Math.min(0.4 * fps, total / 4);
  const opacity = interpolate(
    frame,
    [0, fade, total - fade, total],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: 64,
      }}
    >
      <div
        style={{
          opacity,
          maxWidth: 1500,
          background: COLORS.captionBg,
          color: COLORS.text,
          fontSize: 40,
          fontWeight: 700,
          lineHeight: 1.4,
          padding: "18px 34px",
          borderRadius: 14,
          textAlign: "center",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};

/** 左上の章バッジ (編集ナビ用。最終 render では DEV_OVERLAYS=false で消す)。 */
export const ChapterBadge: React.FC<{ chapter: string; title: string }> = ({
  chapter,
  title,
}) => (
  <div
    style={{
      position: "absolute",
      top: 40,
      left: 48,
      display: "flex",
      alignItems: "center",
      gap: 14,
    }}
  >
    <span
      style={{
        fontSize: 34,
        fontWeight: 900,
        color: "#fff",
        background: COLORS.accent,
        borderRadius: 10,
        padding: "4px 16px",
      }}
    >
      {chapter}
    </span>
    <span
      style={{
        fontSize: 26,
        fontWeight: 700,
        color: COLORS.text,
        textShadow: "0 2px 8px #000",
      }}
    >
      {title}
    </span>
  </div>
);

const TECH_LOGOS = [
  "Cloud Run",
  "ADK",
  "Gemini 2.5",
  "Vertex AI RAG",
  "Imagen 3",
  "BigQuery",
  "Pub/Sub",
  "Firestore",
  "Firebase App Hosting",
  "Terraform",
];

/** 技術ロゴ帯 (シーン⑤)。Veo は含めない。 */
export const TechLogoBar: React.FC = () => (
  <div
    style={{
      position: "absolute",
      left: 0,
      right: 0,
      bottom: 250,
      display: "flex",
      flexWrap: "wrap",
      justifyContent: "center",
      gap: 12,
      padding: "0 80px",
    }}
  >
    {TECH_LOGOS.map((name) => (
      <span
        key={name}
        style={{
          fontSize: 24,
          fontWeight: 700,
          color: COLORS.info,
          background: "rgba(88,166,255,0.12)",
          border: `1px solid ${COLORS.panelBorder}`,
          borderRadius: 999,
          padding: "6px 16px",
        }}
      >
        {name}
      </span>
    ))}
  </div>
);

/** 「人間レビュー必須・自動実行なし」バッジ (シーン④)。 */
export const HumanReviewBadge: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pulse = 0.85 + 0.15 * Math.sin((frame / fps) * Math.PI * 2 * 0.6);
  return (
    <div
      style={{
        position: "absolute",
        top: 40,
        right: 48,
        opacity: pulse,
        fontSize: 26,
        fontWeight: 900,
        color: "#fff",
        background: COLORS.warn,
        borderRadius: 10,
        padding: "8px 18px",
        boxShadow: "0 4px 16px rgba(245,158,11,0.4)",
      }}
    >
      🔒 人間レビュー必須・自動実行なし
    </div>
  );
};

/** 素材(録画/画像)未配置のプレースホルダ。撮影ヒントを表示。 */
export const PlaceholderPanel: React.FC<{
  kind: "footage" | "slide";
  scene: Scene;
}> = ({ kind, scene }) => (
  <AbsoluteFill
    style={{ justifyContent: "center", alignItems: "center", padding: 120 }}
  >
    <div
      style={{
        width: "78%",
        height: "62%",
        border: `4px dashed ${COLORS.panelBorder}`,
        borderRadius: 24,
        background: COLORS.panel,
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        gap: 20,
        padding: 48,
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 30, fontWeight: 900, color: COLORS.accent }}>
        {scene.chapter} {scene.title}
      </div>
      <div style={{ fontSize: 24, color: COLORS.sub }}>
        ▶{" "}
        {kind === "slide"
          ? "画像を public/slides/ に配置"
          : "録画を public/recordings/ に配置"}
        して scenes.ts に設定
      </div>
      {scene.record ? (
        <div
          style={{
            fontSize: 24,
            color: COLORS.text,
            background: "rgba(16,185,129,0.1)",
            border: `1px solid ${COLORS.accent}`,
            borderRadius: 12,
            padding: "12px 20px",
            maxWidth: 900,
          }}
        >
          撮影: {scene.record}
        </div>
      ) : null}
    </div>
  </AbsoluteFill>
);

/** 動画上の下線テロップ (編集時刻で配置)。 */
export const Telop: React.FC<{
  editStart: number;
  editDur: number;
  text: string;
}> = ({ editStart, editDur, text }) => {
  const { fps } = useVideoConfig();
  return (
    <Sequence
      from={Math.round(editStart * fps)}
      durationInFrames={Math.max(1, Math.round(editDur * fps))}
      layout="none"
    >
      <TelopInner editDur={editDur} text={text} />
    </Sequence>
  );
};

const TelopInner: React.FC<{ editDur: number; text: string }> = ({
  editDur,
  text,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const fade = Math.min(0.3, editDur / 4);
  const opacity = interpolate(
    frame,
    [0, fps * fade, fps * (editDur - fade), fps * editDur],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return (
    <div
      style={{
        position: "absolute",
        left: 80,
        bottom: 150,
        opacity,
        maxWidth: 1400,
        background: "rgba(6,10,18,0.9)",
        borderLeft: `6px solid ${COLORS.info}`,
        color: COLORS.text,
        fontSize: 34,
        fontWeight: 700,
        padding: "14px 26px",
        borderRadius: 10,
      }}
    >
      {text}
    </div>
  );
};

/** 動画上のハイライト矩形 (ポップイン)。 */
export const HighlightBox: React.FC<{
  editStart: number;
  editDur: number;
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
}> = ({ editStart, editDur, x, y, width, height, color }) => {
  const { fps } = useVideoConfig();
  return (
    <Sequence
      from={Math.round(editStart * fps)}
      durationInFrames={Math.max(1, Math.round(editDur * fps))}
      layout="none"
    >
      <HighlightInner x={x} y={y} width={width} height={height} color={color} />
    </Sequence>
  );
};

const HighlightInner: React.FC<{
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
}> = ({ x, y, width, height, color }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = interpolate(frame, [0, fps * 0.3], [0, 1], {
    extrapolateRight: "clamp",
  });
  const scale = interpolate(pop, [0, 1], [1.4, 1]);
  const opacity = interpolate(pop, [0, 1], [0, 1]);
  return (
    <div
      style={{
        position: "absolute",
        left: `${x}%`,
        top: `${y}%`,
        width: `${width}%`,
        height: `${height}%`,
        border: `4px solid ${color}`,
        borderRadius: 8,
        boxShadow: `0 0 12px ${color}88`,
        opacity,
        transform: `scale(${scale})`,
      }}
    />
  );
};
