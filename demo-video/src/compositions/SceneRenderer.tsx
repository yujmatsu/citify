import { AbsoluteFill, Audio, staticFile } from "remotion";
import { EndCard, SlideCard, TitleCard } from "../components/cards";
import {
  Caption,
  ChapterBadge,
  HumanReviewBadge,
  TechLogoBar,
} from "../components/overlays";
import {
  DEV_OVERLAYS,
  NARRATION_READY,
  type Scene,
  sceneDuration,
  SHOW_CAPTION,
} from "../data/scenes";
import { COLORS, FONT_FAMILY } from "../theme";
import { Footage } from "./Footage";

/** 1 シーンを種別に応じて描画し、字幕・ナレ・章バッジ等を重ねる。 */
export const SceneRenderer: React.FC<{ scene: Scene }> = ({ scene }) => {
  const dur = sceneDuration(scene);
  return (
    <AbsoluteFill style={{ background: COLORS.bg, fontFamily: FONT_FAMILY }}>
      {scene.kind === "title" ? <TitleCard scene={scene} /> : null}
      {scene.kind === "footage" ? <Footage scene={scene} /> : null}
      {scene.kind === "slide" ? <SlideCard scene={scene} /> : null}
      {scene.kind === "end" ? <EndCard scene={scene} /> : null}

      {scene.showLogoBar ? <TechLogoBar /> : null}
      {scene.showHumanReviewBadge ? <HumanReviewBadge /> : null}

      {SHOW_CAPTION ? <Caption text={scene.caption} durationSec={dur} /> : null}

      {scene.hasNarration && NARRATION_READY ? (
        <Audio src={staticFile(`narration/${scene.id}_01.wav`)} />
      ) : null}

      {DEV_OVERLAYS ? (
        <ChapterBadge chapter={scene.chapter} title={scene.title} />
      ) : null}
    </AbsoluteFill>
  );
};
