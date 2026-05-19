# TERRAFORM_GUIDE.md — Terraform 初期化・運用ガイド

> Citify の GCP インフラを Terraform で管理するためのガイド。初期化手順、モジュール構成、追加リソースの作り方、トラブルシューティング。

---

## 0. 前提

### 0.1 必要なツール

```
terraform >= 1.7.0
gcloud SDK
GitHub CLI (gh) - 必須ではないが便利
```

インストール例:

**WSL Ubuntu (推奨環境)**:
```bash
# Terraform (HashiCorp 公式 apt リポジトリ)
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update
sudo apt install -y terraform

# Google Cloud SDK
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee -a /etc/apt/sources.list.d/google-cloud-sdk.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg
sudo apt update
sudo apt install -y google-cloud-cli

# GitHub CLI
sudo apt install -y gh
```

**macOS の場合（参考）**:
```bash
brew install terraform
brew install --cask google-cloud-sdk
brew install gh
```

詳細手順は `docs/GETTING_STARTED.md` Section 1.2 参照。

### 0.2 必要な GCP 権限

- **Owner** または以下の組み合わせ:
  - Editor
  - Project IAM Admin
  - Service Account Admin
  - Secret Manager Admin

### 0.3 設計原則

- **dev / prod 環境を完全分離** (GCP プロジェクトレベルで)
- **モジュール化を徹底** (同じパターンを 3 回書いたらモジュール化)
- **すべてのリソースに label を付ける** (`project = "citify"`, `env = var.env`)
- **State はリモート (GCS)** に保管。ローカル State 禁止
- **シークレットは Terraform に書かない** (Secret Manager 経由)
- **`terraform fmt` と `terraform validate` を CI で必須**

---

## 1. ディレクトリ構成

```
infra/
├── backend.tf                  # GCS バックエンド設定
├── versions.tf                 # Terraform バージョン要求
│
├── modules/                    # 再利用可能なモジュール
│   ├── cloud_run_service/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   └── README.md
│   ├── cloud_run_job/
│   ├── firestore/
│   ├── bigquery_dataset/
│   ├── pubsub_topic/
│   ├── cloud_scheduler/
│   ├── secret_manager/
│   ├── vector_search/
│   ├── storage_bucket/
│   ├── iam_service_account/
│   └── artifact_registry/
│
├── env/                        # 環境別の設定
│   ├── dev/
│   │   ├── main.tf
│   │   ├── variables.tf
│   │   ├── outputs.tf
│   │   ├── terraform.tfvars    # dev環境の変数
│   │   └── backend.hcl         # dev環境のbackend設定
│   └── prod/
│       └── (同じ構造)
│
└── seed/                       # シードデータ投入スクリプト
    ├── load_municipalities.py
    └── ...
```

---

## 2. 初回セットアップ手順 (Week 0)

### 2.1 GCP プロジェクト作成

```bash
# プロジェクト作成
gcloud projects create citify-dev \
  --name="Citify Development" \
  --set-as-default

# 課金アカウントをリンク (請求アカウントID を要事前取得)
gcloud beta billing projects link citify-dev \
  --billing-account=XXXXXX-YYYYYY-ZZZZZZ

# 同様に prod も作成
gcloud projects create citify-prod \
  --name="Citify Production"
gcloud beta billing projects link citify-prod \
  --billing-account=XXXXXX-YYYYYY-ZZZZZZ
```

### 2.2 必要な API の有効化

```bash
gcloud config set project citify-dev

gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudfunctions.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  bigquery.googleapis.com \
  pubsub.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudkms.googleapis.com \
  documentai.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  cloudtrace.googleapis.com
```

### 2.3 Terraform State 用 GCS バケット作成

State はリモートで管理。**手動で作成** (State 自体は Terraform 管理対象外):

```bash
gcloud storage buckets create gs://citify-tfstate-dev \
  --location=asia-northeast1 \
  --uniform-bucket-level-access \
  --versioning

gcloud storage buckets create gs://citify-tfstate-prod \
  --location=asia-northeast1 \
  --uniform-bucket-level-access \
  --versioning
```

### 2.4 認証

```bash
# 開発時はユーザー認証
gcloud auth application-default login

# 本番デプロイ時は Workload Identity Federation (推奨)
# または サービスアカウントキー (非推奨だがハッカソンでは可)
```

### 2.5 Terraform 初期化

```bash
cd infra/env/dev

# backend.hcl を編集して bucket 名を指定
cat > backend.hcl <<EOF
bucket = "citify-tfstate-dev"
prefix = "terraform/state"
EOF

terraform init -backend-config=backend.hcl
```

期待される出力:
```
Initializing the backend...
Successfully configured the backend "gcs"!
Terraform has been successfully initialized!
```

---

## 3. 基本ファイル

### 3.1 `infra/backend.tf`

```hcl
terraform {
  required_version = ">= 1.7.0"

  backend "gcs" {
    # bucket と prefix は backend.hcl で指定
  }

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }
}
```

### 3.2 `infra/env/dev/variables.tf`

```hcl
variable "project_id" {
  type        = string
  description = "GCP project ID"
}

variable "region" {
  type        = string
  default     = "asia-northeast1"
  description = "Primary region"
}

variable "env" {
  type        = string
  description = "Environment (dev, prod)"
  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be 'dev' or 'prod'"
  }
}

variable "default_labels" {
  type = map(string)
  default = {
    project = "citify"
    managed_by = "terraform"
  }
}
```

### 3.3 `infra/env/dev/terraform.tfvars`

```hcl
project_id = "citify-dev"
region     = "asia-northeast1"
env        = "dev"
```

### 3.4 `infra/env/dev/main.tf`

```hcl
provider "google" {
  project = var.project_id
  region  = var.region
  default_labels = merge(var.default_labels, {
    env = var.env
  })
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# ===== Firestore =====
module "firestore" {
  source     = "../../modules/firestore"
  project_id = var.project_id
  location   = "asia-northeast1"
}

# ===== BigQuery =====
module "bigquery" {
  source     = "../../modules/bigquery_dataset"
  project_id = var.project_id
  dataset_id = "citify_analytics"
  location   = "asia-northeast1"
  env        = var.env

  tables = {
    speeches = {
      schema_file       = "schemas/speeches.json"
      partition_field   = "date"
      partition_type    = "DAY"
      clustering_fields = ["municipality_code", "source"]
    }
    press_releases = {
      schema_file       = "schemas/press_releases.json"
      partition_field   = "published_at"
      partition_type    = "DAY"
      clustering_fields = ["municipality_code"]
    }
    # ... 他のテーブル
  }
}

# ===== Cloud Storage =====
module "videos_bucket" {
  source        = "../../modules/storage_bucket"
  project_id    = var.project_id
  name          = "citify-videos-${var.env}"
  location      = "asia-northeast1"
  storage_class = "STANDARD"

  lifecycle_rules = [
    {
      condition = { age = 90 }
      action    = { type = "SetStorageClass", storage_class = "COLDLINE" }
    }
  ]
}

# ===== Pub/Sub =====
module "pubsub_new_content" {
  source     = "../../modules/pubsub_topic"
  project_id = var.project_id
  topic_name = "citify-new-content-${var.env}"
}

module "pubsub_classified" {
  source     = "../../modules/pubsub_topic"
  project_id = var.project_id
  topic_name = "citify-classified-${var.env}"
}

# ===== サービスアカウント =====
module "sa_api" {
  source       = "../../modules/iam_service_account"
  project_id   = var.project_id
  account_id   = "citify-api-${var.env}"
  display_name = "Citify API"
  roles = [
    "roles/datastore.user",                 # Firestore
    "roles/pubsub.publisher",
    "roles/secretmanager.secretAccessor",
    "roles/storage.objectViewer",
    "roles/aiplatform.user",
  ]
}

module "sa_collector" {
  source       = "../../modules/iam_service_account"
  project_id   = var.project_id
  account_id   = "citify-collector-${var.env}"
  display_name = "Citify Collector Agent"
  roles = [
    "roles/bigquery.dataEditor",
    "roles/pubsub.publisher",
    "roles/storage.objectAdmin",
  ]
}

# ... 他のエージェント用 SA も同様

# ===== Cloud Run サービス =====
locals {
  cloud_run_services = {
    api          = { sa = module.sa_api.email, port = 8080 }
    collector    = { sa = module.sa_collector.email, port = 8080 }
    classifier   = { sa = module.sa_classifier.email, port = 8080 }
    relevance    = { sa = module.sa_relevance.email, port = 8080 }
    translator   = { sa = module.sa_translator.email, port = 8080 }
    comparator   = { sa = module.sa_comparator.email, port = 8080 }
    storyteller  = { sa = module.sa_storyteller.email, port = 8080 }
    distributor  = { sa = module.sa_distributor.email, port = 8080 }
  }
}

module "cloud_run" {
  for_each = local.cloud_run_services

  source            = "../../modules/cloud_run_service"
  project_id        = var.project_id
  region            = var.region
  service_name      = "citify-${each.key}-${var.env}"
  service_account   = each.value.sa
  image             = "${var.region}-docker.pkg.dev/${var.project_id}/citify/${each.key}:latest"
  cpu               = "1"
  memory            = "512Mi"
  min_instances     = 0
  max_instances     = 5
  port              = each.value.port

  env_vars = {
    GCP_PROJECT_ID = var.project_id
    GCP_REGION     = var.region
    ENV            = var.env
    LOG_LEVEL      = "info"
  }
}

# ===== Cloud Run Jobs (Batch) =====
module "job_collect_daily" {
  source             = "../../modules/cloud_run_job"
  project_id         = var.project_id
  region             = var.region
  job_name           = "citify-batch-collect-daily-${var.env}"
  service_account    = module.sa_collector.email
  image              = "${var.region}-docker.pkg.dev/${var.project_id}/citify/batch-collect:latest"
  timeout_seconds    = 1800  # 30 min
  max_retries        = 2
}

# ===== Cloud Scheduler =====
module "scheduler_collect_daily" {
  source           = "../../modules/cloud_scheduler"
  project_id       = var.project_id
  region           = var.region
  name             = "citify-collect-daily-${var.env}"
  schedule         = "0 5 * * *"
  time_zone        = "Asia/Tokyo"
  description      = "Daily collection at 5:00 JST"
  target_job       = module.job_collect_daily.job_name
}

# ===== Secret Manager =====
resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "citify-gemini-api-key-${var.env}"
  project   = var.project_id
  replication {
    auto {}
  }
}

# ===== Artifact Registry =====
module "artifact_registry" {
  source       = "../../modules/artifact_registry"
  project_id   = var.project_id
  location     = var.region
  repository_id = "citify"
  description  = "Citify container images"
}
```

### 3.5 `infra/env/dev/outputs.tf`

```hcl
output "api_service_url" {
  value = module.cloud_run["api"].url
}

output "firestore_database" {
  value = module.firestore.database_name
}

output "bigquery_dataset" {
  value = module.bigquery.dataset_id
}
```

---

## 4. モジュール例

### 4.1 `modules/cloud_run_service/main.tf`

```hcl
resource "google_cloud_run_v2_service" "this" {
  name     = var.service_name
  location = var.region
  project  = var.project_id

  template {
    service_account = var.service_account

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image
      ports {
        container_port = var.port
      }
      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }
      dynamic "env" {
        for_each = var.env_vars
        content {
          name  = env.key
          value = env.value
        }
      }
    }

    timeout = "${var.timeout_seconds}s"
  }

  labels = {
    service = var.service_name
  }
}

# IAM: 認証必須に設定 (allUsers から呼び出し不可)
resource "google_cloud_run_v2_service_iam_member" "internal_only" {
  count    = var.allow_unauthenticated ? 0 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.service_account}"
}
```

### 4.2 `modules/cloud_run_service/variables.tf`

```hcl
variable "project_id" {}
variable "region" {}
variable "service_name" {}
variable "service_account" {}
variable "image" {}
variable "cpu" { default = "1" }
variable "memory" { default = "512Mi" }
variable "min_instances" { default = 0 }
variable "max_instances" { default = 10 }
variable "port" { default = 8080 }
variable "env_vars" { type = map(string), default = {} }
variable "allow_unauthenticated" { default = false }
variable "timeout_seconds" { default = 300 }
```

### 4.3 `modules/cloud_run_service/outputs.tf`

```hcl
output "url" {
  value = google_cloud_run_v2_service.this.uri
}

output "name" {
  value = google_cloud_run_v2_service.this.name
}
```

---

## 5. 日常運用コマンド

### 5.1 変更前の確認

```bash
cd infra/env/dev

# フォーマット
terraform fmt -recursive

# 検証
terraform validate

# 変更プレビュー
terraform plan -out=tfplan
```

### 5.2 適用

```bash
terraform apply tfplan
```

### 5.3 特定リソースの再作成

```bash
# 例: Cloud Run の api サービスを再作成
terraform taint 'module.cloud_run["api"].google_cloud_run_v2_service.this'
terraform apply
```

### 5.4 State 操作

```bash
# 現在の State を確認
terraform state list

# 特定リソースの詳細
terraform state show 'module.firestore.google_firestore_database.this'

# 手動リソースを State にインポート
terraform import 'module.firestore.google_firestore_database.this' projects/citify-dev/databases/(default)
```

### 5.5 環境間の切替

```bash
# dev → prod
cd infra/env/prod
terraform init -backend-config=backend.hcl
terraform plan
```

---

## 6. CI/CD 統合

### 6.1 GitHub Actions ワークフロー

`.github/workflows/terraform.yml`:

```yaml
name: Terraform

on:
  pull_request:
    paths:
      - 'infra/**'
  push:
    branches: [main]
    paths:
      - 'infra/**'

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.7.0

      - run: terraform fmt -check -recursive
      - run: |
          cd infra/env/dev
          terraform init -backend=false
          terraform validate

  plan:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    needs: validate
    permissions:
      id-token: write
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.WIF_SA }}

      - uses: hashicorp/setup-terraform@v3
      - run: |
          cd infra/env/dev
          terraform init -backend-config=backend.hcl
          terraform plan -no-color | tee plan.txt

      - uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const plan = fs.readFileSync('infra/env/dev/plan.txt', 'utf8');
            github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: '```\n' + plan + '\n```'
            });

  apply:
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    runs-on: ubuntu-latest
    needs: validate
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: ${{ secrets.WIF_PROVIDER }}
          service_account: ${{ secrets.WIF_SA }}

      - uses: hashicorp/setup-terraform@v3
      - run: |
          cd infra/env/dev
          terraform init -backend-config=backend.hcl
          terraform apply -auto-approve
```

### 6.2 Workload Identity Federation 設定

GitHub Actions から GCP へキーレスでデプロイするための設定 (初回のみ):

```bash
# プール作成
gcloud iam workload-identity-pools create "github-pool" \
  --location="global" \
  --display-name="GitHub Actions Pool"

# プロバイダ作成
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub OIDC Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

# サービスアカウント作成 (Terraform で管理してもよい)
gcloud iam service-accounts create "github-terraform" \
  --display-name="GitHub Actions Terraform SA"

# 権限付与
gcloud projects add-iam-policy-binding citify-dev \
  --member="serviceAccount:github-terraform@citify-dev.iam.gserviceaccount.com" \
  --role="roles/editor"

# GitHub repo と紐付け
gcloud iam service-accounts add-iam-policy-binding \
  github-terraform@citify-dev.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/attribute.repository/{USER}/citify"
```

GitHub Secret に登録：
- `WIF_PROVIDER`: `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
- `WIF_SA`: `github-terraform@citify-dev.iam.gserviceaccount.com`

---

## 7. シードデータ投入

`infra/seed/load_municipalities.py`:

```python
"""自治体マスタ CSV を Firestore に投入する"""
import csv
from google.cloud import firestore

db = firestore.Client(project="citify-dev")
batch = db.batch()

with open("municipality_master.csv") as f:
    reader = csv.DictReader(f)
    for row in reader:
        doc_ref = db.collection("municipalities").document(row["municipality_code"])
        batch.set(doc_ref, {
            "code": row["municipality_code"],
            "name": row["name"],
            "prefecture": row["prefecture"],
            "kana": row["kana"],
            "population": int(row["population"]) if row["population"] else None,
            "scraperType": row["scraper_type"],
            "scraperConfig": {
                "tenantId": row.get("tenant_id") or None,
                "pressRssUrl": row.get("press_rss_url") or None,
            },
            "tier": int(row["tier"]),
            "isActive": row["is_active"].lower() == "true",
            "createdAt": firestore.SERVER_TIMESTAMP,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })

batch.commit()
print(f"Loaded municipalities")
```

実行:
```bash
cd infra/seed
python load_municipalities.py
```

---

## 8. トラブルシューティング

### 8.1 `Error: Failed to query available provider packages`

```bash
# .terraform.lock.hcl を削除して再初期化
rm .terraform.lock.hcl
terraform init -upgrade
```

### 8.2 State がロックされている

```bash
# 強制的にアンロック
terraform force-unlock <LOCK_ID>
```

### 8.3 リソースを誤って削除した

GCS の State バケットは Versioning ON にしているので、前バージョンを復元可能：

```bash
gsutil ls -a gs://citify-tfstate-dev/terraform/state/
gsutil cp gs://citify-tfstate-dev/terraform/state/default.tfstate#<GENERATION> ./default.tfstate.backup
```

### 8.4 Cloud Run のデプロイは Terraform より Cloud Build で

Cloud Run の **コンテナイメージ更新** は `terraform apply` ではなく Cloud Build で行う設計。
Terraform は **インフラ定義のみ** を管理し、デプロイ操作は CI/CD パイプラインの責務。

### 8.5 `terraform plan` で大量の差分が出る

GCP 側で手動変更している可能性。`terraform refresh` で State を最新化：

```bash
terraform refresh
terraform plan  # 差分を確認
```

---

## 9. コスト管理

### 9.1 想定コスト (月額、dev環境)

| サービス | 想定 |
|---|---|
| Cloud Run (全サービス) | $5-15 |
| Firestore | $0-5 (読み書き量次第) |
| BigQuery | $5-10 |
| Cloud Storage | $1-3 |
| Vertex AI (Gemini) | $20-50 |
| Veo (60秒動画 × 100本) | $50-150 |
| Imagen (1000枚) | $20-40 |
| **合計** | **約 $100-275 / 月** |

### 9.2 コスト監視

```hcl
# モジュール: budget alert
resource "google_billing_budget" "monthly" {
  billing_account = var.billing_account
  display_name    = "Citify monthly budget"

  budget_filter {
    projects = ["projects/${var.project_id}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = "300"
    }
  }

  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
}
```

---

## 10. ハッカソン期間中の進め方

### Week 0 (5/19-5/25)
- [ ] GCP プロジェクト 2つ作成 (dev/prod)
- [ ] State バケット作成
- [ ] 最低限のリソース (Firestore, BigQuery, Cloud Run × 1) を terraform apply
- [ ] サンプル Cloud Run へ Hello World デプロイ成功

### Week 1 (5/26-6/1)
- [ ] 全 Cloud Run サービス (7 エージェント) のリソース定義
- [ ] Cloud Scheduler + Pub/Sub の連携
- [ ] Vertex AI RAG Engine の Index 作成

### Week 2-5
- 機能追加に合わせて随時 modules/ を拡張

### Week 6 (6/30-7/6)
- [ ] prod 環境にも apply
- [ ] 本番URLでデモ動画撮影

### Week 7 (7/7-7/10)
- 提出間際は **触らない** (壊さない)

---

## 11. 改訂履歴

- 2026-05-19 v0.1 初版作成
