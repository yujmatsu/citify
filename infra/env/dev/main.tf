# Citify dev 環境 — Terraform エントリポイント
#
# Week 1 Day 1 (5/26): DevOps 動線完成のためのリソース群
#   - GCS state bucket (本ファイル外で gcloud 経由で先に作成)
#   - Artifact Registry repo (Docker images)
#   - Service Account x 2 (cloud_build_deployer / citify_api_runtime)
#   - IAM bindings (最小権限主義)
#   - Cloud Build Trigger (main push -> citify-api 自動デプロイ)

terraform {
  required_version = ">= 1.7"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.10"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.10"
    }
  }

  # GCS リモートステート (Week 1 Day 1 で有効化)
  # 前提: `gcloud storage buckets create gs://citify-dev-tf-state` を事前実行
  backend "gcs" {
    bucket = "citify-dev-tf-state"
    prefix = "env/dev"
  }
}

# ---------------------------------------------------------------------------
# Provider 設定
# ---------------------------------------------------------------------------
provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Locals: 共通ラベル(全リソースに付与、`AGENTS.md §4.3` 準拠)
# ---------------------------------------------------------------------------
locals {
  common_labels = {
    project    = "citify"
    env        = var.env
    managed_by = "terraform"
  }

  # cloud-build-deployer SA に付与する project-level role
  cb_deployer_roles = [
    "roles/cloudbuild.builds.builder", # Cloud Build worker
    "roles/run.admin",                 # Cloud Run deploy + invoker IAM (--allow-unauthenticated 用)
    "roles/artifactregistry.writer",   # Docker image push
    "roles/logging.logWriter",         # Cloud Build logs (CLOUD_LOGGING_ONLY)
  ]

  # citify-api-runtime SA に付与する project-level role (最小権限)
  runtime_roles = [
    "roles/aiplatform.user",              # Vertex AI / Gemini 呼び出し
    "roles/secretmanager.secretAccessor", # Secret Manager 連携 (Week 1 後半)
    "roles/logging.logWriter",            # 構造化ログ書き込み
    "roles/cloudtrace.agent",             # Cloud Trace export
  ]
}

# ---------------------------------------------------------------------------
# Artifact Registry: citify-api Docker image repo
# ---------------------------------------------------------------------------
resource "google_artifact_registry_repository" "api" {
  location      = var.region
  repository_id = "citify-api"
  description   = "Citify API container images (built by Cloud Build trigger)"
  format        = "DOCKER"
  labels        = local.common_labels
}

# ---------------------------------------------------------------------------
# Service Accounts
# ---------------------------------------------------------------------------
# Cloud Build 実行 ID: build -> push -> Cloud Run deploy を行う
resource "google_service_account" "cloud_build_deployer" {
  account_id   = "cloud-build-deployer"
  display_name = "Cloud Build Deployer (Citify)"
  description  = "Cloud Build trigger 'citify-api-main' の実行 ID"
}

# Cloud Run 実行 ID: 最小権限、Vertex AI/Secret Manager 等の Citify API ランタイム
resource "google_service_account" "citify_api_runtime" {
  account_id   = "citify-api-runtime"
  display_name = "Citify API Runtime"
  description  = "Cloud Run citify-api サービスの最小権限ランタイム SA"
}

# ---------------------------------------------------------------------------
# IAM: cloud-build-deployer に必要な project-level role を付与
# ---------------------------------------------------------------------------
resource "google_project_iam_member" "cb_deployer" {
  for_each = toset(local.cb_deployer_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cloud_build_deployer.email}"
}

# cloud-build-deployer が citify-api-runtime を Cloud Run service に attach できるように
# (Cloud Run の --service-account 指定時に必須)
resource "google_service_account_iam_member" "cb_act_as_runtime" {
  service_account_id = google_service_account.citify_api_runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.cloud_build_deployer.email}"
}

# ---------------------------------------------------------------------------
# IAM: citify-api-runtime に必要な project-level role を付与 (最小)
# ---------------------------------------------------------------------------
resource "google_project_iam_member" "runtime" {
  for_each = toset(local.runtime_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# ---------------------------------------------------------------------------
# Cloud Build Trigger: main push -> citify-api 自動デプロイ
# ---------------------------------------------------------------------------
# 前提: Cloud Build の GitHub App 連携を Cloud Console で 1 回手動接続する必要あり
#   1. https://console.cloud.google.com/cloud-build/triggers?project=citify-dev
#   2. "Connect Repository" → GitHub (Cloud Build GitHub App) → Authorize → yujmatsu/citify
#   3. 接続のみ完了させ、Trigger 作成は次の `terraform apply` で実施
resource "google_cloudbuild_trigger" "api_main" {
  name        = "citify-api-main"
  description = "main push (apps/api 配下変更時) で citify-api を build -> push -> deploy"

  github {
    owner = var.github_owner
    name  = var.github_repo

    push {
      branch = "^main$"
    }
  }

  filename = "cloudbuild.yaml"

  service_account = google_service_account.cloud_build_deployer.id

  # apps/api 配下と cloudbuild.yaml の変更時のみ走らせる
  # (tasks.json / docs / README 等の変更で build を走らせない)
  included_files = [
    "apps/api/**",
    "cloudbuild.yaml",
  ]

  depends_on = [
    google_project_iam_member.cb_deployer,
    google_service_account_iam_member.cb_act_as_runtime,
    google_artifact_registry_repository.api,
  ]
}

# ---------------------------------------------------------------------------
# BigQuery: 生データ dataset + kokkai_speeches テーブル (Phase C)
# ---------------------------------------------------------------------------
# 設計方針 (docs/DATA_SOURCES.md §0.3 準拠):
#   - dataset citify_raw: 議事録・プレス等の生データ集約 (asia-northeast1)
#   - source 別に table を分離 (kokkai_speeches / kaigiroku_speeches など)
#   - partition by meeting_date (DATE): 期間スキャン最小化
#   - cluster by municipality_code, source: 自治体×ソース絞込で高速
resource "google_bigquery_dataset" "raw" {
  dataset_id  = "citify_raw"
  location    = var.region
  description = "Citify 生データ (議事録 / プレスリリース)。BQ クエリ料金最小化のため Tokyo に配置"
  labels      = local.common_labels

  # 開発中は dataset 内のテーブル削除を許容 (prod では false)
  delete_contents_on_destroy = false

  # citify-api-runtime SA がクエリできるよう access 付与
  access {
    role          = "OWNER"
    special_group = "projectOwners"
  }
  access {
    role          = "WRITER"
    user_by_email = google_service_account.citify_api_runtime.email
  }
  access {
    role          = "READER"
    special_group = "projectReaders"
  }
}

resource "google_bigquery_table" "kokkai_speeches" {
  dataset_id          = google_bigquery_dataset.raw.dataset_id
  table_id            = "kokkai_speeches"
  description         = "国会会議録 検索 API から取得した発言レコード (source=kokkai 固定、municipality_code='00000')"
  deletion_protection = false # 開発中は破棄しやすく

  time_partitioning {
    type  = "DAY"
    field = "meeting_date"
  }

  clustering = ["municipality_code", "source"]

  schema = jsonencode([
    { name = "id", type = "STRING", mode = "REQUIRED", description = "speechID (国会 API の一意 ID)" },
    { name = "source", type = "STRING", mode = "REQUIRED", description = "データソース識別子 ('kokkai' 固定)" },
    { name = "municipality_code", type = "STRING", mode = "NULLABLE", description = "自治体コード ('00000' = 国会)" },
    { name = "session", type = "INTEGER", mode = "NULLABLE", description = "国会回次" },
    { name = "name_of_house", type = "STRING", mode = "NULLABLE", description = "衆議院 / 参議院" },
    { name = "name_of_meeting", type = "STRING", mode = "NULLABLE", description = "本会議 / 予算委員会 等" },
    { name = "issue", type = "STRING", mode = "NULLABLE", description = "会議号数" },
    { name = "meeting_date", type = "DATE", mode = "NULLABLE", description = "開催日 (partition key)" },
    { name = "speech_order", type = "INTEGER", mode = "NULLABLE", description = "同一会議内の発言順序" },
    { name = "speaker", type = "STRING", mode = "NULLABLE", description = "発言者名" },
    { name = "speaker_yomi", type = "STRING", mode = "NULLABLE", description = "発言者名 (読み仮名)" },
    { name = "speaker_group", type = "STRING", mode = "NULLABLE", description = "所属政党" },
    { name = "speaker_position", type = "STRING", mode = "NULLABLE", description = "役職" },
    { name = "speech", type = "STRING", mode = "NULLABLE", description = "発言本文 (倫理: 内部 RAG のみ、転載禁止)" },
    { name = "start_page", type = "INTEGER", mode = "NULLABLE" },
    { name = "speech_url", type = "STRING", mode = "NULLABLE", description = "発言原典 URL" },
    { name = "meeting_url", type = "STRING", mode = "NULLABLE", description = "会議録原典 URL" },
    { name = "raw_json", type = "STRING", mode = "NULLABLE", description = "取得時のオリジナル JSON (デバッグ用)" },
    { name = "fetched_at", type = "TIMESTAMP", mode = "REQUIRED", description = "取得タイムスタンプ (UTC)" },
  ])

  labels = local.common_labels
}

# citify-api-runtime に BigQuery ジョブ実行権限 (クエリ料金は project に紐づく)
resource "google_project_iam_member" "runtime_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# ---------------------------------------------------------------------------
# GCS: RAG corpus 取り込み用 staging bucket (Phase D)
# ---------------------------------------------------------------------------
# Vertex AI RAG Engine は GCS から file を import するため、BQ から export した
# .txt ファイルを一時格納する bucket。
#
# 設計方針:
#   - asia-northeast1 (Tokyo) で RAG corpus と同 region
#   - uniform_bucket_level_access = true (オブジェクト ACL を使わない)
#   - lifecycle: 30 日後に自動削除 (corpus に import 済みなら staging 不要)
#   - versioning OFF (一時データのため)
resource "google_storage_bucket" "rag_staging" {
  name                        = "${var.project_id}-rag-staging"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true # dev は terraform destroy で消せるように

  labels = local.common_labels

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

# citify-api-runtime に bucket の read 権限 (RAG Engine が import 時に読む)
resource "google_storage_bucket_iam_member" "rag_staging_runtime_reader" {
  bucket = google_storage_bucket.rag_staging.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# citify-api-runtime に bucket の write 権限 (BQ → GCS export 時に書く)
resource "google_storage_bucket_iam_member" "rag_staging_runtime_writer" {
  bucket = google_storage_bucket.rag_staging.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# Vertex AI の Google 管理サービスアカウントへの bucket read 権限 (Phase D 検証で動作確認済)。
#
# 実際の SA 名: `service-46070204654@gcp-sa-aiplatform.iam.gserviceaccount.com`
# (当初予測の `gcp-sa-vertex-rag` ではなく aiplatform 一般 SA を RAG が使う)
#
# プロビジョニング履歴: 2026-05-21 に
#    `gcloud beta services identity create --service=aiplatform.googleapis.com`
# で明示作成 (corpus 自動 provision されなかったため手動で実行)。新規プロジェクトで
# Terraform apply 失敗する場合は同コマンドで再現可能。
resource "google_storage_bucket_iam_member" "rag_staging_aiplatform_reader" {
  bucket = google_storage_bucket.rag_staging.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:service-46070204654@gcp-sa-aiplatform.iam.gserviceaccount.com"
}

# ---------------------------------------------------------------------------
# Pub/Sub: A-4 → A-5 → A-6 のエージェント間メッセージング (Phase N)
# ---------------------------------------------------------------------------
# パイプライン:
#   scrapers (kaigiroku_net / kokkai / press_rss)
#       → publish to "citify-speech-translate" topic
#       → A-5 (translator worker, Cloud Run)
#           subscribe "citify-speech-translate-sub"
#           publish to "citify-speech-translated" topic
#       → A-6 (relevance scorer worker, 将来)
#           subscribe "citify-speech-translated-sub"
#
# 設計方針:
#   - DLQ (Dead Letter Queue) を 1 トピック分用意、5 回 nack で送信
#   - message_retention = 7 days (議事録量を考えると十分)
#   - ack_deadline = 60 sec (翻訳に 30 秒程度かかる)
#   - exactly_once_delivery = true (BQ への重複書き込みを避けるため)

# --- Topic: speech-translate (A-5 入力) ---
resource "google_pubsub_topic" "speech_translate" {
  name = "citify-speech-translate"

  message_retention_duration = "604800s" # 7 days

  labels = local.common_labels
}

# --- DLQ Topic (5 回失敗時の送信先) ---
resource "google_pubsub_topic" "speech_translate_dlq" {
  name = "citify-speech-translate-dlq"

  message_retention_duration = "604800s" # 7 days

  labels = merge(local.common_labels, { purpose = "dlq" })
}

# --- Subscription: speech-translate-sub (A-5 worker pull) ---
resource "google_pubsub_subscription" "speech_translate_sub" {
  name  = "citify-speech-translate-sub"
  topic = google_pubsub_topic.speech_translate.id

  ack_deadline_seconds         = 60 # 翻訳 ~30 sec + 余裕
  message_retention_duration   = "604800s"
  enable_message_ordering      = false
  enable_exactly_once_delivery = true

  expiration_policy {
    ttl = "" # 永続化 (空文字 = never expire)
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.speech_translate_dlq.id
    max_delivery_attempts = 5
  }

  labels = local.common_labels
}

# --- Topic: speech-translated (A-5 出力 / A-6 入力) ---
resource "google_pubsub_topic" "speech_translated" {
  name = "citify-speech-translated"

  message_retention_duration = "604800s"

  labels = local.common_labels
}

resource "google_pubsub_subscription" "speech_translated_sub" {
  name  = "citify-speech-translated-sub"
  topic = google_pubsub_topic.speech_translated.id

  ack_deadline_seconds         = 30
  message_retention_duration   = "604800s"
  enable_exactly_once_delivery = true

  expiration_policy {
    ttl = ""
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  labels = local.common_labels
}

# --- IAM: citify-api-runtime に publish + subscribe 権限 ---
resource "google_pubsub_topic_iam_member" "runtime_publish_translate" {
  topic  = google_pubsub_topic.speech_translate.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

resource "google_pubsub_subscription_iam_member" "runtime_subscribe_translate" {
  subscription = google_pubsub_subscription.speech_translate_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

resource "google_pubsub_topic_iam_member" "runtime_publish_translated" {
  topic  = google_pubsub_topic.speech_translated.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

resource "google_pubsub_subscription_iam_member" "runtime_subscribe_translated" {
  subscription = google_pubsub_subscription.speech_translated_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# --- Topic: speech-scored (A-6 出力 / A-7 distributor 入力) ---
resource "google_pubsub_topic" "speech_scored" {
  name = "citify-speech-scored"

  message_retention_duration = "604800s"

  labels = local.common_labels
}

resource "google_pubsub_subscription" "speech_scored_sub" {
  name  = "citify-speech-scored-sub"
  topic = google_pubsub_topic.speech_scored.id

  ack_deadline_seconds         = 30
  message_retention_duration   = "604800s"
  enable_exactly_once_delivery = true

  expiration_policy {
    ttl = ""
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  labels = local.common_labels
}

# A-6 worker が speech_scored に publish
resource "google_pubsub_topic_iam_member" "runtime_publish_scored" {
  topic  = google_pubsub_topic.speech_scored.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# A-7 distributor が speech_scored を subscribe
resource "google_pubsub_subscription_iam_member" "runtime_subscribe_scored" {
  subscription = google_pubsub_subscription.speech_scored_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# DLQ への publish 権限 (subscription が dead_letter 送信時に必要)
# Pub/Sub サービスアカウント: service-PROJECT_NUMBER@gcp-sa-pubsub.iam.gserviceaccount.com
data "google_project" "current" {
  project_id = var.project_id
}

resource "google_pubsub_topic_iam_member" "pubsub_sa_dlq_publish" {
  topic  = google_pubsub_topic.speech_translate_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# Pub/Sub SA は DLQ 送信時に元 subscription を ack する必要があるため subscriber 権限も付与
resource "google_pubsub_subscription_iam_member" "pubsub_sa_subscribe_translate" {
  subscription = google_pubsub_subscription.speech_translate_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# ---------------------------------------------------------------------------
# 後続 (Week 2 後半 / Week 3 以降で追加予定):
#   - module "firestore"        (modules/firestore/)
#   - module "secret_manager"   (modules/secret_manager/)
#   - module "cloud_storage"    (modules/cloud_storage/)
#   - module "rag_engine"       (Vertex AI RAG Engine)
# 詳細は `docs/TERRAFORM_GUIDE.md` 参照
