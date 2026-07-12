// 元動画の「ソース時刻」で指定したテロップ/ハイライトを、カット・速度変更後の
// 「編集時刻」へ写像するヘルパー (remotion-best-practices / edited-video-spec より)。

import type { VideoSegment } from "../data/scenes";

export type EditSegment = VideoSegment & { editStart: number; editDur: number };
export type EditRange = { editStart: number; editDur: number };

/** segments に編集時刻カーソル(editStart/editDur)を付与する。 */
export function buildEditSegments(segments: VideoSegment[]): EditSegment[] {
  let cursor = 0;
  return segments.map((s) => {
    const editDur = (s.srcEnd - s.srcStart) / s.speed;
    const editStart = cursor;
    cursor += editDur;
    return { ...s, editStart, editDur };
  });
}

/** ソース区間 [srcStart, srcEnd] を編集時刻の区間群へ写像 (カット境界で自動分割)。 */
export function mapSrcRangeToEdit(
  srcStart: number,
  srcEnd: number,
  editSegments: EditSegment[],
): EditRange[] {
  const results: EditRange[] = [];
  for (const seg of editSegments) {
    const overlapStart = Math.max(srcStart, seg.srcStart);
    const overlapEnd = Math.min(srcEnd, seg.srcEnd);
    if (overlapStart < overlapEnd) {
      const editStart =
        seg.editStart + (overlapStart - seg.srcStart) / seg.speed;
      const editEnd = seg.editStart + (overlapEnd - seg.srcStart) / seg.speed;
      results.push({ editStart, editDur: editEnd - editStart });
    }
  }
  return results;
}

/** 編集時刻で隣接する区間を1つに結合 (カット跨ぎのフェード点滅を防ぐ)。 */
export function coalesceRanges(ranges: EditRange[], fps: number): EditRange[] {
  if (ranges.length === 0) return [];
  const eps = 1 / fps + 1e-6;
  const out: EditRange[] = [{ ...ranges[0] }];
  for (let k = 1; k < ranges.length; k++) {
    const prev = out[out.length - 1];
    const cur = ranges[k];
    if (cur.editStart - (prev.editStart + prev.editDur) <= eps) {
      prev.editDur = cur.editStart + cur.editDur - prev.editStart;
    } else {
      out.push({ ...cur });
    }
  }
  return out;
}
