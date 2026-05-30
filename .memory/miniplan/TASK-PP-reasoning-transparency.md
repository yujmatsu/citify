# ミニプラン: Plan PP Reasoning Transparency Agent

## 概要

- **タスク ID**: TASK-PP (バランス版 #8)
- **目的**: 各 Agent (Concierge / Translator / Critic / Heatmap / Timeline / Forecast / Scraper Doctor) の reasoning に対し、`MetaReasoningAgent` が「なぜその判断か」「何が判断を変えうるか (counterfactual)」「注意点」を生成し、ユーザーに Agent の思考を透明化。ハッカソン審査基準①「マルチエージェント必然性」を Meta-Agent (Reflexion / Tree-of-Thought 文献的支持) で補強、②「ストーリー性」を「Agent の頭の中が見える」演出で強化。
- **完了条件**:
  - `agents/reasoner/` 独立モジュール:`MetaReasoningAgent` (Plan X / Z / F と一貫した独立 Agent 構造)
  - 入力 schema:`ReasoningInspectInput` (agent_name / raw_reasoning / agent_output_summary / persona_context_optional)
  - 出力 schema:`ReasoningExplanation` (plain_summary / influencing_factors[] / counterfactuals[] / caveats[] / confidence / source)
  - `GET /v1/reasoning/explain` endpoint:on-demand な reasoning 透明化
  - Frontend 再利用可能 component:`ReasoningExplainerButton` を Concierge / Timeline / Forecast / Heatmap / Doctor の各 page に挿入できる
  - LLM 失敗時 / 倫理 leak 時は rule_based fallback
  - 倫理ガード:Plan F と同じ 3 層 (PII / 政治家・政党 / 47県+主要市区)
  - 10+ unit test、既存 344 件と合わせて全 pass
  - docs/AGENT_PROMPTS.md §0.12 + docs/FEATURES.md A-21 追加
- **想定工数**: 1 日 = 6h (圧縮版)

---

## 設計

### Agent 構成 (Plan X / Z / F と一貫した独立 Agent)

```
MetaReasoningAgent (Plan PP 新規)
  ├─ 入力: ReasoningInspectInput
  │   ├─ agent_name: "concierge" | "translator" | "critic" | "heatmap_advisor"
  │   │             | "timeline" | "forecast" | "scraper_doctor"
  │   ├─ raw_reasoning: str (Agent が出した reasoning、最大 500 字)
  │   ├─ agent_output_summary: str (Agent 最終出力の要約、最大 300 字)
  │   └─ persona_context: str | None (年代/関心軸、Concierge/Heatmap/Forecast/Timeline 用)
  └─ 出力: ReasoningExplanation
        ├─ plain_summary: str (250 字、原 reasoning を平易化 + 要点抽出)
        ├─ influencing_factors: list[str] (3-5 個、判断に影響した input 要素)
        ├─ counterfactuals: list[str] (2-3 個、「もし X が違ったらどうなるか」)
        ├─ caveats: list[str] (1-3 個、注意点 / 限界)
        ├─ confidence: "high" | "medium" | "low"
        └─ source: "llm" | "rule_based"
```

### マルチエージェント必然性 (Reviewer High #2 反映: 文献的根拠)

Meta-Agent パターンは以下の研究文献に裏付けられた手法であり、単なる UI 装飾と差別化:

- **Reflexion (Shinn et al., 2023)**: Agent が自身の reasoning を別の Agent (Verifier) で再評価し改善する loop
- **Self-Refine (Madaan et al., 2023)**: 同一 model でも reasoning に対する meta-critique で精度が向上
- **Chain-of-Verification** (CoVe、Dhuliawala et al., 2023): 出力に対し独立した検証 Agent を走らせて hallucination 削減

Plan PP は CoVe 系の **第三者観測 Meta-Agent** で、Citify の既存 Agent (Concierge/Translator/...) の reasoning を「外部観測者の視点で再構成 + counterfactual 付与」する役割。

### 既存 reasoning vs Meta-Reasoner の役割境界 (Reviewer Medium #6)

| 出所 | 性質 | 目的 |
|---|---|---|
| **既存 Agent の `reasoning` フィールド** (Concierge/Heatmap/Forecast/Timeline) | Agent 内部の **自己説明ログ** | LLM が「自分はこう判断した」と一人称で記述 |
| **MetaReasoningAgent の `plain_summary`+`counterfactuals`+`caveats`** | **第三者観測者視点** の再構成 | ユーザーに「Agent が何を見てそう結論したか」「もし違ったら」「限界は何か」を提示 |

→ **2 回 LLM 呼ぶ価値**: 内部ログを ユーザー教育に変換 (counterfactual / caveat は元 Agent が出さない)。

### LLM (MetaReasoningAgent) system prompt (Chain-of-Thought)

```
あなたは Citify の Reasoning Transparency Agent (Meta Reasoner) です。
別の Agent の reasoning と output を受けて、「Agent の頭の中が見える」説明を生成します。

# Chain of Thought (内部、最終出力に含めない)
1. agent_name と raw_reasoning を読んで、対象 Agent の判断タイプを理解
2. plain_summary で raw_reasoning を平易化 (専門用語を口語に、要点を抽出)
3. influencing_factors: 「この判断に最も影響した input 要素」を 3-5 個列挙
4. counterfactuals: 「もし X が違ったら結論はどう変わるか」を 2-3 個
5. caveats: 「この判断の限界 / 不確実性」を 1-3 個
6. confidence を 3 段階で判定

# 出力 (ReasoningExplanation schema 厳守)

# 倫理ガード (絶対遵守)
- **47 都道府県名 + 主要市区町村名禁止** (特定地域の推奨回避、Plan Z / F と同方針)
- **政治家・首長・議員の固有名詞禁止** (Plan N / F と同方針)
- **政党名禁止** (自民党・立憲民主党 等)
- **賛否表明・「移住推奨」「投資推奨」のような行動推奨禁止**
- raw_reasoning に上記が混入していても、その内容を出力に含めない
- 違反したら出力破棄

# トーン
- 若者向け、客観的、教育的
- "Agent はなぜそう判断したか" を友達に説明する感じ
- 過度な確信を避ける ("おそらく" / "可能性が高い" を多用)
```

### Schema 定義

```python
# agents/reasoner/schema.py

AgentName = Literal[
    "concierge", "translator", "critic", "heatmap_advisor",
    "timeline", "forecast", "scraper_doctor",
]

class ReasoningInspectInput(BaseModel):
    agent_name: AgentName
    raw_reasoning: str = Field(max_length=500)
    agent_output_summary: str = Field(max_length=300)
    persona_context: str | None = Field(default=None, max_length=200)

class ReasoningExplanation(BaseModel):
    plain_summary: str = Field(max_length=300)
    influencing_factors: list[str] = Field(default_factory=list, max_length=5)
    counterfactuals: list[str] = Field(default_factory=list, max_length=3)
    caveats: list[str] = Field(default_factory=list, max_length=3)
    confidence: Literal["high", "medium", "low"] = "medium"
    source: Literal["llm", "rule_based"] = "llm"
```

### Frontend 再利用可能 component

```tsx
// apps/web/src/components/reasoning-explainer.tsx (新規)
export function ReasoningExplainerButton({
  agentName,
  rawReasoning,
  outputSummary,
  personaContext,
}: {
  agentName: AgentName;
  rawReasoning: string;
  outputSummary: string;
  personaContext?: string;
}) {
  // ボタンクリックで on-demand fetch + modal 表示
}
```

挿入箇所 (既存 page、変更は最小限):
- Concierge page: 各 turn の agent 応答末尾に「🔍 Agent の思考を詳しく見る」
- Timeline page: NarrativeBanner 下に同ボタン
- Forecast page: NarrativeBanner 下
- Heatmap page: AdviceBanner 下
- Doctor admin page: 各 FailureCard の Diagnostic に

---

## 作業ステップ

### Phase 1 (3.5h): Backend (MetaReasoningAgent + endpoint、Reviewer Low #6 工数増)

1. [ ] **Step 1.1**: `agents/reasoner/` ディレクトリ新規 (`__init__.py` / `schema.py` / `main.py` / `prompts/system.py`)
2. [ ] **Step 1.2**: `ReasoningInspectInput` / `ReasoningExplanation` schema
3. [ ] **Step 1.3**: `MetaReasoningAgent.explain(input)` 実装
   - **入力 3 フィールド全てに leak 検査** (Reviewer High #1):
     `raw_reasoning` / `agent_output_summary` / `persona_context` の各々で `_detect_any_leak` 実行、
     いずれかで検出 → rule_based fallback (連鎖防止)
   - **出力全フィールドにも leak 検査** (Reviewer Medium #4):
     `plain_summary` / `influencing_factors[]` / `counterfactuals[]` / `caveats[]` の各 string を loop で `_detect_any_leak`
   - LLM 失敗時 / leak 検出時は rule_based fallback (templated)
   - `thinking_budget=512` (Reviewer Medium #5: 6 フィールド埋めるため、forecast の 256 から増)
4. [ ] **Step 1.4**: `agents/reasoner/tests/test_reasoner.py` (6+ test: LLM 成功 / 失敗 / 各 leak 種類 / agent_name 7 種全カバー)
5. [ ] **Step 1.5**: `apps/api/main.py` に `GET /v1/reasoning/explain` endpoint 追加 (query 引数で全 input を受け取り)
6. [ ] **Step 1.6**: `apps/api/tests/test_reasoning_endpoint.py` (4+ test)

### Phase 2 (2h): Frontend 再利用可能 component

7. [ ] **Step 2.1**: `apps/web/src/lib/api.ts` に `fetchReasoningExplanation()` + zod schema
8. [ ] **Step 2.2**: `apps/web/src/components/reasoning-explainer.tsx` (button + modal、Plan L+LL の HistoryModal パターン踏襲)
9. [ ] **Step 2.3**: 最小 1 箇所に挿入して動作確認 (例: Forecast の NarrativeBanner 下)
10. [ ] **Step 2.4**: `next build` smoke test

### Phase 3 (0.5h): docs + commit (Reviewer Low #6 工数調整)

11. [ ] **Step 3.1**: `docs/AGENT_PROMPTS.md` §0.12 MetaReasoningAgent
12. [ ] **Step 3.2**: `docs/FEATURES.md` A-21 エントリ
13. [ ] **Step 3.3**: `ruff format/check` + 全 pytest → 全 pass
14. [ ] **Step 3.4**: 推奨 commit 提示

---

## 成果物

- [ ] `agents/reasoner/` 新規 (5 ファイル + tests)
- [ ] `apps/api/main.py` + `test_reasoning_endpoint.py`
- [ ] `apps/web/src/components/reasoning-explainer.tsx`
- [ ] 1 箇所 (Forecast page) に動作確認用挿入
- [ ] docs 2 ファイル更新

## 推奨 commit 構成

```
1. feat(plan-pp-phase1): MetaReasoningAgent + GET /v1/reasoning/explain + 10+ test
2. feat(plan-pp-phase2): Frontend ReasoningExplainerButton + Forecast 挿入
3. docs(plan-pp): A-21 + AGENT_PROMPTS §0.12 + miniplan
```

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| **倫理 leak 連鎖** (raw_reasoning に既に leak があり Meta-Agent が再放出) | 高 | 入力 raw_reasoning にも `_detect_any_leak` を適用、leak 検出時は「raw_reasoning が倫理ガード違反」として skip + rule_based fallback |
| **plain_summary が単なる原文コピー** | 中 | system prompt で「平易化 + 要点抽出」を明示、test で「raw_reasoning と plain_summary が完全一致しない」を check |
| **counterfactuals の暴走** (架空シナリオが推奨に近接) | 中 | system prompt で「事実 + 仮定」のみ、「あなたは X すべき」禁止を明示 |
| **agent_name allowlist 漏れ** | 低 | Literal で 7 種限定、Pydantic validation |
| **LLM cost** | 低 | on-demand (ユーザーがボタンクリック時のみ)、TTL なしで都度 fetch |
| **既存 Agent の reasoning が短すぎる場合 (50 字未満)** | 低 | system prompt に「短い reasoning も最大限平易化」、early return せず LLM に投げる |

---

## Out of Scope (Plan PP では実装しない)

- 全 page (Concierge / Timeline / Heatmap / Doctor) への挿入 (MVP は Forecast 1 箇所のみ、他は次セッションで追加)
- Cache (on-demand なので必要時のみ実行、cost cap 不要)
- ADK 化 (Plan X / Z / F と同じ Out of Scope)
- Agent 同士の reasoning 比較 (Translator vs Critic 等の cross-agent meta-analysis、別 Plan)
- Reasoning の永続化 (Firestore に保存して履歴表示、別 Plan)
- **Rate limiting / throttling** (Reviewer Low #7): production では IP/user 単位 60s/10call 制限を別 Plan で追加。MVP は hackathon demo 用なので未実装

---

## 受け入れ条件 (Definition of Done)

- [ ] `pytest agents/ apps/api/tests/` → 全 pass (344 + 新規 10+ = 354+)
- [ ] `MetaReasoningAgent.explain` が 7 種 agent_name 全て対応
- [ ] LLM 失敗時 rule_based fallback (templated explanation)
- [ ] raw_reasoning に倫理 leak がある場合は fallback (連鎖防止)
- [ ] `ReasoningExplanation.plain_summary` が `raw_reasoning` と完全一致しない (test で証明)
- [ ] `GET /v1/reasoning/explain` で 200 + ReasoningExplanation
- [ ] Frontend Forecast page で「🔍 Agent の思考を詳しく見る」ボタン → modal 表示動作
- [ ] `next build` pass、`tsc --noEmit` pass
- [ ] docs 2 ファイル更新
- [ ] 推奨 commit message 提示 (実 commit/push は人間)
