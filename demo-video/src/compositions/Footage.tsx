import {
  AbsoluteFill,
  Freeze,
  OffthreadVideo,
  Sequence,
  staticFile,
  useVideoConfig,
} from "remotion";
import { HighlightBox, PlaceholderPanel, Telop } from "../components/overlays";
import { type Scene, sceneDuration } from "../data/scenes";
import {
  buildEditSegments,
  coalesceRanges,
  mapSrcRangeToEdit,
} from "../lib/edit";

/** 画面録画を編集(カット/速度/テロップ/ハイライト)して表示。src 未設定ならプレースホルダ。 */
export const Footage: React.FC<{ scene: Scene }> = ({ scene }) => {
  const { fps } = useVideoConfig();
  const f = scene.footage;

  if (!f?.src) {
    return <PlaceholderPanel kind="footage" scene={scene} />;
  }
  const src = f.src;

  const segments =
    f.segments && f.segments.length > 0
      ? f.segments
      : [{ srcStart: 0, srcEnd: sceneDuration(scene), speed: 1 }];
  const editSegments = buildEditSegments(segments);
  const videoVolume = f.narrationVideoVolume ?? 0; // 既定: 録画はミュート (ナレが音声)

  const telopAppearances = (f.telops ?? []).flatMap((t) =>
    coalesceRanges(
      mapSrcRangeToEdit(t.srcStart, t.srcEnd, editSegments),
      fps,
    ).map((r) => ({ ...r, text: t.text })),
  );

  const maxSrcEnd = Math.max(...segments.map((s) => s.srcEnd));
  const highlightAppearances = (f.highlights ?? []).flatMap((h) =>
    coalesceRanges(
      mapSrcRangeToEdit(h.srcStart, h.srcEnd ?? maxSrcEnd, editSegments),
      fps,
    ).map((r) => ({
      ...r,
      x: h.x,
      y: h.y,
      width: h.width,
      height: h.height,
      color: h.color ?? "#ff4444",
    })),
  );

  // holdLastFrame: 動画尺 < シーン尺のとき、末尾フレームを Freeze で埋める。
  const videoEditDur = editSegments.reduce(
    (m, seg) => Math.max(m, seg.editStart + seg.editDur),
    0,
  );
  const holdGap = f.holdLastFrame
    ? Math.max(0, sceneDuration(scene) - videoEditDur)
    : 0;
  const lastSrcFrame = Math.max(
    0,
    Math.round((segments[segments.length - 1]?.srcEnd ?? 0) * fps) - 1,
  );

  return (
    <AbsoluteFill style={{ background: "#000" }}>
      {editSegments.map((seg, i) => (
        <Sequence
          key={`seg-${i}`}
          from={Math.round(seg.editStart * fps)}
          durationInFrames={Math.max(1, Math.round(seg.editDur * fps))}
        >
          <AbsoluteFill>
            <OffthreadVideo
              src={staticFile(src)}
              startFrom={Math.round(seg.srcStart * fps)}
              endAt={Math.round(seg.srcEnd * fps)}
              playbackRate={seg.speed}
              volume={() => (seg.speed > 2.5 ? 0 : videoVolume)}
              style={{ width: "100%", height: "100%", objectFit: "contain" }}
            />
          </AbsoluteFill>
        </Sequence>
      ))}

      {holdGap > 0 ? (
        <Sequence
          from={Math.round(videoEditDur * fps)}
          durationInFrames={Math.max(1, Math.round(holdGap * fps))}
        >
          <AbsoluteFill>
            <Freeze frame={lastSrcFrame}>
              <OffthreadVideo
                src={staticFile(src)}
                style={{ width: "100%", height: "100%", objectFit: "contain" }}
              />
            </Freeze>
          </AbsoluteFill>
        </Sequence>
      ) : null}

      {highlightAppearances.map((h, i) => (
        <HighlightBox key={`hl-${i}`} {...h} />
      ))}
      {telopAppearances.map((t, i) => (
        <Telop
          key={`tl-${i}`}
          editStart={t.editStart}
          editDur={t.editDur}
          text={t.text}
        />
      ))}
    </AbsoluteFill>
  );
};
