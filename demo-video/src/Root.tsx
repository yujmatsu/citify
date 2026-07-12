import { Composition } from "remotion";
import { CitifyDemo } from "./compositions/CitifyDemo";
import { FPS, TOTAL_SEC } from "./data/scenes";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="CitifyDemo"
      component={CitifyDemo}
      durationInFrames={Math.max(1, Math.round(TOTAL_SEC * FPS))}
      fps={FPS}
      width={1920}
      height={1080}
    />
  );
};
