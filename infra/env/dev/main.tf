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
    "roles/run.invoker",                  # Cloud Scheduler → Cloud Run Job 起動 (Phase R)
    "roles/datastore.user",               # Firestore native mode read/write (Phase X リアクション永続化)
  ]

  # Cloud Run Job として deploy する worker 一覧 (Phase R)
  # NOTE: image は cloudbuild-workers.yaml で push、Terraform は job 構成のみ管理
  # NOTE: subscribers blocking call なので timeout に近い時間まで動く
  workers = {
    translator = {
      command = ["python", "-m", "agents.translator.worker"]
      args = [
        "--project-id", "citify-dev",
        "--input-subscription", "citify-speech-translate-sub",
        "--output-topic", "citify-speech-translated",
      ]
      memory = "1Gi"
      cpu    = "1"
    }
    relevance = {
      # Phase Y: multi-persona fan-out (personas.json で 5 ペルソナ定義)
      command = ["python", "-m", "agents.relevance.worker"]
      args = [
        "--project-id", "citify-dev",
        "--input-subscription", "citify-speech-translated-sub",
        "--output-topic", "citify-speech-scored",
        "--personas-file", "agents/relevance/personas.json",
      ]
      memory = "1Gi"
      cpu    = "1"
    }
    distributor = {
      command = ["python", "-m", "agents.distributor.worker"]
      args = [
        "--project-id", "citify-dev",
        "--input-subscription", "citify-speech-scored-distributor-sub", # fan-out 専用
        "--output-topic", "citify-feed-snapshot",
        "--min-relevance", "50",
        "--feed-size", "10",
      ]
      memory = "512Mi"
      cpu    = "1"
    }
    bq-sink-scored = {
      command = ["python", "-m", "pkg.bq_sink_runner"]
      args = [
        "--project-id", "citify-dev",
        "--sink", "scored_speeches",
        "--subscription", "citify-speech-scored-bq-sub", # fan-out 専用
        "--table", "citify-dev.citify_curated.scored_speeches",
      ]
      memory = "512Mi"
      cpu    = "1"
    }
  }
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

  # API イメージは apps/api だけでなく agents/ と pkg/ も COPY する
  # (apps/api/Dockerfile L66-67)。エージェントロジック(agents/**)のみの変更でも
  # 必ずリビルドするため、これらを included_files に含める。
  # (含めないと agents/** 変更が本番 API に反映されない — TASK-WATCHERV2 P1/P2 で発覚)
  included_files = [
    "apps/api/**",
    "agents/**",
    "pkg/**",
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
# BigQuery: citify_curated dataset + scored_speeches テーブル (Phase Q)
# ---------------------------------------------------------------------------
# 設計方針:
#   - dataset citify_curated: 加工済データ集約 (raw + AI 結果の join)
#   - scored_speeches: A-6 relevance worker → BQ sink で永続化
#     1 行 = 1 ユーザー × 1 speech の評価結果 (matched_interests/score breakdown 含む)
#   - partition by ingested_at (DAY): 直近 N 日のフィード生成で全件スキャン回避
#   - cluster by user_id, municipality_code: per-user feed query 最速化
resource "google_bigquery_dataset" "curated" {
  dataset_id  = "citify_curated"
  location    = var.region
  description = "Citify 加工済データ (翻訳済 speech + relevance score、ユーザー × speech 単位)"
  labels      = local.common_labels

  delete_contents_on_destroy = false

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

resource "google_bigquery_table" "scored_speeches" {
  dataset_id          = google_bigquery_dataset.curated.dataset_id
  table_id            = "scored_speeches"
  description         = "A-6 relevance worker 出力。1 行 = 1 ユーザー × 1 speech の評価結果"
  deletion_protection = false

  time_partitioning {
    type  = "DAY"
    field = "ingested_at"
  }

  clustering = ["user_id", "municipality_code"]

  schema = jsonencode([
    { name = "speech_id", type = "STRING", mode = "REQUIRED", description = "合成 ID (tenant:council:schedule:order or kokkai speechID)" },
    { name = "user_id", type = "STRING", mode = "REQUIRED", description = "ペルソナ ID" },
    { name = "municipality_code", type = "STRING", mode = "NULLABLE", description = "5 桁自治体コード ('00000' = 国会)" },
    { name = "title", type = "STRING", mode = "NULLABLE", description = "A-5 翻訳タイトル (40 字以内)" },
    { name = "summary", type = "STRING", mode = "REPEATED", description = "A-5 翻訳 3 行サマリ" },
    { name = "detail_url", type = "STRING", mode = "NULLABLE", description = "原典 URL (引用必須)" },
    { name = "meeting_date", type = "DATE", mode = "NULLABLE", description = "会議開催日" },
    { name = "relevance_score", type = "INTEGER", mode = "REQUIRED", description = "A-6 総合スコア 0-100" },
    { name = "score_topic", type = "INTEGER", mode = "NULLABLE", description = "トピック関連性 0-25" },
    { name = "score_age", type = "INTEGER", mode = "NULLABLE", description = "年代適合性 0-25" },
    { name = "score_geographic", type = "INTEGER", mode = "NULLABLE", description = "地理関連性 0-25" },
    { name = "score_urgency", type = "INTEGER", mode = "NULLABLE", description = "緊急性 0-25" },
    { name = "matched_interests", type = "STRING", mode = "REPEATED", description = "ペルソナ関心軸との合致" },
    { name = "reasoning", type = "STRING", mode = "NULLABLE", description = "スコアの簡潔な理由 (200 字以内)" },
    { name = "speaker_position", type = "STRING", mode = "NULLABLE", description = "役職 (固有名詞でない)" },
    { name = "name_of_meeting", type = "STRING", mode = "NULLABLE", description = "会議名" },
    { name = "tone", type = "STRING", mode = "NULLABLE", description = "A-5 翻訳トーン casual/neutral/formal" },
    { name = "message_id", type = "STRING", mode = "NULLABLE", description = "Pub/Sub message_id (dedup 用)" },
    { name = "ingested_at", type = "TIMESTAMP", mode = "REQUIRED", description = "BQ 投入タイムスタンプ (UTC, partition key)" },
  ])

  labels = local.common_labels
}

# ---------------------------------------------------------------------------
# BigQuery View: scored_speeches_latest (Phase S — EOD race による重複 dedup)
# ---------------------------------------------------------------------------
# 設計:
#   - Pub/Sub exactly_once_delivery は「ほぼ exactly once」、稀に重複配信あり
#   - BQ insert は idempotent でないため、同じ (speech_id, user_id) が複数行になる可能性
#   - この view で (speech_id, user_id) ごとに最新 1 行だけ返すよう正規化
#   - frontend / BI ツールはこの view を読むことで重複を意識せずに済む
#   - 列は元 table と完全一致 (rn は EXCEPT で除外)、互換性維持
#
# 参考クエリ (このまま実行可):
#   SELECT speech_id, title, relevance_score, matched_interests
#   FROM `citify-dev.citify_curated.scored_speeches_latest`
#   WHERE user_id = 'demo-25-29' AND relevance_score >= 50
#   ORDER BY relevance_score DESC LIMIT 10
resource "google_bigquery_table" "scored_speeches_latest" {
  dataset_id          = google_bigquery_dataset.curated.dataset_id
  table_id            = "scored_speeches_latest"
  description         = "scored_speeches を (speech_id, user_id) で dedup した view。Pub/Sub EOD race による稀な重複を吸収。frontend / BI が読む推奨先"
  deletion_protection = false

  view {
    use_legacy_sql = false
    query          = <<-SQL
      SELECT * EXCEPT (_rn)
      FROM (
        SELECT
          *,
          ROW_NUMBER() OVER (
            PARTITION BY speech_id, user_id
            ORDER BY ingested_at DESC
          ) AS _rn
        FROM `${var.project_id}.${google_bigquery_dataset.curated.dataset_id}.${google_bigquery_table.scored_speeches.table_id}`
      )
      WHERE _rn = 1
    SQL
  }

  labels = merge(local.common_labels, { purpose = "dedup_view" })

  depends_on = [google_bigquery_table.scored_speeches]
}

# ---------------------------------------------------------------------------
# BigQuery Table: municipality_stats (Plan A Phase D — e-Stat 統計)
# ---------------------------------------------------------------------------
# 街ダッシュボード /cities/{code} に「客観数値」を載せるためのテーブル。
#   - 1 行 = 1 自治体 (1,741 市区町村 + prefecture_aggregate)
#   - 国勢調査 2020 + 人口動態調査から手動 prep → scripts/load_estat_stats.py で投入
#   - Tier 3 で議題が薄くても「街の輪郭」が見える背骨データ
resource "google_bigquery_table" "municipality_stats" {
  dataset_id          = google_bigquery_dataset.curated.dataset_id
  table_id            = "municipality_stats"
  description         = "Plan A Phase D 街ダッシュボード用 統計指標 (国勢調査 2020 + 人口動態 2023)"
  deletion_protection = false

  schema = jsonencode([
    { name = "municipality_code", type = "STRING", mode = "REQUIRED", description = "5 桁自治体コード (PK)" },
    { name = "municipality_name", type = "STRING", mode = "REQUIRED", description = "自治体名" },
    { name = "prefecture", type = "STRING", mode = "REQUIRED", description = "都道府県名" },
    { name = "population_total", type = "INTEGER", mode = "NULLABLE", description = "総人口 (2020 国勢調査)" },
    { name = "population_15_29", type = "INTEGER", mode = "NULLABLE", description = "15-29 歳人口" },
    { name = "population_65_plus", type = "INTEGER", mode = "NULLABLE", description = "65 歳以上人口" },
    { name = "population_2015", type = "INTEGER", mode = "NULLABLE", description = "2015 国勢調査人口 (増減率算出用)" },
    { name = "households_total", type = "INTEGER", mode = "NULLABLE", description = "総世帯数 (2020 国勢調査)" },
    { name = "births_annual", type = "INTEGER", mode = "NULLABLE", description = "年間出生数 (2023 人口動態)" },
    { name = "youth_share_pct", type = "FLOAT", mode = "NULLABLE", description = "15-29 歳比率 (%)" },
    { name = "elderly_share_pct", type = "FLOAT", mode = "NULLABLE", description = "65+ 比率 (%)" },
    { name = "population_change_pct", type = "FLOAT", mode = "NULLABLE", description = "5 年人口増減率 ((2020-2015)/2015)" },
    { name = "birth_rate_per_1000", type = "FLOAT", mode = "NULLABLE", description = "普通出生率 (出生数/人口×1000)" },
    { name = "data_year", type = "INTEGER", mode = "REQUIRED", description = "主データ年 (国勢調査基準年 = 2020)" },
    { name = "source_url", type = "STRING", mode = "NULLABLE", description = "e-Stat 統計表 URL (引用元)" },
    { name = "loaded_at", type = "TIMESTAMP", mode = "REQUIRED", description = "BQ 投入タイムスタンプ" },
    # ----- Phase F: Reinfolib (不動産情報ライブラリ) 由来列 -----
    { name = "used_apartment_median_price_man_yen", type = "INTEGER", mode = "NULLABLE", description = "中古マンション中央値 (万円、過去4Q集計、XIT001)" },
    { name = "used_apartment_sample_size", type = "INTEGER", mode = "NULLABLE", description = "中古マンション取引サンプル数 (n<10 は UI 非表示)" },
    { name = "used_apartment_median_unit_price_yen", type = "INTEGER", mode = "NULLABLE", description = "中古マンション ㎡単価中央値 (円/㎡)" },
    { name = "used_apartment_avg_building_age", type = "FLOAT", mode = "NULLABLE", description = "中古マンション築年数平均 (年)" },
    { name = "emergency_shelter_count", type = "INTEGER", mode = "NULLABLE", description = "周辺地域 (z=11 3x3タイル ~50km四方) の指定緊急避難場所数 (XGT001)" },
    { name = "emergency_shelter_official_link", type = "STRING", mode = "NULLABLE", description = "国土地理院ハザードマップポータル URL (自治体中心座標)" },
    # ----- Phase F v3: XKT013 将来推計人口 (z=11 3x3タイル、~50km四方の 250m メッシュ合算) -----
    { name = "population_2025_estimated", type = "INTEGER", mode = "NULLABLE", description = "2025 年予測人口 (250m メッシュ合算、秘匿メッシュ除外、XKT013)" },
    { name = "population_2050_estimated", type = "INTEGER", mode = "NULLABLE", description = "2050 年予測人口 (XKT013)" },
    { name = "population_change_2025_2050_pct", type = "FLOAT", mode = "NULLABLE", description = "2050 vs 2025 人口変動率 (%)" },
    # ----- Phase F v3: XKT010 医療機関 (z=13 5x5 タイル、~25km四方) -----
    { name = "medical_facility_count", type = "INTEGER", mode = "NULLABLE", description = "医療機関数 (名前+住所で重複除外、XKT010)" },
    { name = "medical_hospital_count", type = "INTEGER", mode = "NULLABLE", description = "うち病院 (P04_001=1)" },
    { name = "medical_clinic_count", type = "INTEGER", mode = "NULLABLE", description = "うち診療所 (P04_001=2)" },
    # ----- Phase F v3: XKT007 保育園・幼稚園 (z=13 5x5 タイル、administrativeAreaCode フィルタ) -----
    { name = "childcare_facility_count", type = "INTEGER", mode = "NULLABLE", description = "保育・幼児教育施設数 (XKT007、自治体内厳密集計)" },
    { name = "kindergarten_count", type = "INTEGER", mode = "NULLABLE", description = "うち幼稚園" },
    { name = "nursery_count", type = "INTEGER", mode = "NULLABLE", description = "うち保育園・認定こども園・その他" },
    { name = "reinfolib_loaded_at", type = "TIMESTAMP", mode = "NULLABLE", description = "Reinfolib データ最終取得時刻" },
    { name = "reinfolib_source_url", type = "STRING", mode = "NULLABLE", description = "不動産情報ライブラリ URL (引用元)" },
    # ----- TASK-FISCAL: 社会・人口統計体系 (統計でみる市区町村のすがた) 由来 5指標 -----
    { name = "financial_capability_index", type = "FLOAT", mode = "NULLABLE", description = "財政力指数 (3か年平均、1.0超で財政的余裕。SSDS D2201、特別区は対象外で null)" },
    { name = "real_debt_service_ratio_pct", type = "FLOAT", mode = "NULLABLE", description = "実質公債費比率 (%、借金の重さ。SSDS D2211)" },
    { name = "taxable_income_per_capita_yen", type = "INTEGER", mode = "NULLABLE", description = "1人当たり課税対象所得 (円、=課税対象所得/納税義務者数。SSDS C120110/C120120)" },
    { name = "homeownership_rate_pct", type = "FLOAT", mode = "NULLABLE", description = "持ち家比率 (%、=持ち家数/居住世帯あり住宅数。SSDS H1310/H1101、住調標本のため一部 null)" },
    { name = "crime_rate_per_1000", type = "FLOAT", mode = "NULLABLE", description = "刑法犯認知件数 (人口千対、=刑法犯/人口×1000。SSDS K4201/A1101)" },
    { name = "ssds_data_year", type = "INTEGER", mode = "NULLABLE", description = "SSDS 公表年度 (統計でみる市区町村のすがた)" },
    { name = "ssds_source_url", type = "STRING", mode = "NULLABLE", description = "e-Stat 社会・人口統計体系 URL (引用元)" },
    { name = "ssds_loaded_at", type = "TIMESTAMP", mode = "NULLABLE", description = "SSDS データ最終取得時刻" },
  ])

  labels = merge(local.common_labels, { purpose = "city_dashboard_stats" })
}

# ---------------------------------------------------------------------------
# BigQuery Table: municipality_population_series (TASK-POPTREND — 人口推移グラフ)
# ---------------------------------------------------------------------------
# 1 行 = 1 自治体 × 1 年次 の人口 (long format)。city ダッシュボードの人口推移グラフ用。
#   - source='census'     : e-Stat 国勢調査の実績 (2015/2020、Stage 2 で 2000-2010 延伸)
#   - source='projection' : XKT013 将来推計人口 250m メッシュを SHICODE 集計 (2025-2070)
#   - 2870 倍バグ (50km box 全合算) を SHICODE 絞り込みで解消した正しい人口時系列
resource "google_bigquery_table" "municipality_population_series" {
  dataset_id          = google_bigquery_dataset.curated.dataset_id
  table_id            = "municipality_population_series"
  description         = "TASK-POPTREND 人口推移 (census 実績 + XKT013 将来推計) long format"
  deletion_protection = false

  schema = jsonencode([
    { name = "municipality_code", type = "STRING", mode = "REQUIRED", description = "5 桁自治体コード" },
    { name = "year", type = "INTEGER", mode = "REQUIRED", description = "年次 (2000..2070)" },
    { name = "population", type = "INTEGER", mode = "NULLABLE", description = "総人口" },
    { name = "source", type = "STRING", mode = "REQUIRED", description = "'census' (e-Stat実績) | 'projection' (XKT013将来推計)" },
    { name = "loaded_at", type = "TIMESTAMP", mode = "NULLABLE", description = "BQ 投入時刻" },
    { name = "source_url", type = "STRING", mode = "NULLABLE", description = "出典 URL (総務省国勢調査 / 国交省将来推計)" },
  ])

  labels = merge(local.common_labels, { purpose = "population_trend" })
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

# --- DLQ Subscription (DLQ 行きメッセージの保持・inspect 用) ---
# DLQ topic に subscription が無いと dead-letter 配信されたメッセージは消失する。
# このサブスクで未消化のまま retention 7d 保持し、必要時に Cloud Console / gcloud で
# pull して内容確認 → コード修正 → 再 publish の運用が可能。
resource "google_pubsub_subscription" "speech_translate_dlq_sub" {
  name  = "citify-speech-translate-dlq-sub"
  topic = google_pubsub_topic.speech_translate_dlq.id

  ack_deadline_seconds       = 60
  message_retention_duration = "604800s" # 7 days、DLQ inspect の猶予

  expiration_policy {
    ttl = "" # 永続化 (DLQ inspect 用は消えないように)
  }

  labels = merge(local.common_labels, { purpose = "dlq_inspect" })
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

# NOTE: distributor (A-7) と bq_sink は同じ topic を fan-out で読むため、
#       それぞれ独立した subscription を持つ (competing consumers ではなく fan-out)
# 旧 citify-speech-scored-sub も互換性のため残置 (使用しない、削除可)
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

# distributor (A-7) 専用 subscription (fan-out 用)
resource "google_pubsub_subscription" "speech_scored_distributor_sub" {
  name  = "citify-speech-scored-distributor-sub"
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

  labels = merge(local.common_labels, { consumer = "distributor" })
}

# bq_sink 専用 subscription (fan-out 用)
resource "google_pubsub_subscription" "speech_scored_bq_sub" {
  name  = "citify-speech-scored-bq-sub"
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

  labels = merge(local.common_labels, { consumer = "bq_sink" })
}

# A-6 worker が speech_scored topic に publish
resource "google_pubsub_topic_iam_member" "runtime_publish_scored" {
  topic  = google_pubsub_topic.speech_scored.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# (旧) citify-speech-scored-sub の subscriber 権限 (互換性のため残置)
resource "google_pubsub_subscription_iam_member" "runtime_subscribe_scored" {
  subscription = google_pubsub_subscription.speech_scored_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# distributor 専用 subscription の subscriber 権限
resource "google_pubsub_subscription_iam_member" "runtime_subscribe_scored_distributor" {
  subscription = google_pubsub_subscription.speech_scored_distributor_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# bq_sink 専用 subscription の subscriber 権限
resource "google_pubsub_subscription_iam_member" "runtime_subscribe_scored_bq" {
  subscription = google_pubsub_subscription.speech_scored_bq_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# --- Topic: feed-snapshot (A-7 出力 / frontend or Firestore writer 入力) ---
resource "google_pubsub_topic" "feed_snapshot" {
  name = "citify-feed-snapshot"

  message_retention_duration = "604800s"

  labels = local.common_labels
}

resource "google_pubsub_subscription" "feed_snapshot_sub" {
  name  = "citify-feed-snapshot-sub"
  topic = google_pubsub_topic.feed_snapshot.id

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

resource "google_pubsub_topic_iam_member" "runtime_publish_feed_snapshot" {
  topic  = google_pubsub_topic.feed_snapshot.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

resource "google_pubsub_subscription_iam_member" "runtime_subscribe_feed_snapshot" {
  subscription = google_pubsub_subscription.feed_snapshot_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.citify_api_runtime.email}"
}

# ---------------------------------------------------------------------------
# Cloud Run Jobs: 4 worker (translator / relevance / distributor / bq_sink) (Phase R)
# ---------------------------------------------------------------------------
# 設計:
#   - 1 image (workers:latest) で 4 worker 同梱、CMD で種別切替
#   - timeout = 3540s (59 分) で 1 度の実行
#   - Cloud Scheduler が 60 分ごとに起動 → ほぼ常時 1 インスタンス稼働
#   - max_retries = 0: 失敗しても再試行しない (次の Scheduler 起動で再開)
#   - SA = citify-api-runtime (Pub/Sub publish/subscribe + BQ insert 権限済み)
#   - image は cloudbuild-workers.yaml で push 後、`gcloud run jobs update` で適用

# 初回 apply 時は image がまだ存在しないため、:latest tag が見つかるよう placeholder image を使う
# (cloudbuild-workers.yaml の build を最初に 1 度実行してから terraform apply するのが正しい順序)
resource "google_cloud_run_v2_job" "workers" {
  for_each = local.workers

  name     = "citify-worker-${each.key}"
  location = var.region

  template {
    template {
      service_account = google_service_account.citify_api_runtime.email
      timeout         = "3540s" # 59 min, just under 1h Scheduler interval
      max_retries     = 0       # 次の起動で再開、cascading failure 防止

      containers {
        image   = "${var.region}-docker.pkg.dev/${var.project_id}/citify-api/workers:latest"
        command = each.value.command
        args    = each.value.args

        env {
          name  = "GOOGLE_CLOUD_PROJECT"
          value = var.project_id
        }
        env {
          name  = "GCP_REGION"
          value = var.region
        }

        resources {
          limits = {
            cpu    = each.value.cpu
            memory = each.value.memory
          }
        }
      }
    }
  }

  labels = local.common_labels

  deletion_protection = false

  # 初回 apply 時に image がない場合は手動 cloudbuild submit を先に実行する想定
  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image, # cloudbuild が更新するので drift 無視
    ]
  }
}

# Scheduler service identity に SA TokenCreator 権限 (Scheduler が SA を impersonate して Job 起動)
resource "google_service_account_iam_member" "scheduler_token_creator" {
  service_account_id = google_service_account.citify_api_runtime.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudscheduler.iam.gserviceaccount.com"
}

# ---------------------------------------------------------------------------
# Cloud Scheduler: 1 日 1 回各 Cloud Run Job を起動 (デモ期間用)
# ---------------------------------------------------------------------------
# 設計:
#   - default で paused = true: 普段は停止、月コスト ~$0
#   - デモ期間中は `gcloud scheduler jobs resume` で起こす → 1 日 1 回 09:00 JST に自動起動
#   - 必要な時は `gcloud run jobs execute` で手動 trigger 可能 (Scheduler 不要)
#   - offset で minute をずらす (Gemini API quota 短期集中防止):
#       translator     09:00 JST
#       relevance      09:05 JST
#       distributor    09:10 JST
#       bq-sink-scored 09:15 JST
#   - paused state は terraform variable で flip 可能:
#       terraform apply -var schedulers_paused=false  # デモ期間開始
#       terraform apply -var schedulers_paused=true   # デモ期間終了
#     gcloud で個別 toggle も可能 (scripts/toggle-schedulers.sh 参照)
resource "google_cloud_scheduler_job" "worker_triggers" {
  for_each = local.workers

  name             = "citify-worker-${each.key}-trigger"
  description      = "Trigger Cloud Run Job citify-worker-${each.key} daily at 09:0X JST (paused=${var.schedulers_paused})"
  schedule         = "${index(keys(local.workers), each.key) * 5} 9 * * *" # 9:00 / 9:05 / 9:10 / 9:15 JST
  time_zone        = "Asia/Tokyo"
  region           = var.region
  attempt_deadline = "320s"
  paused           = var.schedulers_paused

  retry_config {
    retry_count = 1
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.workers[each.key].name}:run"

    oauth_token {
      service_account_email = google_service_account.citify_api_runtime.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  depends_on = [
    google_service_account_iam_member.scheduler_token_creator,
    google_project_iam_member.runtime, # runtime に run.invoker が付くまで待つ
  ]
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
