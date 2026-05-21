# Citify Workers — Cloud Run Job デプロイ

4 つの Pub/Sub subscriber worker を **コスト最小化**で Cloud Run Job として運用する構成。

| Worker | 入力 subscription | 出力 topic | Cloud Run Job 名 |
|---|---|---|---|
| translator | `citify-speech-translate-sub` | `citify-speech-translated` | `citify-worker-translator` |
| relevance | `citify-speech-translated-sub` | `citify-speech-scored` | `citify-worker-relevance` |
| distributor | `citify-speech-scored-distributor-sub` ⭐ | `citify-feed-snapshot` | `citify-worker-distributor` |
| bq-sink-scored | `citify-speech-scored-bq-sub` ⭐ | (BQ insert) | `citify-worker-bq-sink-scored` |

⭐ **`speech-scored` topic は distributor と bq_sink の 2 つの consumer を持つため、各 worker が独立した subscription を持つ fan-out パターン**。1 つの subscription を share すると Pub/Sub の competing consumers でメッセージが分配されてしまうため。

## 運用方針 (コスト優先)

```
[普段]
   Scheduler 全 paused → 月コスト ~$0
   Job リソース自体は存在するが何も実行されない

[必要時、手動 demo]
   ./apps/workers/scripts/toggle-schedulers.sh run-once
   → 4 worker を即座に起動 (各 59 分稼働) → コスト ~$0 (無料枠内)

[デモ期間 (1〜2 週間)]
   ./apps/workers/scripts/toggle-schedulers.sh resume
   → 1 日 1 回 09:00 JST 起動 → 月コスト ~$5
   期間終了時: ./apps/workers/scripts/toggle-schedulers.sh pause
```

## アーキテクチャ

```
Cloud Scheduler (cron: 0/5/10/15 9 * * *, paused by default)
       ↓ HTTPS POST + OAuth (citify-api-runtime SA + run.invoker)
Cloud Run Job (timeout 3540s = 59min, max_retries 0)
       ↓ container start
docker run citify-worker:latest python -m {worker_module} ...
       ↓ blocking streaming pull
Pub/Sub subscription (exactly_once_delivery)
```

各 Job は 59 分稼働して終了。期間中 Pub/Sub message は subscription に蓄積されるため、次の起動で確実に処理される (`exactly_once_delivery + retain 7 days`)。

## 初回デプロイ手順

⚠️ **必ず Cloud Build → Terraform の順で実行**。Cloud Run Job は image が存在しないと作成失敗。

```bash
cd /home/yujmatsu/projects/citify

# 1. image を build + push (Cloud Build 実行、初回 ~5-10 分)
gcloud builds submit --config=cloudbuild-workers.yaml --region=asia-northeast1

# 2. Terraform で Cloud Run Job + Scheduler (paused) + IAM を反映
cd infra/env/dev
terraform apply  # 4 jobs + 4 schedulers (paused) + 2 IAM
# 完了時点で Scheduler は全 paused 状態、コスト発生なし
```

## 日々の運用コマンド

### A. デモ前 (手動で 1 度動かしたい)

```bash
# 4 worker を 1 度ずつ実行 (background、59 分稼働)
./apps/workers/scripts/toggle-schedulers.sh run-once

# 続けて scraper publish
PYTHONPATH=. apps/api/.venv/bin/python -m scrapers.kaigiroku_net publish-speeches \
    --tenant prefokayama --council-id 177 --schedule-id 4 \
    --max-speeches 5 --project-id citify-dev \
    --topic citify-speech-translate --rate-limit-sec 1

# 数分待つと BQ に反映
bq query --project_id=citify-dev --use_legacy_sql=false '
SELECT speech_id, title, relevance_score, matched_interests
FROM `citify-dev.citify_curated.scored_speeches`
WHERE user_id = "demo-25-29"
ORDER BY ingested_at DESC LIMIT 10
'
```

### B. デモ期間中 (毎日自動起動を有効化)

```bash
# Scheduler を起動 (1 日 1 回 09:00 JST から自動稼働)
./apps/workers/scripts/toggle-schedulers.sh resume

# 状態確認
./apps/workers/scripts/toggle-schedulers.sh status

# デモ期間終了時
./apps/workers/scripts/toggle-schedulers.sh pause
```

### C. Terraform で flip (より厳密、CI 統合可)

```bash
cd /home/yujmatsu/projects/citify/infra/env/dev

# 起動 (デモ期間開始)
terraform apply -var schedulers_paused=false

# 停止 (デモ期間終了)
terraform apply -var schedulers_paused=true   # ← default なので引数省略可
```

## コスト見積もり

| モード | 月コスト | 解説 |
|---|---|---|
| **全 Scheduler paused (default)** | **~$0** | Job リソース存在のみ、課金なし |
| 手動 trigger のみ (`run-once` × 数回) | ~$0 | 4 exec × 数回 = 無料枠内 |
| Scheduler resume (1 日 1 回 09:00) | ~$5 | 120 exec/月、CPU 一部超過、メモリ無料枠内 |
| (参考) 1 時間ごと自動 | ~$265 | hackathon scope では非推奨 |

無料枠 (毎月):
- Cloud Run Job: **240,000 vCPU-sec** + **450,000 GiB-sec**
- 1 worker 59 分 = 3,540 vCPU-sec (vCPU 1 個 / 3540s)
- 240,000 / 3,540 ≈ **67 executions / 月まで無料**

## image 更新時

```bash
cd /home/yujmatsu/projects/citify
gcloud builds submit --config=cloudbuild-workers.yaml --region=asia-northeast1
# update-jobs step が全 4 Job の image を自動更新
```

## トラブルシュート

| 症状 | 原因 | 対処 |
|---|---|---|
| 初回 apply で `image not found` | cloudbuild-workers.yaml 未実行 | 先に Cloud Build を実行 |
| `invalid image name "...workers:"` | `${COMMIT_SHA}` が空 (手動 submit) | `BUILD_ID` 採用済み (修正反映確認) |
| Scheduler 起動するが Job が start しない | run.invoker / token_creator 権限不足 | terraform apply を再実行 |
| Job が即終了 | Pub/Sub auth エラー / Gemini quota | Cloud Logging で要因確認 |
| Job が timeout で kill | 想定動作 (59 分稼働 + Scheduler が次起動) | 監視不要 |
| INVALID_ACK_ID warning | exactly_once_delivery の既知 race condition | 無視 (実害なし) |
| `terraform apply` partial state で Job が残骸 | image なしで作成失敗 | README の「リカバリ手順」参照 |

## デプロイが途中で失敗した場合のリカバリ

### ケース 1: cloudbuild で image push エラー
変数 (`${COMMIT_SHA}` 等) が空文字になっている。現状は `BUILD_ID` 採用済み、最新版で再実行。

### ケース 2: terraform apply で `Image not found`
Cloud Build が先に走っていない。Cloud Build 成功後に terraform apply 再実行。

### ケース 3: terraform apply が partial に進んで Job が "error state" になった

```bash
# 失敗した Job を確認
gcloud run jobs list --region=asia-northeast1 | grep citify-worker

# Terraform state からも除外
cd /home/yujmatsu/projects/citify/infra/env/dev
terraform state rm 'google_cloud_run_v2_job.workers["translator"]'
terraform state rm 'google_cloud_run_v2_job.workers["relevance"]'
terraform state rm 'google_cloud_run_v2_job.workers["distributor"]'
terraform state rm 'google_cloud_run_v2_job.workers["bq-sink-scored"]'

# image push されているか確認
gcloud artifacts docker images list \
  asia-northeast1-docker.pkg.dev/citify-dev/citify-api/workers \
  --include-tags --limit=5

# 再 apply
terraform apply
```

## relevance worker のペルソナ設定

現状は Terraform で 1 ペルソナ `demo-25-29` を hardcode (`住居/雇用/税/子育て`, `33000+00000`)。

将来 (Week 3+) は:
- Firestore に複数ユーザー登録
- relevance worker は subscription pull のたびに全ユーザー分 score を計算 (fan-out)
- 各ユーザーごとに ScoredSpeech 1 件 publish
