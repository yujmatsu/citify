# ミニプラン: Watcher 分析の非同期化 ＋ PDF(画面＋保存)

## 概要
- **タスクID**: TASK-ASYNC-PDF
- **目的**: 144-178s の同期待ちを解消。分析をバックグラウンド実行にし、完了で画面表示＋
  「PDFとして保存」できるようにする(アドバイザーが裏で調べてレポートを出す体験)。
- **完了条件**:
  1. `POST /run` が即時 202 を返し、分析は**バックグラウンド実行**→ Firestore 永続化
  2. フロントは「作成中…」表示で `GET /analysis` をポーリングし、**新 run_id 検知で結果表示**
  3. `/agent` に「🖨 PDFとして保存」= 印刷用に整形した**レポートのみ**を window.print
  4. PDF内容は永続(保存済み分析から都度描画)・ファイルは溜め込まない
  5. ruff / pytest / tsc / next build 全 green

## スコープ
### IN
- backend: `POST /run` → 202 + `BackgroundTasks` で `agent.run` を裏実行(既存永続化を流用)
- cloudbuild.yaml: `--no-cpu-throttling`(応答後も CPU 割当=背景タスク完走に必須)
- frontend api.ts: `runWatcher` を POST(202)→`/analysis` ポーリング(新 run_id まで・タイムアウト)
- frontend /agent: RunProgress 待ち演出は流用。`PDFとして保存`ボタン＋ chrome を `.no-print`
- globals.css: `@media print`(chrome 非表示・白背景・カード分割・印刷用タイトル＋AI注記)

### OUT(後続)
- メール送付(PII＋送信基盤。Option B=GCS保存はメール時に)
- サーバ側 .pdf 生成(reportlab+Noto)。今回はクライアント印刷でMVP

## 作業ステップ
1. [ ] api/main.py: `_execute_watcher_run_bg` 抽出 + `POST /run`→202+BackgroundTasks
2. [ ] cloudbuild.yaml: deploy に `--no-cpu-throttling`
3. [ ] api.ts: `runWatcher` を 202+ポーリング(prev run_id 差分・~4分上限)に
4. [ ] /agent: PDF保存ボタン(window.print)・chrome に no-print・印刷用 disclaimer
5. [ ] globals.css: @media print
6. [ ] tests: test_watcher_api POST /run を 202+背景実行に更新
7. [ ] 検証: ruff/pytest/tsc/build → push → 本番 smoke(非同期+印刷)

## リスク
| リスク | 対策 |
|---|---|
| Cloud Run 応答後の CPU スロットルで背景タスク停滞 | `--no-cpu-throttling`(min-instances=1 で常時割当)。本番 smoke で完走確認 |
| ポーリングが新 run_id を取り違える | run_id は実行毎に uuid。prev と差分で判定。~4分でタイムアウト→再試行導線 |
| 印刷でレーダー(SVG)やレイアウト崩れ | @media print でカード `break-inside:avoid`・chrome 非表示・色補正 |
| 背景タスク中にインスタンス縮退 | min-instances=1＋低トラフィック(デモ)で実害小。失敗時はポーリングtimeout |
