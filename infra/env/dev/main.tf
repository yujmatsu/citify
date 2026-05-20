# Citify dev 環境 — Terraform エントリポイント
#
# Week 1 で `terraform apply` を実行する想定。
# 初回は GCS backend 用バケットがまだ無いのでローカル state でスタート、
# その後 backend "gcs" を有効化して `terraform init -migrate-state` で移行。

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

  # Week 1 で有効化予定: GCS リモートステート
  # 先に `gsutil mb gs://citify-dev-tf-state` で バケット作成 → 下記コメント解除 → `terraform init -migrate-state`
  # backend "gcs" {
  #   bucket = "citify-dev-tf-state"
  #   prefix = "env/dev"
  # }
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
}

# ---------------------------------------------------------------------------
# (Week 1 Day 1 雛形): リソースはここから追加
# ---------------------------------------------------------------------------
# 予定:
#   - module "cloud_run_api"   (modules/cloud_run/)
#   - module "firestore"        (modules/firestore/)
#   - module "bigquery"         (modules/bigquery/)
#   - module "pubsub"           (modules/pubsub/)
#   - module "secret_manager"   (modules/secret_manager/)
#   - module "cloud_storage"    (modules/cloud_storage/)
# 詳細は `docs/TERRAFORM_GUIDE.md` 参照
