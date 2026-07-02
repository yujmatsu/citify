/** おすすめ自治体 (議題データが豊富な街)。
 *
 * BigQuery 上のフィードデータ量が多い自治体を手動でピックアップ (2026-07-02 時点)。
 */

export const RECOMMENDED_MUNICIPALITIES = [
  { code: "33100", name: "岡山市" },
  { code: "01100", name: "札幌市" },
  { code: "38201", name: "松山市" },
  { code: "14130", name: "川崎市" },
  { code: "27100", name: "大阪市" },
  { code: "40130", name: "福岡市" },
] as const;
