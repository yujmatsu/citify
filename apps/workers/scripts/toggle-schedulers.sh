#!/usr/bin/env bash
# Citify Worker Schedulers の一括 pause / resume
#
# 用途:
#   ./toggle-schedulers.sh resume   # デモ期間開始 (1 日 1 回 09:00 JST 自動起動が有効化)
#   ./toggle-schedulers.sh pause    # デモ期間終了 (停止、月コスト ~$0)
#   ./toggle-schedulers.sh status   # 現在の状態確認
#
# 前提:
#   - gcloud auth が citify-dev project で済んでいること
#   - 4 つの worker Scheduler が Terraform で作成済みであること

set -euo pipefail

ACTION="${1:-status}"
REGION="${REGION:-asia-northeast1}"
WORKERS=(translator relevance distributor bq-sink-scored)

case "$ACTION" in
  pause | resume)
    echo "=== ${ACTION^^} all worker schedulers ==="
    for W in "${WORKERS[@]}"; do
      echo "  $ACTION citify-worker-$W-trigger"
      gcloud scheduler jobs "$ACTION" "citify-worker-$W-trigger" \
        --location="$REGION" \
        --quiet || echo "  WARN: $W trigger 操作失敗 (paused 状態が既に正しい可能性)"
    done
    echo ""
    echo "次回の自動起動時刻 (JST): 09:00 (translator) / 09:05 / 09:10 / 09:15"
    ;;
  status)
    echo "=== Scheduler status ==="
    for W in "${WORKERS[@]}"; do
      STATE=$(gcloud scheduler jobs describe "citify-worker-$W-trigger" \
        --location="$REGION" \
        --format="value(state)" 2>/dev/null || echo "NOT_FOUND")
      LAST=$(gcloud scheduler jobs describe "citify-worker-$W-trigger" \
        --location="$REGION" \
        --format="value(lastAttemptTime)" 2>/dev/null || echo "")
      printf "  %-25s  state=%-10s  last=%s\n" "$W" "$STATE" "$LAST"
    done
    ;;
  run-once)
    # 全 worker を 1 度ずつ手動で実行 (Scheduler を介さない)
    echo "=== Run all workers once (manual trigger) ==="
    for W in "${WORKERS[@]}"; do
      echo "  executing citify-worker-$W (background)"
      gcloud run jobs execute "citify-worker-$W" \
        --region="$REGION" \
        --quiet &
    done
    wait
    echo "✅ all workers triggered (running for up to 59 min each)"
    ;;
  *)
    echo "Usage: $0 {pause|resume|status|run-once}"
    echo ""
    echo "  pause     - 全 Scheduler を停止 (デモ期間終了時)"
    echo "  resume    - 全 Scheduler を起動 (1 日 1 回 09:00 JST から自動稼働)"
    echo "  status    - 現在の状態確認"
    echo "  run-once  - 全 worker を 1 度手動実行 (Scheduler 経由せず即起動)"
    exit 1
    ;;
esac
