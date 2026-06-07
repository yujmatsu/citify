# ミニプラン: Watcher v2 P5 — 日次先回り Cloud Run Job (A3)

## 概要
- **タスクID**: TASK-WATCHERV2-P5(設計 §8 P5)
- **目的**: 全ユーザーの watchlist を毎朝走査し WatcherAgent を実行・保存。ホームを事前計算→即表示、
  前回との変化検知(P4)を毎日自動化 = "先回りで見張る"。
- **完了条件**:
  1. `agents/watcher/daily_job.py` が watchlist 全件を実行・persist(graceful、1ユーザー失敗で全体止めない)
  2. Cloud Run Job + Scheduler(既存 worker パターン)で毎朝実行
  3. workers イメージに google-adk / google-cloud-firestore 追加(watcher 実行・保存に必須)
  4. pytest green(daily_job ロジックを mock 検証)

## スコープ
### IN
- `agents/watcher/repo.py`: `list_all_watchlists()` (user_watchlist 全件)
- `agents/watcher/daily_job.py`: 全 watchlist を **逐次**実行(quota安全)、街名は BQ から解決、graceful
- `apps/workers/Dockerfile`: `google-adk google-cloud-firestore` 追加
- `infra/env/dev/main.tf`: `local.workers` に `watcher-daily`(Job+Scheduler が for_each で生成)
### OUT(後続)
- 並列実行・通知(メール/Push)・イベント駆動(Pub/Sub)

## 作業ステップ
1. [ ] repo.list_all_watchlists()
2. [ ] daily_job.py (enumerate → run → persist、街名解決、ログ集計)
3. [ ] Dockerfile に adk/firestore 追加
4. [ ] terraform local.workers に watcher-daily 追加(schedule 9:20 JST = pipeline 後)
5. [ ] テスト(daily_job を repo/agent mock で)+ 検証

## デプロイ(ユーザー)
1. `gcloud builds submit --config=cloudbuild-workers.yaml --region=asia-northeast1 .`(workers image 再ビルド)
2. `terraform apply`(watcher-daily Job + Scheduler 追加)
3. (任意) `gcloud run jobs execute citify-worker-watcher-daily --region=asia-northeast1`(手動実行で確認)

## リスク
| リスク | 対策 |
|---|---|
| ユーザー多数でJob timeout | 逐次 + graceful。デモは少数。必要なら job timeout 延長 or 並列度2 |
| quota 429 (LLM多コール×ユーザー) | 逐次実行(同時多発を避ける)。memory の 429既往に配慮 |
| workers image に依存不足 | adk/firestore を Dockerfile に追加(本miniplanで対応) |
| 街名がコード表示 | daily_job が BQ で code→name を解決し town_names 渡す |
