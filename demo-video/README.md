# Citify 提出用デモ動画 (Remotion)

`docs/DEMO_SCRIPT.md` 3分版 / `docs/submission/NARRATION.md` を、画面録画にテロップ・字幕・ナレーション(voicebox)を重畳して 1 本の mp4 にする編集プロジェクト。

- 出力: `CitifyDemo` (1920×1080 / 30fps / 3分)
- 各シーンは `src/data/scenes.ts` の `SCENES`（9シーン = NARRATION の 9 セグメント）に対応
- **編集は基本 `src/data/scenes.ts` だけを触る**（合成ロジックは触らない）

---

## セットアップ

```bash
cd demo-video
npm install
npm run studio     # http://localhost:3000 でプレビュー
```

素材が無くても起動できる（footage/画像はプレースホルダ、字幕のみ）。まず全体尺・字幕タイミングを確認してから素材を差し込む。

---

## 制作フロー

### 1. 画面録画 (あなた)
OBS 等で各シーンを録画 → `public/recordings/` に置く（ASCII ファイル名推奨）。撮影する画面は Studio のプレースホルダに「撮影: …」ヒントが出る。`docs/DEMO_SCRIPT.md §0.4` の事前 seed（当日）を必ず実施。

### 2. ナレーション生成 (voicebox / Windows)
1. Windows で Voicebox を起動 → Qwen3-TTS 1.7B をロード
2. `voice_type:"preset"` でプロファイル作成（参照音声不要）→ `profile_id` を控える
3. `~/.claude/skills/voicebox/templates/batch_generate.py` の `texts` に **`docs/submission/NARRATION.md` の dict** を貼付、`PROFILE_ID` と `OUTPUT_DIR = Path("<repo>/demo-video/public/narration")` を設定して実行
4. 生成物: `s1_problem_01.wav … s6_closing_01.wav`（scenes.ts が参照する命名と一致）
5. `src/data/scenes.ts` の `NARRATION_READY = true` にする

> NAT の WSL2 から Windows の Voicebox(127.0.0.1) に届かない場合は、ミラーモード（`%UserProfile%\.wslconfig` に `[wsl2]`/`networkingMode=mirrored` → `wsl --shutdown`）か、Windows 側生成 → `/mnt/c/...` から `public/narration/` へコピー。

### 3. シーンごとに素材を差し込む (`src/data/scenes.ts`)
```ts
// footage シーンの例:
footage: {
  src: "recordings/agent.mp4",
  // カット・速度: ソース時刻(秒)で指定
  segments: [
    { srcStart: 0, srcEnd: 8, speed: 1 },
    { srcStart: 20, srcEnd: 90, speed: 4 }, // 待ち時間を4倍速で凝縮
  ],
  // テロップ・ハイライトもソース時刻。カット跨ぎは自動分割される
  telops: [{ srcStart: 2, srcEnd: 6, text: "計画→並列実行→自己検証" }],
},
```
スライド(⑤)は `image: "slides/architecture.png"`（`docs/assets/architecture.png` をコピー）。

### 4. プレビュー & レンダリング
```bash
npm run studio       # 調整。scenes.ts を保存すると即反映
npm run render:high  # out/citify-demo.mp4 を書き出し
```

---

## フラグ (`src/data/scenes.ts`)

| フラグ | 意味 |
|---|---|
| `NARRATION_READY` | WAV 生成後 `true`。false の間は字幕のみで再生 |
| `DEV_OVERLAYS` | 章バッジ等の編集用オーバーレイ。**最終 render 前に `false`** |

## 命名規約

- 録画: `public/recordings/*.mp4`
- ナレ: `public/narration/{sceneId}_01.wav`（例 `s3_watcher_01.wav`）
- スライド: `public/slides/*.png`

（`recordings/` `narration/` `slides/` の中身は `.gitignore` 済み。コミットされるのはコードのみ）

## 倫理・提出チェック（`docs/DEMO_SCRIPT.md §3` と揃える）
- [ ] AI 生成画像に「AI 生成」ラベルが映る
- [ ] 政治家の顔・名前が映らない
- [ ] Veo・未実装機能への言及ゼロ（口頭・字幕・ロゴ全て）
- [ ] 3 分以内 / 字幕が全ナレに対応
