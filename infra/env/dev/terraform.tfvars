# Citify dev 環境 — terraform.tfvars テンプレ
#
# 使い方:
#   cp terraform.tfvars.example terraform.tfvars
#   # 必要に応じて値を編集
#   terraform init
#   terraform plan
#   terraform apply
#
# 注: terraform.tfvars は .gitignore 推奨 (実値を含むため)。
#     このテンプレ (.example) のみコミットする。

project_id   = "citify-dev"
region       = "asia-northeast1"
env          = "dev"
github_owner = "yujmatsu"
github_repo  = "citify"

# 審査期間はデータ鮮度を保つため Scheduler を resume 状態で宣言的に固定。
# (既定 true = paused。手動 resume は terraform apply で paused に戻されるため、
#  ここで false にして「resumed」を宣言状態にする。審査終了後にコスト最小化なら true へ)
schedulers_paused = false
