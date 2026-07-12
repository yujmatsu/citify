import {
  AbsoluteFill,
  Img,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type { Scene } from "../data/scenes";
import { COLORS } from "../theme";
import { PlaceholderPanel } from "./overlays";

/** タイトルカード (シーン①)。痛みのある問いを大きく提示。 */
export const TitleCard: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200 } });
  const y = interpolate(enter, [0, 1], [30, 0]);
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        background: `radial-gradient(circle at 50% 40%, #16203a 0%, ${COLORS.bg} 70%)`,
      }}
    >
      <div
        style={{
          opacity: enter,
          transform: `translateY(${y}px)`,
          textAlign: "center",
          padding: "0 120px",
        }}
      >
        {scene.headline ? (
          <div
            style={{
              fontSize: 82,
              fontWeight: 900,
              color: COLORS.text,
              lineHeight: 1.25,
            }}
          >
            {scene.headline}
          </div>
        ) : null}
        {scene.subhead ? (
          <div style={{ marginTop: 28, fontSize: 40, color: COLORS.sub }}>
            {scene.subhead}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

/** スライド (シーン⑤: アーキ図)。画像未配置ならプレースホルダ。 */
export const SlideCard: React.FC<{ scene: Scene }> = ({ scene }) => {
  if (!scene.image) {
    return <PlaceholderPanel kind="slide" scene={scene} />;
  }
  return (
    <AbsoluteFill style={{ background: COLORS.bg, padding: 60 }}>
      <Img
        src={staticFile(scene.image)}
        style={{ width: "100%", height: "100%", objectFit: "contain" }}
      />
    </AbsoluteFill>
  );
};

/** エンドカード (シーン⑥)。タグライン。 */
export const EndCard: React.FC<{ scene: Scene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const enter = spring({ frame, fps, config: { damping: 200 } });
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        background: `radial-gradient(circle at 50% 45%, #0f2a22 0%, ${COLORS.bg} 70%)`,
      }}
    >
      <div style={{ opacity: enter, textAlign: "center" }}>
        <div style={{ fontSize: 110, fontWeight: 900, color: COLORS.accent }}>
          🏛️ {scene.headline}
        </div>
        {scene.subhead ? (
          <div style={{ marginTop: 24, fontSize: 44, color: COLORS.text }}>
            {scene.subhead}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
