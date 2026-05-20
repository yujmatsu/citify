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
# 後続 (Week 1 後半 / Week 2 で追加予定):
#   - module "firestore"        (modules/firestore/)
#   - module "bigquery"         (modules/bigquery/)
#   - module "pubsub"           (modules/pubsub/)
#   - module "secret_manager"   (modules/secret_manager/)
#   - module "cloud_storage"    (modules/cloud_storage/)
#   - module "rag_engine"       (Vertex AI RAG Engine)
# 詳細は `docs/TERRAFORM_GUIDE.md` 参照
