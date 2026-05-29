/**
 * 47 都道府県のタイルグリッド配置 (Plan X)。
 *
 * Japan Times / FT 等で使われる「タイル状日本地図」(tile-grid map) 方式を採用。
 * SVG 上の (col, row) 位置で各県をひとつの矩形タイルとして配置し、
 * Chloropleth 風に色付けして全国比較を可能にする。
 *
 * 採用理由:
 *   - TopoJSON (数 MB) なしで 47 県を表示可能
 *   - d3-geo の射影計算が不要 (純粋な grid 配置)
 *   - 各タイルが同一サイズなので「面積による視覚バイアス」が排除され比較しやすい
 *   - クリックターゲットが均一に大きく取れる (UX 上有利)
 */

export type PrefectureTile = {
  code: string; // 2 桁県コード
  row: number;
  col: number;
  name: string;
};

// 11 列 × 13 行 グリッド (col=0 が西、row=0 が北)
export const PREFECTURE_TILES: PrefectureTile[] = [
  { code: "01", row: 0, col: 9, name: "北海道" },
  { code: "02", row: 2, col: 8, name: "青森" },
  { code: "05", row: 3, col: 7, name: "秋田" },
  { code: "03", row: 3, col: 8, name: "岩手" },
  { code: "06", row: 4, col: 7, name: "山形" },
  { code: "04", row: 4, col: 8, name: "宮城" },
  { code: "07", row: 5, col: 8, name: "福島" },
  { code: "15", row: 5, col: 7, name: "新潟" },
  { code: "10", row: 6, col: 7, name: "群馬" },
  { code: "09", row: 6, col: 8, name: "栃木" },
  { code: "08", row: 6, col: 9, name: "茨城" },
  { code: "20", row: 7, col: 6, name: "長野" },
  { code: "11", row: 7, col: 7, name: "埼玉" },
  { code: "13", row: 7, col: 8, name: "東京" },
  { code: "12", row: 7, col: 9, name: "千葉" },
  { code: "16", row: 7, col: 5, name: "富山" },
  { code: "17", row: 7, col: 4, name: "石川" },
  { code: "19", row: 8, col: 7, name: "山梨" },
  { code: "14", row: 8, col: 8, name: "神奈川" },
  { code: "22", row: 8, col: 6, name: "静岡" },
  { code: "21", row: 8, col: 5, name: "岐阜" },
  { code: "18", row: 8, col: 4, name: "福井" },
  { code: "23", row: 9, col: 6, name: "愛知" },
  { code: "24", row: 9, col: 5, name: "三重" },
  { code: "25", row: 9, col: 4, name: "滋賀" },
  { code: "26", row: 9, col: 3, name: "京都" },
  { code: "27", row: 10, col: 3, name: "大阪" },
  { code: "28", row: 10, col: 2, name: "兵庫" },
  { code: "29", row: 10, col: 4, name: "奈良" },
  { code: "30", row: 10, col: 5, name: "和歌山" },
  { code: "31", row: 10, col: 1, name: "鳥取" },
  { code: "32", row: 11, col: 1, name: "島根" },
  { code: "33", row: 11, col: 2, name: "岡山" },
  { code: "34", row: 12, col: 1, name: "広島" },
  { code: "35", row: 12, col: 0, name: "山口" },
  { code: "36", row: 11, col: 3, name: "徳島" },
  { code: "37", row: 11, col: 4, name: "香川" },
  { code: "38", row: 12, col: 3, name: "愛媛" },
  { code: "39", row: 12, col: 4, name: "高知" },
  { code: "40", row: 12, col: 5, name: "福岡" }, // 西から並べ替え
  { code: "41", row: 12, col: 6, name: "佐賀" },
  { code: "42", row: 12, col: 7, name: "長崎" },
  { code: "44", row: 12, col: 8, name: "大分" },
  { code: "43", row: 13, col: 6, name: "熊本" },
  { code: "45", row: 13, col: 7, name: "宮崎" },
  { code: "46", row: 13, col: 5, name: "鹿児島" },
  { code: "47", row: 13, col: 0, name: "沖縄" },
];

export const GRID_COLS = 11;
export const GRID_ROWS = 14;
export const TILE_SIZE = 56;
export const TILE_GAP = 2;

/**
 * value を 0-1 に正規化した上で blue 系の色を返す (lower_is_better/higher_is_better で反転)。
 */
export function colorForRank(
  rank: number,
  total: number,
  direction: "lower_is_better" | "higher_is_better",
): string {
  // rank=1 が「最良」(direction 反映済みで sort 済み前提)
  const normalized = (total - rank) / Math.max(total - 1, 1); // 1 位 = 1.0, 最下位 = 0.0
  const _ = direction; // direction は既に sort で反映済 (この関数では reference 用)
  // blue-to-light gradient (彩度 + 明度)
  const lightness = 90 - normalized * 50; // 40 (deep) ~ 90 (light)
  const saturation = 35 + normalized * 35; // 35 ~ 70
  return `hsl(212, ${saturation}%, ${lightness}%)`;
}
