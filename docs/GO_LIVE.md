# GO_LIVE.md — 実装済み機能を審査で「live」にする実行チェックリスト

> このセッションで積んだ ①②⑤ の強化はすべて **コード実装・テスト済みだが既定 OFF**
> (現行デモを壊さない段階導入)。審査で加点を確定させるには、以下の **人間による
> GCP/Firebase 操作** が必要。**上から順に「低リスク・高効果」**に並べてある。
>
> 環境: project=`citify-dev` / region=`asia-northeast1` / Cloud Run service=`citify-api`。
> 各手順に **検証** を付けた。まず 1〜3 (低リスク) を、時間があれば 4〜6 を。

---

## 1. ① Ops crew を見せる (操作ほぼ不要・最大効果)

`/ops` は `main` push 済みで Firebase App Hosting / Cloud Run に自動反映される。

- **確認**: ブラウザで `https://citify-web--citify-dev.asia-east1.hosted.app/ops` を開き
  「▶ 運用アセスメントを実行」→ verdict / 所見 / 提案 (人間レビュー必須バッジ) /
  自律トレースが出ること。
- **任意 (推奨)**: 公開を絞るなら Cloud Run に admin token を設定。
  ```bash
  gcloud run services update citify-api --region=asia-northeast1 \
    --update-env-vars OPS_ADMIN_TOKEN=$(openssl rand -hex 16)
  ```
  (未設定なら誰でも閲覧可 = デモでは可)。設定した場合はフロントに token 付与が要るので、
  デモは未設定のままが簡単。
- **効果**: 動画で **Watcher 分析トレースと /ops トレースを 2 画面並置**し「同じアーキ、
  対象違い」を見せる → ① が跳ねる。

## 2. ⑤ 監視アラートを実在させる (terraform apply 1 回・低リスク)

```bash
cd infra/env/dev
# 通知メールを受け取るなら terraform.tfvars に追記: alert_email = "you@example.com"
terraform plan   # 追加されるのは monitoring 3 policy (+ email channel)。既存に破壊なし
terraform apply
```
- **検証**: GCP Console → Monitoring → Alerting に 3 ポリシー
  (`citify-api 5xx` / `p95 latency` / `Pub/Sub DLQ backlog`) が出る。
- **効果**: ⑤「実運用への配慮」が文書上の主張から実リソースになる。

## 3. データ鮮度を保つ (審査期間中)

Scheduler は 07-02 に resume 済み。審査直前に再確認:
```bash
./apps/workers/scripts/toggle-schedulers.sh status   # 5 job が ENABLED か
./apps/workers/scripts/toggle-schedulers.sh run-once  # 直近分を今すぐ処理したい場合
```
- **検証**:
  ```bash
  SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
  apps/api/.venv/bin/python -c "from google.cloud import bigquery; c=bigquery.Client(project='citify-dev'); print(list(c.query('SELECT MAX(ingested_at) FROM \`citify-dev.citify_curated.scored_speeches_latest\`').result())[0][0])"
  ```

## 4. ⑤ BQ MERGE 冪等化 (非prod で 1 バッチ smoke 後に本番フリップ)

```bash
# bq-sink worker (Cloud Run Job) に env を付けて 1 度実行 → 重複が増えないか確認
gcloud run jobs update citify-worker-bq-sink-scored --region=asia-northeast1 \
  --update-env-vars CITIFY_BQ_MERGE=1
gcloud run jobs execute citify-worker-bq-sink-scored --region=asia-northeast1
```
- **検証 (重複が増えないこと)**:
  ```sql
  -- 同一 (speech_id,user_id) が 2 行以上ある = 重複。MERGE 有効後は 0 に収束
  SELECT COUNT(*) AS dup_keys FROM (
    SELECT speech_id, user_id, COUNT(*) c
    FROM `citify-dev.citify_curated.scored_speeches`
    GROUP BY 1,2 HAVING c > 1)
  ```
- **ロールバック**: `--remove-env-vars CITIFY_BQ_MERGE` で stream insert に即復帰。

## 5. ① Concierge を ADK 親子経路で live 化 (フラグ + smoke)

```bash
gcloud run services update citify-api --region=asia-northeast1 \
  --update-env-vars CITIFY_CONCIERGE_ADK=1
```
- **検証**: `/concierge` で 1 往復し、応答が返ること (ADK 経路が落ちても sync に自動
  fallback するのでユーザー影響なし)。Cloud Logging で `concierge.adk_path_failed` が
  出ていなければ ADK 経路が生きている。
- **ロールバック**: `--remove-env-vars CITIFY_CONCIERGE_ADK`。

## 6. ⑤ Firebase 認証 live 化 (中工数) → [AUTH_RUNBOOK.md](AUTH_RUNBOOK.md)

owned-data の user_id → uid 移行が要るため、上記より工数大。手順は AUTH_RUNBOOK 参照。
IDOR を実際に塞ぐので ⑤ を最も引き上げるが、デモ動線への影響確認が必要。

## 7. ② 地方 RAG live 化 (最大工数) → [RAG_RUNBOOK.md](RAG_RUNBOOK.md)

地方議事録テキストの BQ 永続化 (sink 追加 + Terraform テーブル) → Vertex コーパス投入。
export/検索の多ソース対応はコード済み。残るは永続化と課金を伴う import。

---

## 優先度まとめ
- **必ずやる (低リスク・高効果)**: 1 (Ops 可視化) / 2 (監視 apply) / 3 (鮮度)。
- **時間があれば**: 4 (MERGE) / 5 (Concierge ADK) — どちらも env フリップ + 即ロールバック可。
- **工数を取れるなら**: 6 (認証) / 7 (地方RAG) — 加点は大きいが人手が要る。
