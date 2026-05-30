# ミニプラン: Plan CC Cost Anomaly Hunter Agent

## 概要

- **タスク ID**: TASK-CC (バランス版 余裕枠 #2、最終)
- **目的**: GCP リソース (BigQuery / Cloud Run / Firestore / Vertex AI) の日次 cost data から **異常スパイク検知** + 根本原因診断 + 削減提案を 2 段階 Agent で生成。Plan F (Scraper Doctor) と類似パターンの「運用負荷を Agent が肩代わり」演出。ハッカソン審査基準①「マルチエージェント必然性」+ ④「実用性」。
- **完了条件**:
  - `agents/cost_hunter/` 独立モジュール:`CostAnomalyDetector` (純計算、z-score + 急上昇率) + `CostRootCauseAgent` (LLM)
  - 入力:`CostObservation` (date / service / cost_jpy / project_id) の時系列
  - Detector 出力:`CostAnomaly` (anomaly_score / anomaly_type / spike_ratio / baseline_avg)
  - RootCause 出力:`CostRootCauseProposal` (root_cause_hypothesis / proposed_action / monthly_savings_estimate / risk_assessment + `requires_human_review=True` schema 強制)
  - `GET /v1/cost-health?days=30&service=...` endpoint
  - Sample seed (`infra/seed/cost_observations_sample.json`、30 日 × 4 services = 120 行) demo 用
  - Frontend `/admin/costs` page (Plan F `/admin/scrapers` と同パターン、簡易 admin token guard + disclaimer)
  - 12+ unit/integration test、既存 366 件と合わせて全 pass
  - 倫理ガード:Plan PP / F と同じ `_detect_any_leak` を入出力に適用 + `requires_human_review=True` schema 強制
  - docs/AGENT_PROMPTS.md §0.13 + docs/FEATURES.md A-22 追加
- **想定工数**: 2-3 日 (12-18h)、余裕枠で圧縮目標 **10-12h**

---

## 設計

### Agent 構成 (Plan F と一貫)

```
CostAnomalyDetector (純計算、LLM 不要、Plan Z Engine と一貫)
  ├─ 入力: list[CostObservation] (date × service × cost_jpy)
  └─ 出力: list[CostAnomaly]
        ├─ date: date
        ├─ service: str
        ├─ cost_jpy: float
        ├─ baseline_avg_7d: float (過去 7 日平均)
        ├─ baseline_stddev_7d: float
        ├─ z_score: float (現在 vs 過去 7 日)
        ├─ spike_ratio: float (current / baseline)
        ├─ anomaly_type: "spike" | "drift" | "normal"
        └─ severity: "critical" | "high" | "medium" | "low"

CostRootCauseAgent (LLM、Plan F の RepairProposalAgent と一貫)
  ├─ 入力: CostAnomaly + 過去 30 日 cost trend summary
  └─ 出力: CostRootCauseProposal
        ├─ root_cause_hypothesis: str (240 字)
        ├─ proposed_action: "scale_down" | "optimize_query" | "investigate_logs"
        │                   | "rate_limit" | "manual_review"
        ├─ rationale: str (240 字)
        ├─ monthly_savings_estimate_jpy: int (推定削減額)
        ├─ risk_assessment: "safe" | "moderate" | "risky"
        ├─ requires_human_review: bool = True (Plan F と同じ schema 強制)
        └─ source: "llm" | "rule_based"
```

### 異常検知ロジック (純計算、numpy なし)

```python
# Plan Z Engine と一貫した純 Python
def detect_anomalies(observations: list[CostObservation]) -> list[CostAnomaly]:
    """日次 cost data から異常を検知。

    1. service 別に groupby
    2. 各日に対し過去 7 日の (avg, stddev) を計算
    3. z_score = (current - avg) / stddev
    4. spike_ratio = current / avg
    5. anomaly_type 分類:
        - "spike" if z_score > 2 or spike_ratio > 1.5
        - "drift" if stddev > avg * 0.3 (trend あり、変動大)
        - "normal" else
    6. severity 分類: spike_ratio から
        - >3x: critical
        - >2x: high
        - >1.5x: medium
        - <=1.5x: low
    """
```

### Schema 定義

```python
# agents/cost_hunter/schema.py

ServiceName = Literal[
    "bigquery", "cloud_run", "firestore", "vertex_ai",
    "cloud_storage", "pubsub", "other",
]

class CostObservation(BaseModel):
    date: date
    service: ServiceName
    cost_jpy: float = Field(ge=0.0)
    project_id: str = "citify-dev"

class CostAnomaly(BaseModel):
    date: date
    service: ServiceName
    cost_jpy: float
    baseline_avg_7d: float
    baseline_stddev_7d: float
    z_score: float
    spike_ratio: float
    anomaly_type: Literal["spike", "drift", "normal"]
    severity: Literal["critical", "high", "medium", "low"]

class CostRootCauseProposal(BaseModel):
    root_cause_hypothesis: str = Field(max_length=240)
    proposed_action: Literal[...]
    rationale: str = Field(max_length=240)
    # Reviewer Critical: schema レベルで上限 cap (LLM overshoot 構造防止)
    monthly_savings_estimate_jpy: int = Field(ge=0, le=100_000)
    risk_assessment: Literal["safe", "moderate", "risky"]
    requires_human_review: bool = True  # Plan F と同じ schema 強制
    source: Literal["llm", "rule_based"] = "llm"

class CostHealthResponse(BaseModel):
    # ... 既存フィールド ...
    # Reviewer Medium #4: 差別化観点 (Plan F と差をつける)
    cross_service_pattern: str | None = Field(
        default=None,
        max_length=200,
        description="同日に複数 service で spike 検出時の rule-based パターン記述 (e.g. 'deploy 起因の可能性')",
    )

class CostHealthEntry(BaseModel):
    anomaly: CostAnomaly
    proposal: CostRootCauseProposal

class CostHealthResponse(BaseModel):
    period_start: date
    period_end: date
    total_anomalies: int
    by_service: dict[str, int]
    by_severity: dict[str, int]
    estimated_total_savings_jpy: int  # all proposal の合計
    entries: list[CostHealthEntry]
    disclaimer: str = "本ページの削減提案は Agent 推定です。実適用前に IAM / DBA レビュー必須。"
```

### Sample seed (30 日 × 4 services = 120 行)

`infra/seed/cost_observations_sample.json`:
- bigquery: 通常 200-400 円/日、20 日目に 2500 円スパイク (重い ANALYZE クエリ想定)
- cloud_run: 通常 100-150 円/日、25 日目に 800 円スパイク (公開後 traffic 増)
- firestore: 安定 50 円/日、異常なし (normal/baseline 確認用)
- vertex_ai: 通常 300-500 円/日、徐々に 800 円まで drift (LLM 利用増)

→ Detector が 2-3 件 anomaly を検出する想定、CostRootCauseAgent が削減提案を返す。

### Frontend `/admin/costs` 構成 (Plan F `/admin/scrapers` と一貫)

- 簡易 admin token guard (`NEXT_PUBLIC_ADMIN_TOKEN` + URL `?token=...`)
- 常設 disclaimer banner
- 統計サマリ (total_anomalies / by_service / by_severity / estimated_total_savings)
- 異常カード一覧 (折りたたみ、AnomalyBadge + ProposalBadge + monthly_savings + code_hint)

---

## 作業ステップ

### Phase 1 (3h): Schema + CostAnomalyDetector (純計算)

1. [ ] **Step 1.1**: `agents/cost_hunter/` ディレクトリ新規 (`__init__.py` / `schema.py` / `detector.py` / `main.py` / `prompts/system.py`)
2. [ ] **Step 1.2**: Schema 全定義 (CostObservation / CostAnomaly / CostRootCauseProposal / CostHealthEntry / CostHealthResponse)
3. [ ] **Step 1.3**: `CostAnomalyDetector.detect_anomalies()` 実装 (純 Python z-score + spike_ratio + severity 分類)
4. [ ] **Step 1.4**: `agents/cost_hunter/tests/test_detector.py` (6+ test: 正常 / spike / drift / data 不足 / severity 境界)
   - **Reviewer Medium #5 反映**: `drift` を `drift_up` / `drift_down` に分割 (Plan Z の `linear_regression` slope 符号を流用)
5. [ ] **Step 1.5**: `cross_service_pattern` 推定 helper (rule-based、同日 spike 2+ service なら "deploy 起因の可能性")

### Phase 2 (4h): CostRootCauseAgent (LLM) (Reviewer Low #7 工数再配分)

5. [ ] **Step 2.1**: `agents/cost_hunter/prompts/system.py` (Chain-of-Thought + 倫理ガード + Plan F 流用)
6. [ ] **Step 2.2**: `CostRootCauseAgent.propose(anomaly, trend_summary)` 実装
7. [ ] **Step 2.3**: 倫理ガード (Plan PP / F と同じ `_detect_any_leak` を rationale + root_cause_hypothesis に適用) + rule_based fallback
8. [ ] **Step 2.4**: `requires_human_review=True` schema 強制 (Plan F と同じ)
   - **Reviewer High #3 反映**: `proposed_action="scale_down" AND service in ("vertex_ai", "cloud_run")` の組合せはサーバー側で自動で `risk_assessment="risky"` に上書き (ユーザー影響大の誤提案防止)
   - **Reviewer Critical 反映**: `monthly_savings_estimate_jpy` を schema 上限 `le=100_000` + server 側 `min(value, 100_000)` clamp で二重防御
9. [ ] **Step 2.5**: `agents/cost_hunter/tests/test_root_cause.py` (**7+ test**: LLM 成功 / 失敗 / leak / requires_review 強制 / fallback template / scale_down→risky 自動上書き / savings 上限 clamp)

### Phase 3 (2h): GET /v1/cost-health endpoint + sample seed

10. [ ] **Step 3.1**: `infra/seed/cost_observations_sample.json` (30 日 × 4 services、demo 用 anomaly 仕込み)
   - **Reviewer High #2 反映**: spike 値は `baseline_avg + 3*stddev` で逆算、test で `assert len(anomalies) >= 2` を保証
   - **Reviewer Low #6 反映**: seed JSON の date は **生成時 today 起点で過去 30 日** に。fixture loader 側で `today - N days` 変換 (将来日付腐敗回避)
11. [ ] **Step 3.2**: `apps/api/main.py` に `GET /v1/cost-health` endpoint 追加 (Plan F /v1/scraper-health と同パターン)
12. [ ] **Step 3.3**: `apps/api/tests/test_cost_health_endpoint.py` (4+ test)

### Phase 4 (2h): Frontend `/admin/costs` page (Reviewer Low #7 圧縮、Plan F /admin/scrapers 完全踏襲)

13. [ ] **Step 4.1**: `apps/web/src/lib/api.ts` に `fetchCostHealth()` + zod schema
14. [ ] **Step 4.2**: `apps/web/src/app/admin/costs/page.tsx` (Plan F `/admin/scrapers` パターン踏襲、Suspense ラップ + admin token + disclaimer + StatsSummary + AnomalyCard)
15. [ ] **Step 4.3**: `next build` smoke test
16. [ ] **Step 4.4**: ホームに nav リンク追加

### Phase 5 (1h): docs + ruff + 全 regression + commit 提示

17. [ ] **Step 5.1**: `docs/AGENT_PROMPTS.md` §0.13 CostAnomalyHunter
18. [ ] **Step 5.2**: `docs/FEATURES.md` A-22 エントリ
19. [ ] **Step 5.3**: `ruff format/check` + 全 pytest → 全 pass
20. [ ] **Step 5.4**: 推奨 commit 提示 (5 commit 構成)

---

## 成果物

- [ ] `agents/cost_hunter/` 新規 (5 ファイル + tests)
- [ ] `infra/seed/cost_observations_sample.json` (120 行)
- [ ] `apps/api/main.py` + `test_cost_health_endpoint.py`
- [ ] `apps/web/src/app/admin/costs/page.tsx`
- [ ] docs 2 ファイル更新

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| **LLM が過激な action 提案** (例: 「全機能停止すべき」) | 高 | `requires_human_review=True` schema 強制、proposed_action enum で許可 action 限定、risk_assessment "risky" の明示 |
| **monthly_savings_estimate_jpy の過大予測** | 中 | LLM 出力後に `max(monthly_savings, 0)` で clamp、enum 設定で上限 (一律 月 100,000 円上限 cap) |
| **cost data 公開リスク** (組織内財務情報) | 中 | `/admin/costs` に admin token guard (Plan F と同パターン)、disclaimer で「demo data」明示 |
| **Plan F とのコード重複** | 低 | 構造的に類似は意図的 (パターン統一)、共通化は将来検討 |
| **倫理 leak (政治家名 / 地域名)** | 低 | 通常 cost data には混入しないが、念のため `_detect_any_leak` を rationale に適用 |
| **z-score 計算でゼロ除算** (stddev=0) | 低 | stddev=0 なら z_score=0 で normal 扱い、graceful |

---

## Out of Scope (Plan CC では実装しない)

- 実 GCP Billing API 連携 (BigQuery export 経由)、MVP は sample seed のみ
- 自動 cost 削減 action 実行 (人間レビュー前提、Plan F と同じ Out of Scope)
- 予算 alert / 通知連携 (Slack/メール)、別 Plan
- 複数 GCP project 横断分析、1 project (citify-dev) のみ
- 月次 forecast (Plan Z の forecast engine を流用すれば将来可能)
- ADK 化

---

## 受け入れ条件 (Definition of Done)

- [ ] `pytest agents/ apps/api/tests/` → 全 pass (366 + 新規 12+ = 378+)
- [ ] `CostAnomalyDetector.detect_anomalies` が spike を検知 (sample seed の 2-3 件)
- [ ] `CostRootCauseAgent.propose` が LLM 失敗時に rule_based fallback
- [ ] 倫理 leak 検出時は fallback、leaked 文字列ユーザー向けに残らない
- [ ] `CostRootCauseProposal.requires_human_review` は schema 既定で True、LLM が False を返してもサーバー側で True 上書き (Plan F と同じ構造防止)
- [ ] `GET /v1/cost-health?days=30` で 200 + CostHealthResponse
- [ ] Frontend `/admin/costs` page で disclaimer + 統計 + AnomalyCard 表示
- [ ] `next build` pass、`tsc --noEmit` pass
- [ ] docs 2 ファイル更新
- [ ] 推奨 commit message 提示
