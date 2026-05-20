# Citify dev 環境 — 変数定義

variable "project_id" {
  type        = string
  description = "GCP プロジェクト ID (例: citify-dev)"
  default     = "citify-dev"
}

variable "region" {
  type        = string
  description = "デフォルトリージョン (Tokyo 固定)"
  default     = "asia-northeast1"
}

variable "env" {
  type        = string
  description = "環境名 (dev / staging / prod)"
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.env)
    error_message = "env は dev / staging / prod のいずれかである必要があります。"
  }
}

# Week 1 以降で追加予定:
# variable "billing_account" { ... }
# variable "gemini_model" {
#   type    = string
#   default = "gemini-2.5-flash"
# }
# variable "cors_origins" { ... }
