# Citify Workers — Cloud Run Job デプロイ

4 つの Pub/Sub subscriber worker を Cloud Run Job + Cloud Scheduler で永続稼働させる構成。

| Worker | 入力 subscription | 出力 topic | Cloud Run Job 名 |
|---|---|---|---|
| translator | `citify-speech-translate-sub` | `citify-speech-translated` | `citify-worker-translator` |
| relevance | `citify-speech-translated-sub` | `citify-speech-scored` | `citify-worker-relevance` |
| distributor | `citify-speech-scored-sub` | `citify-feed-snapshot` | `citify-worker-distributor` |
| bq-sink-scored | `citify-speech-scored-sub` | (BQ insert) | `citify-worker-bq-sink-scored` |

## アーキテクチャ

```
Cloud Scheduler (60 min interval, offset 0/5/10/15 min)
       ↓ HTTPS POST + OAuth (citify-api-runtime SA, roles/run.invoker)
Cloud Run Job (timeout 59 min, max_retries 0)
       ↓ container startup
docker run citify-worker:latest python -m agents.translator.worker ...
       ↓ blocking streaming pull
Pub/Sub subscription (exactly_once_delivery)
```

各 Job は 59 分稼働して終了。Scheduler が 60 分後に次インスタンスを起動。1 分の隙間はあるが Pub/Sub message は subscription に蓄積されるためロスなし。

## 初回デプロイ手順

```bash
cd /home/yujmatsu/projects/citify

# 1. image を build + push (Cloud Build 実行)
gcloud builds submit --config=cloudbuild-workers.yaml --region=asia-northeast1

# (初回のみ: Cloud Run Job リソースがまだ無いので update-jobs step は警告で済む)

# 2. Terraform で Cloud Run Job + Scheduler + IAM を反映
cd infra/env/dev
terraform apply  # 4 jobs + 4 schedulers + 2 IAM resources

# 3. (option) 即座に動作確認したい場合は手動 trigger
gcloud run jobs execute citify-worker-translator --region=asia-northeast1 --wait
```

## image 更新時

cloudbuild-workers.yaml の `update-jobs` step が自動で `gcloud run jobs update --image=NEW_TAG` を実行するため、Cloud Build を再実行するだけ：

```bash
gcloud builds submit --config=cloudbuild-workers.yaml --region=asia-northeast1
```

## 動作確認

```bash
# 各 Job の最新 execution の状態
for JOB in translator relevance distributor bq-sink-scored; do
  echo "=== $JOB ==="
  gcloud run jobs executions list \
    --job=citify-worker-$JOB \
    --region=asia-northeast1 \
    --limit=1
done

# Job のログ
gcloud logging read \
  'resource.type="cloud_run_job" resource.labels.job_name="citify-worker-translator"' \
  --limit=20 --format=json

# Scheduler の状態
gcloud scheduler jobs list --location=asia-northeast1
```

## トラブルシュート

| 症状 | 原因 | 対処 |
|---|---|---|
| 初回 apply で `image not found` | cloudbuild-workers.yaml 未実行 | 先に Cloud Build を実行 |
| Scheduler 起動するが Job が start しない | run.invoker / token_creator 権限不足 | `terraform apply` を再実行 |
| Job が即終了 | Pub/Sub auth エラー / Gemini quota | Cloud Logging で要因確認 |
| Job が timeout で kill | 想定動作 (59 分稼働 + Scheduler が次起動) | 監視不要 |
| INVALID_ACK_ID warning | exactly_once_delivery の既知 race condition | 無視 (実害なし) |

## relevance worker のペルソナ設定

現状は Terraform で 1 ペルソナ `demo-25-29` を hardcode (`住居/雇用/税/子育て`, `33000+00000`)。

将来 (Week 3+) は:
- Firestore に複数ユーザー登録
- relevance worker は subscription pull のたびに全ユーザー分 score を計算 (fan-out)
- 各ユーザーごとに ScoredSpeech 1 件 publish
