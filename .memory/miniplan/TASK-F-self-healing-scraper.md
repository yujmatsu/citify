# ミニプラン: Plan F Self-healing Scraper Agent

## 概要

- **タスク ID**: TASK-F (バランス版 #6、ハッカソン審査主役 #1)
- **目的**: スクレイパー失敗ログを 2 段階 Agent (`DiagnosticAgent` + `RepairProposalAgent`) で診断 + 修正提案を生成、人間レビュー可能な形で表示。**自動 PR / 自動 commit はせず、提案のみ生成 (倫理ガード + 安全性)**。ハッカソン審査基準①「マルチエージェント必然性」の主役機能の 1 つで、Citify の運用ストーリー (「Agent が運用負荷を肩代わり」) を体現。
- **完了条件**:
  - `ScraperFailureLog` schema (timestamp / scraper / tenant_id / municipality_code / error_type / stack_trace / html_snippet / url)
  - `agents/scraper_doctor/` 独立モジュール:`DiagnosticAgent` (failure log → エラーカテゴリ + 根本原因) + `RepairProposalAgent` (root_cause → 修正提案 + risk 評価)
  - **Self-healing は提案のみ、自動修正は実装しない** (PROJECT.md §5 倫理境界)。提案は人間レビュー前提
  - Firestore `scraper_failures` collection に失敗ログ保存 (10 件 sample data を seed として用意、demo 用)
  - `GET /v1/scraper-health` endpoint:過去 N 日の失敗統計 + 上位失敗パターン + Agent 診断 + 修正提案
  - Frontend `/admin/scrapers` page:失敗ログ一覧 + 各失敗の Diagnostic + RepairProposal をカード表示
  - **Disclaimer banner 常設**:「Agent は提案を生成するのみ、自動修正は適用されません」
  - 倫理ガード:LLM に渡す html_snippet は PII 含む可能性ありなので **メールアドレス / 電話番号 regex でマスク**
  - 12+ unit/integration test、既存 284 件と合わせて全 pass
  - docs/AGENT_PROMPTS.md §0.11 + docs/FEATURES.md A-20 追加
- **想定工数**: 4-5 日 = 24-30h、MVP に絞って **20-24h** 着地目標

---

## 設計

### Agent 構成 (2 段階、Plan X / Z と一貫)

```
DiagnosticAgent (Plan F 新規 1/2)
  ├─ 入力: ScraperFailureLog (timestamp / scraper / tenant / error / stack / html_snippet)
  └─ 出力: DiagnosticResult
        ├─ error_category: "ssl_failure" | "auth_403" | "html_structure_change"
        │                  | "robots_disallow" | "network_timeout" | "rate_limit"
        │                  | "parser_logic" | "unknown"
        ├─ root_cause_text: str (200 字、なぜ失敗したか)
        ├─ confidence: "high" | "medium" | "low"
        └─ severity: "critical" | "high" | "medium" | "low"

RepairProposalAgent (Plan F 新規 2/2)
  ├─ 入力: DiagnosticResult + ScraperFailureLog
  └─ 出力: RepairProposal
        ├─ proposed_action: "user_agent_change" | "retry_strategy_adjust"
        │                   | "parser_path_update" | "drop_tenant"
        │                   | "robots_check" | "manual_review"
        ├─ rationale: str (200 字、なぜこの修正案か)
        ├─ code_hint: str (300 字、人間が編集すべき diff のヒント、実コードではない)
        ├─ risk_assessment: "safe" | "moderate" | "risky"
        └─ requires_human_review: bool (常に True、構造的安全性)
```

### Self-healing flow (人間レビュー前提)

```
1. Scraper 実行中に例外発生 → try/except でキャッチ
2. ScraperFailureLog を Firestore `scraper_failures` collection に書き込み
   - html_snippet は 2000 字 cap + PII regex マスク (email/phone)
3. GET /v1/scraper-health がトリガーされたタイミング (batch、demo は手動 trigger 可)
   - 過去 N 日の失敗を Firestore から取得
   - 各失敗を DiagnosticAgent + RepairProposalAgent に通す (失敗種別ごとに 1 回 LLM call、cost cap)
4. response に DiagnosticResult + RepairProposal を含めて return
5. Frontend `/admin/scrapers` で表示
6. **人間がレビューして手動で修正 commit** (Auto-PR / Auto-commit は実装しない)
```

### LLM コスト制御

- 同一 (scraper, error_category, html_signature) の失敗は **重複排除** (1 失敗パターン = 1 LLM call)
- `_DOCTOR_CACHE` TTL=1 時間
- 過去 N 日の失敗を最大 50 件まで処理 (それ以上は別 batch)

### PII マスクパターン (Reviewer Critical 予防 + Reviewer High #1 拡張)

```python
PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Email
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[email]"),
    # 携帯 090/080/070 (Reviewer High #1)
    (re.compile(r"0[789]0-\d{4}-\d{4}"), "[phone]"),
    # 固定電話 (市外局番 1-4 桁)
    (re.compile(r"0\d{1,4}-\d{1,4}-\d{4}"), "[phone]"),
    # 〒郵便番号
    (re.compile(r"〒\d{3}-\d{4}"), "[zip]"),
    (re.compile(r"\d{3}-\d{4}"), "[zip]"),
    # IPv4 (Reviewer High #1)
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[ipv4]"),
    # Authorization Bearer / Cookie / session token (Reviewer High #1)
    (re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE), "Authorization: Bearer [token]"),
    (re.compile(r"Cookie:\s*[^\s]+", re.IGNORECASE), "Cookie: [redacted]"),
    (re.compile(r"session_id=[A-Za-z0-9._\-]+", re.IGNORECASE), "session_id=[token]"),
    # URL クエリ内の token / api_key
    (re.compile(r"([?&])(api[_-]?key|token|secret)=[^&\s]+", re.IGNORECASE), r"\1\2=[redacted]"),
]

def mask_pii(text: str) -> str:
    for pattern, repl in PII_PATTERNS:
        text = pattern.sub(repl, text)
    return text
```

**テスト網羅 (Phase 1.5、20+ ケース)**:
- email (foo@bar.com / 日本ドメイン / Unicode)
- 固定電話 (03-xxxx-xxxx / 0463-xxx-xxxx)
- 携帯 (090/080/070-xxxx-xxxx)
- 郵便番号 (〒100-0001 / 100-0001)
- IPv4 (10.0.0.1 / 172.16.x.x / 256.x.x.x 不正値も合わせて確認)
- Authorization Bearer token (大文字小文字混在)
- Cookie session
- URL内 api_key / token / secret
- マスクされない: 普通の文字列 / 日付 (2026-03-25) / バージョン番号 (v1.2.3)

### Schema 定義

```python
# agents/scraper_doctor/schema.py

class ScraperFailureLog(BaseModel):
    failure_id: str  # ULID or {scraper}__{timestamp}
    timestamp: datetime
    scraper: Literal["kaigiroku_net", "kokkai", "press_rss", "reinfolib", "voices_asp", "discussnet", "other"]
    tenant_id: str | None  # 例: prefokayama
    municipality_code: str | None
    url: str | None  # 失敗対象 URL
    error_type: str  # 例: "SSLError" / "HTTPError 403" / "ParserError"
    stack_trace: str  # max 2000 字
    html_snippet: str | None = None  # max 2000 字、PII マスク済
    duration_ms: int | None = None

class DiagnosticResult(BaseModel):
    error_category: Literal[...]
    root_cause_text: str  # max 240 字
    confidence: Literal["high", "medium", "low"]
    severity: Literal["critical", "high", "medium", "low"]
    source: Literal["llm", "rule_based"]

class RepairProposal(BaseModel):
    proposed_action: Literal[...]
    rationale: str  # max 240 字
    code_hint: str  # max 300 字
    risk_assessment: Literal["safe", "moderate", "risky"]
    requires_human_review: bool = True
    source: Literal["llm", "rule_based"]

class ScraperHealthEntry(BaseModel):
    failure: ScraperFailureLog
    diagnostic: DiagnosticResult
    proposal: RepairProposal

class ScraperHealthResponse(BaseModel):
    period_start: datetime
    period_end: datetime
    total_failures: int
    by_category: dict[str, int]  # category → count
    by_scraper: dict[str, int]  # scraper → count
    entries: list[ScraperHealthEntry]  # 上位 N 件 (重複排除済)
    drop_candidates: list[str]  # proposed_action="drop_tenant" な tenant_id 一覧
```

### BQ 連携 (将来) vs Firestore (MVP)

| 選択肢 | 採用 | 理由 |
|---|---|---|
| Firestore | ✅ MVP | 書き込み latency 低 + read 簡単、scraper 実行中の同期書き込みに適 |
| BQ scraper_runs | ⏸️ 将来 | 既存 schema `citify_analytics.scraper_runs` あり、後日統計用に同期可 |

### Frontend `/admin/scrapers` 構成

- 上部 disclaimer banner (常設、Auto-修正は適用されない明示)
- 統計サマリ (total / by_category / by_scraper)
- Drop 候補リスト (proposed_action="drop_tenant" な tenant_id)
- 失敗カード一覧:
  - 失敗 metadata (timestamp / scraper / tenant / URL)
  - DiagnosticResult (category badge + root cause + severity + confidence + source 区別)
  - RepairProposal (action badge + rationale + code_hint + risk_assessment)
  - 「コピー」ボタンで code_hint をクリップボードに

---

## 作業ステップ

### Phase 1 (5-6h): Schema + Firestore 失敗ログ層 + PII マスク

1. [ ] **Step 1.1**: `agents/scraper_doctor/` ディレクトリ新規 (`__init__.py` / `schema.py` / `pii.py` / `firestore_repo.py`)
2. [ ] **Step 1.2**: `ScraperFailureLog` / `DiagnosticResult` / `RepairProposal` schema 定義
3. [ ] **Step 1.3**: PII マスク (`mask_pii`) 実装 + email/phone/zip パターン
4. [ ] **Step 1.4**: `FailureLogRepository` (Firestore CRUD: save_failure / fetch_recent / dedupe)
   - `html_signature` (Reviewer Low #7): HTML タグ構造のみ抽出 (BeautifulSoup の tag-only skeleton)
     → `sha256[:16]` でハッシュ化、同じ DOM 構造の失敗を集約 (`scraper + category + html_signature` で重複排除)
5. [ ] **Step 1.5**: `agents/scraper_doctor/tests/test_pii.py` + `test_firestore_repo.py` (5+ test)

### Phase 2 (5-6h): DiagnosticAgent + RepairProposalAgent (LLM)

6. [ ] **Step 2.1**: `agents/scraper_doctor/prompts/system.py` (DIAGNOSTIC + REPAIR 2 系統 system prompt)
7. [ ] **Step 2.2**: `DiagnosticAgent.diagnose(failure)` 実装 (LLM + rule_based fallback)
8. [ ] **Step 2.3**: `RepairProposalAgent.propose(diagnostic, failure)` 実装 (LLM + rule_based fallback)
9. [ ] **Step 2.4**: 両 Agent の `requires_human_review=True` を schema 強制 (Auto-PR 構造防止)
   - **Reviewer High #2**: `DiagnosticAgent` 出力 (`root_cause_text`) と `RepairProposalAgent` 出力
     (`rationale` / `code_hint`) の **両方** で `_detect_any_leak()` (forecast/main.py 流用) を実行、
     leak 検出時は rule_based fallback に degrade
10. [ ] **Step 2.5**: `agents/scraper_doctor/tests/test_doctor.py` (Diagnostic 3+ + Repair 3+ + leak 検出 2+ = 8+ test)

### Phase 3 (4h): GET /v1/scraper-health endpoint + sample data

11. [ ] **Step 3.1**: `GET /v1/scraper-health?days=7&limit=50` endpoint 追加
12. [ ] **Step 3.2**: Firestore から失敗 fetch → 重複排除 (scraper + category + html_signature) → 2 Agent 並列処理
13. [ ] **Step 3.3**: `_SCRAPER_HEALTH_CACHE` TTL=1 時間
14. [ ] **Step 3.4**: `apps/api/tests/test_scraper_health_endpoint.py` (4+ test)
15. [ ] **Step 3.5**: Sample failure seed (`infra/seed/scraper_failures_sample.json`、**10 件 demo 用、5 scraper × 2 件で実 error_type を反映**、Reviewer Medium):
   - kaigiroku_net × 2 (SSL証明書失効 / HTML 構造変更)
   - kokkai × 2 (HTTP 503 / API レート制限)
   - press_rss × 2 (feedparser ParseError / 404)
   - voices_asp × 2 (robots.txt Disallow / timeout)
   - reinfolib × 2 (JSON schema 変更 / 認証失敗)
16. [ ] **Step 3.6**: `failure_id` 命名規約を **BQ scraper_runs.run_id と互換性ある形式** (`{scraper}__{timestamp_iso}__{seq:04d}`) に統一 (Reviewer Medium、将来の BQ 同期向け)

### Phase 4 (5h): Frontend `/admin/scrapers` page (Reviewer Low 工数バッファ反映)

16. [ ] **Step 4.1**: `apps/web/src/lib/api.ts` に `fetchScraperHealth()` + zod schema
17. [ ] **Step 4.2**: `apps/web/src/app/admin/scrapers/page.tsx` (Disclaimer + 統計 + Drop 候補 + 失敗カード一覧)
   - **簡易 admin ガード** (Reviewer Medium): `NEXT_PUBLIC_ADMIN_TOKEN` env と URL `?token=...` を比較、
     不一致なら「This page is restricted」と表示 (本格 IAM 認証は production で別実装、docs に明記)
18. [ ] **Step 4.3**: `FailureCard` component (DiagnosticBadge + RepairBadge + code_hint コピー)
19. [ ] **Step 4.4**: `next build` smoke test

### Phase 5 (2-3h): docs + nav + ruff + 全 regression

20. [ ] **Step 5.1**: ホームに「🩺 Scraper Health (admin)」リンク追加 (admin 用)
21. [ ] **Step 5.2**: `docs/AGENT_PROMPTS.md` §0.11 ScraperDoctor
22. [ ] **Step 5.3**: `docs/FEATURES.md` A-20 エントリ
23. [ ] **Step 5.4**: `ruff format/check` + 全 pytest → 全 pass

### Phase 6 (0.5h): commit 提示

---

## 成果物

- [ ] `agents/scraper_doctor/` 新規 (8 ファイル + tests)
- [ ] `apps/api/main.py` + `test_scraper_health_endpoint.py`
- [ ] `apps/web/src/app/admin/scrapers/page.tsx`
- [ ] `infra/seed/scraper_failures_sample.json`
- [ ] docs 2 ファイル更新

## 推奨 commit 構成

```
1. feat(plan-f-phase1): ScraperFailureLog schema + PII mask + FailureLogRepository
2. feat(plan-f-phase2): DiagnosticAgent + RepairProposalAgent + 6+ unit test
3. feat(plan-f-phase3): GET /v1/scraper-health endpoint + sample seed + 4+ endpoint test
4. feat(plan-f-phase4): Frontend /admin/scrapers + FailureCard
5. docs(plan-f): A-20 + AGENT_PROMPTS §0.11 + miniplan
```

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| **html_snippet が PII を含むまま LLM に送られる** | 高 | mask_pii() で email/phone/zip を regex マスク、20 件超の Unicode テストで網羅検証 |
| **Auto-PR / Auto-commit が誤って実装される** | 高 | schema レベルで `requires_human_review: bool = True` 強制、UI で disclaimer 常設、Out of Scope に明記 |
| **LLM cost 暴走** (失敗が増えると LLM call も増) | 中 | 重複排除 (scraper + category + html_signature) で 1 失敗パターン = 1 call、TTL 1 時間、過去 N 日 50 件上限 |
| **既存 scraper への性能影響** | 低 | MVP では既存 scraper 改修なし、Firestore 書き込みは別 task (将来)。MVP は sample seed で demo |
| **html_signature ハッシュの衝突** | 低 | sha256[:16] 使用、衝突確率無視可能 |
| **倫理: 自治体名 leak** (RepairProposal で「○○市は drop すべき」など) | 中 | Plan Z の `_detect_geographic_leak` 流用、leak 検出時は rule_based fallback |
| **/admin/scrapers の認証** | 中 | MVP は認証なし (hackathon demo)、production は IAM 認証推奨と docs に明記 |

---

## Out of Scope (Plan F では実装しない)

- **Auto-PR 自動作成** (人間レビュー前提が大前提、絶対禁止)
- **既存 scraper コードへの try/except 自動挿入** (MVP では sample seed のみ)
- **GitHub Issue / Slack 通知連携** (将来 Plan F-2)
- BQ scraper_runs テーブルへの同期 (将来)
- ScraperDoctor の ADK 化 (Plan X / Z と同じ Out of Scope)
- Real-time 修復 (定期 batch でユーザー操作トリガーのみ)
- 多言語 PII マスク (日本語 only、英語電話は scope 外)

---

## 受け入れ条件 (Definition of Done)

- [ ] `pytest agents/ apps/api/tests/` → 全 pass (284 + 新規 12+ = 296+)
- [ ] `mask_pii("foo@bar.com 03-1234-5678 〒100-0001")` → email/phone/zip すべて置換
- [ ] `DiagnosticAgent` LLM 失敗 → rule_based fallback (`source="rule_based"`)
- [ ] `RepairProposal.requires_human_review` は schema で `True` 固定 (Auto-PR 構造防止)
- [ ] 自治体名 leak 検出時は fallback、leaked 文字列がユーザー向け文に残らない
- [ ] `GET /v1/scraper-health?days=7` で 200 + ScraperHealthResponse
- [ ] Frontend `/admin/scrapers` で **disclaimer + 統計 + Drop 候補 + 失敗カード** 表示
- [ ] `next build` pass、`tsc --noEmit` pass
- [ ] docs 2 ファイル更新
- [ ] 推奨 commit message 提示 (実 commit/push は人間)
