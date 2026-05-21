# Citify dev 環境 — outputs
#
# `terraform output` で参照可能な値。
# Cloud Build / Cloud Run / Vertex AI 等から参照する SA email や Artifact Registry URI 等。

output "artifact_registry_repo" {
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.api.repository_id}"
  description = "Artifact Registry Docker repo URI (cloudbuild.yaml の image push 先)"
}

output "cloud_build_deployer_email" {
  value       = google_service_account.cloud_build_deployer.email
  description = "Cloud Build trigger 実行 ID の email"
}

output "citify_api_runtime_email" {
  value       = google_service_account.citify_api_runtime.email
  description = "Cloud Run citify-api ランタイム SA の email (cloudbuild.yaml の _RUNTIME_SA と一致)"
}

output "cloud_build_trigger_id" {
  value       = google_cloudbuild_trigger.api_main.trigger_id
  description = "Cloud Build trigger ID (Cloud Console URL 生成や手動 run 時に使用)"
}

output "cloud_build_trigger_url" {
  value       = "https://console.cloud.google.com/cloud-build/triggers/edit/${google_cloudbuild_trigger.api_main.trigger_id}?project=${var.project_id}"
  description = "Cloud Build trigger の管理 URL"
}

output "bq_dataset_id" {
  value       = google_bigquery_dataset.raw.dataset_id
  description = "BigQuery dataset ID (citify_raw)"
}

output "bq_kokkai_table_full_id" {
  value       = "${var.project_id}.${google_bigquery_dataset.raw.dataset_id}.${google_bigquery_table.kokkai_speeches.table_id}"
  description = "BigQuery kokkai_speeches テーブルの完全 ID (project.dataset.table 形式)"
}

output "bq_scored_speeches_full_id" {
  value       = "${var.project_id}.${google_bigquery_dataset.curated.dataset_id}.${google_bigquery_table.scored_speeches.table_id}"
  description = "BigQuery scored_speeches テーブルの完全 ID (BQ sink 投入先、生データ)"
}

output "bq_scored_speeches_latest_view" {
  value       = "${var.project_id}.${google_bigquery_dataset.curated.dataset_id}.${google_bigquery_table.scored_speeches_latest.table_id}"
  description = "BigQuery scored_speeches_latest view の完全 ID (dedup 済、frontend / BI 推奨先)"
}

output "rag_staging_bucket" {
  value       = "gs://${google_storage_bucket.rag_staging.name}"
  description = "RAG corpus 取り込み用 GCS bucket URI"
}
