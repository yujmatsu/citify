import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { SCENES, sceneDuration } from "../data/scenes";
import { COLORS } from "../theme";
import { SceneRenderer } from "./SceneRenderer";

/** 全シーンを順に連結したデモ本編。尺はデータから累積 (ハードコードなし)。 */
export const CitifyDemo: React.FC = () => {
  const { fps } = useVideoConfig();
  let cursor = 0;
  return (
    <AbsoluteFill style={{ background: COLORS.bg }}>
      {SCENES.map((scene) => {
        const from = Math.round(cursor * fps);
        const durFrames = Math.max(1, Math.round(sceneDuration(scene) * fps));
        cursor += sceneDuration(scene);
        return (
          <Sequence
            key={scene.id}
            from={from}
            durationInFrames={durFrames}
            name={`${scene.chapter} ${scene.title}`}
          >
            <SceneRenderer scene={scene} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
