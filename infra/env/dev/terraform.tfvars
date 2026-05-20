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
