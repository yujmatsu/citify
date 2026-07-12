// デモ動画の全シーン定義。DEMO_SCRIPT.md 3分版 / NARRATION.md と1対1で対応。
//
// 編集フロー:
//  1. OBS 等で各シーンを画面録画 → demo-video/public/recordings/ に置く
//  2. 該当シーンの footage.src / segments / telops を設定 (下の例を参照)
//  3. voicebox で NARRATION.md の texts を生成 → public/narration/{id}_01.wav
//  4. NARRATION_READY = true にする
//  5. npm run studio でプレビュー → 調整 → npm run render:high

export type VideoSegment = { srcStart: number; srcEnd: number; speed: number };

/** 動画上に重ねる下線テロップ (ソース時刻で指定)。 */
export type Telop = { srcStart: number; srcEnd: number; text: string };

/** 動画上のハイライト矩形 (1920x1080 に対する % 座標)。 */
export type Highlight = {
  srcStart: number;
  srcEnd?: number;
  x: number;
  y: number;
  width: number;
  height: number;
  color?: string;
  label?: string;
};

export type Footage = {
  /** publicDir 相対パス。未設定ならプレースホルダ表示。例: "recordings/agent.mp4" */
  src?: string;
  segments?: VideoSegment[];
  telops?: Telop[];
  highlights?: Highlight[];
  /** ナレ再生中の録画音量 (0-1)。既定 0 = 録画はミュートしナレが音声を担う。 */
  narrationVideoVolume?: number;
  /** 動画がシーン尺より短い時、末尾フレームを durationSec まで静止保持する (スロー黒化の回避)。 */
  holdLastFrame?: boolean;
};

export type SceneKind = "title" | "footage" | "slide" | "end";

export type Scene = {
  id: string; // NARRATION.md のキーと一致 (ナレ音声 {id}_01.wav に対応)
  chapter: string; // ①〜⑥
  title: string;
  kind: SceneKind;
  durationSec: number; // フッテージ未設定時のプレースホルダ尺
  caption: string; // 焼き込み字幕 (音声OFF対策)
  hasNarration?: boolean;
  footage?: Footage;
  /** slide 用フルフレーム画像。未設定ならプレースホルダ。例: "slides/architecture.png" */
  image?: string;
  headline?: string; // title/end カードの大見出し
  subhead?: string; // title/end カードの小見出し
  showLogoBar?: boolean;
  showHumanReviewBadge?: boolean;
  record?: string; // 撮影する画面のヒント (プレースホルダに表示)
};

export const FPS = 30;

/** WAV 生成が済んだら true。false の間は字幕のみでプレビュー可能。 */
export const NARRATION_READY = true;

/** 章バッジ・プレースホルダ注記の表示。最終 render では false に。 */
export const DEV_OVERLAYS = false;

/** 焼き込み字幕の表示。false にするとサムネ/スクショ用に字幕なしで書き出せる (本編は true)。 */
export const SHOW_CAPTION = true;

export const SCENES: Scene[] = [
  {
    id: "s1_problem",
    chapter: "①",
    title: "課題提起",
    kind: "title",
    durationSec: 13.5,
    headline: "その議論、誰も読んでいない。",
    subhead: "あなたの街の議会で、先週なにが決まったか？",
    caption: "家賃補助も、子育ても、防災も——全部そこで決まっているのに。",
    hasNarration: true,
  },
  {
    id: "s2_concept",
    chapter: "②",
    title: "コンセプト",
    kind: "footage",
    durationSec: 23.5,
    caption:
      "Citify＝自治体の「今」を、あなた向けに翻訳して届ける AI プロダクト",
    hasNarration: true,
    footage: {
      src: "recordings/s2_concept.mp4",
      // 等速で src0→23.5 (着地→選択→エージェント始動)。VO「AIエージェントが動き…
      // 後半でお見せします」と整合の予告カット。スロー(<1x)は OffthreadVideo が黒くなるため不可。
      segments: [{ srcStart: 0, srcEnd: 23.5, speed: 1 }],
    },
    record: "トップ / でプリセット選択 → /feed へ遷移",
  },
  {
    id: "s2_feed",
    chapter: "②",
    title: "翻訳フィード",
    kind: "footage",
    durationSec: 13,
    caption: "議事録・プレスを AI が翻訳。関心×年代で採点し For You フィードへ",
    hasNarration: true,
    footage: {
      src: "recordings/s2_feed.mp4",
      segments: [{ srcStart: 0, srcEnd: 13, speed: 1 }],
    },
    record:
      "/feed「あなたの街」タブを 2〜3 枚スクロール (Imagen サムネ+3行サマリ)",
  },
  {
    id: "s2_detail",
    chapter: "②",
    title: "議題詳細 + RAG",
    kind: "footage",
    durationSec: 13.5,
    caption: "RAG が国会議事録から関連論戦を検索。原典リンクを必ず併記",
    hasNarration: true,
    footage: {
      src: "recordings/s2_detail.mp4",
      // 読み込み中(0-5s)を除外し「スコア→国会RAG→原典リンク」(src11-27.5)を 1.22x で。
      segments: [{ srcStart: 11, srcEnd: 27.5, speed: 1.22 }],
    },
    record: "/feed/[id] 詳細 (4軸スコア・国会RAG 3件・原典リンク・気になる)",
  },
  {
    id: "s3_watcher",
    chapter: "③",
    title: "Watcher（主役）",
    kind: "footage",
    durationSec: 17.5,
    caption: "中心は「街の見張り番」Watcher（ADK）。計画→並列実行→自己検証",
    hasNarration: true,
    footage: {
      src: "recordings/s3_watcher_trace.mp4",
      segments: [{ srcStart: 0, srcEnd: 129.2, speed: 7.38 }],
    },
    record:
      "/agent 自律トレース ※事前seedで即結論。トレースは別カット/早送りで凝縮",
  },
  {
    id: "s3_plan",
    chapter: "③",
    title: "結論 + アクションプラン",
    kind: "footage",
    durationSec: 15.5,
    caption: "結論＝「どの街が、あなたの何に合うか」＋アクションプラン",
    hasNarration: true,
    footage: {
      src: "recordings/s3_watcher_result.mp4",
      segments: [{ srcStart: 0, srcEnd: 15.5, speed: 1 }],
    },
    record: "分析結果カード+レーダー → /plan アクションプラン",
  },
  {
    id: "s4_ops",
    chapter: "④",
    title: "Ops crew — 同じ自律を運用に",
    kind: "footage",
    durationSec: 31.5,
    caption: "同じ自律の仕組みを「自分たちの運用の見張り」にも（/ops）",
    hasNarration: true,
    footage: {
      src: "recordings/s4_ops.mp4",
      // 動画19s<ナレ30.5s。等速で流し切り、末尾(クルー4ステップ+人間レビュー必須)を保持して payoff を乗せる。
      segments: [{ srcStart: 0, srcEnd: 19, speed: 1 }],
      holdLastFrame: true,
    },
    showHumanReviewBadge: true,
    record:
      "/ops 運用アセスメント (計画→3専門家並列→批判→人間レビュー必須バッジ)",
  },
  {
    id: "s5_arch",
    chapter: "⑤",
    title: "アーキ + CI/CD",
    kind: "slide",
    durationSec: 34.5,
    caption:
      "13 の AI エージェント／830 自治体・議会／4,500 件超の議題。全 Terraform・push で本番自動",
    hasNarration: true,
    image: "slides/architecture.png",
    showLogoBar: true,
    record:
      "docs/assets/architecture.png を public/slides/ にコピー + GitHub Actions/Cloud Build/Terraform 画面",
  },
  {
    id: "s6_closing",
    chapter: "⑥",
    title: "クロージング",
    kind: "end",
    durationSec: 13.5,
    headline: "Citify",
    subhead: "自分の街、自分の世代の話を、60秒で。",
    caption: "🏛️ Citify — 自分の街、自分の世代の話を、60秒で。",
    hasNarration: true,
  },
];

/** segments があれば実尺、なければ durationSec を返す。 */
export function sceneDuration(scene: Scene): number {
  // holdLastFrame 時は動画が durationSec より短く、末尾を Freeze で埋めるので durationSec を採用。
  if (scene.footage?.holdLastFrame) return scene.durationSec;
  const segs = scene.footage?.segments;
  if (segs && segs.length > 0) {
    return segs.reduce((sum, s) => sum + (s.srcEnd - s.srcStart) / s.speed, 0);
  }
  return scene.durationSec;
}

export const TOTAL_SEC = SCENES.reduce((sum, s) => sum + sceneDuration(s), 0);
