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
