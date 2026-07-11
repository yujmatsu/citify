# ============================================================================
# 監視・アラート (実運用配慮 / 審査基準⑤)
# ============================================================================
# Cloud Run (citify-api) のエラー率・レイテンシと、Pub/Sub DLQ の滞留を監視する
# アラートポリシー。ARCHITECTURE.md §8.4 の「アラート表」を実リソース化したもの。
#
# 通知チャンネル: var.alert_email が設定されていれば email チャンネルを作成し
# 各ポリシーに紐付ける。空なら policy のみ作成 (Cloud Console のアラート一覧に出る)。
#
# ※ 適用には `terraform apply` が必要 (本ファイル追加だけでは有効化されない)。
# ============================================================================

locals {
  # api サービス名 (Cloud Build デプロイの Cloud Run service 名と一致させる)
  api_service_name = "citify-api"
  # DLQ サブスクリプション (main.tf の speech_translate_dlq_sub と一致)
  dlq_subscription = "citify-speech-translate-dlq-sub"
  notification_channels = var.alert_email == "" ? [] : [
    google_monitoring_notification_channel.email[0].id
  ]
}

resource "google_monitoring_notification_channel" "email" {
  count        = var.alert_email == "" ? 0 : 1
  project      = var.project_id
  display_name = "Citify alerts (${var.env})"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }
}

# --- Cloud Run: 5xx エラー率スパイク -----------------------------------------
resource "google_monitoring_alert_policy" "api_5xx" {
  project      = var.project_id
  display_name = "citify-api 5xx errors (${var.env})"
  combiner     = "OR"

  conditions {
    display_name = "5xx response count > 5 / 5min"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type = \"cloud_run_revision\"",
        "resource.label.service_name = \"${local.api_service_name}\"",
        "metric.type = \"run.googleapis.com/request_count\"",
        "metric.label.response_code_class = \"5xx\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "300s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
  severity              = "ERROR"

  documentation {
    content   = "citify-api の 5xx が 5 分で 5 件超。直近デプロイのロールバック (docs/CLAUDE.md §11.1) を検討。"
    mime_type = "text/markdown"
  }
}

# --- Cloud Run: p95 レイテンシ悪化 -------------------------------------------
resource "google_monitoring_alert_policy" "api_latency_p95" {
  project      = var.project_id
  display_name = "citify-api p95 latency (${var.env})"
  combiner     = "OR"

  conditions {
    display_name = "p95 request latency > 5s"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type = \"cloud_run_revision\"",
        "resource.label.service_name = \"${local.api_service_name}\"",
        "metric.type = \"run.googleapis.com/request_latencies\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 5000
      duration        = "300s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_PERCENTILE_95"
      }
      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
  severity              = "WARNING"

  documentation {
    content   = "citify-api の p95 レイテンシが 5 秒超。コールドスタート/依存 (Vertex/BQ) 遅延を確認。"
    mime_type = "text/markdown"
  }
}

# --- Pub/Sub: DLQ 滞留 (poison message の兆候) --------------------------------
resource "google_monitoring_alert_policy" "dlq_backlog" {
  project      = var.project_id
  display_name = "Pub/Sub DLQ backlog (${var.env})"
  combiner     = "OR"

  conditions {
    display_name = "DLQ undelivered messages > 0"
    condition_threshold {
      filter = join(" AND ", [
        "resource.type = \"pubsub_subscription\"",
        "resource.label.subscription_id = \"${local.dlq_subscription}\"",
        "metric.type = \"pubsub.googleapis.com/subscription/num_undelivered_messages\"",
      ])
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "600s"
      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MAX"
      }
      trigger {
        count = 1
      }
    }
  }

  notification_channels = local.notification_channels
  severity              = "WARNING"

  documentation {
    content   = "DLQ にメッセージが滞留。パイプラインの poison message を pull して調査 (main.tf DLQ 手順)。"
    mime_type = "text/markdown"
  }
}
