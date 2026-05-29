# ミニプラン: E - 街診断 Migration Concierge Agent

## 概要

- **タスクID**: TASK-E (バランス版 #2 / ユーザー価値の主役)
- **目的**:
  ユーザーが「26歳、リモートワーク、子育て予定」のような自然言語を入れたら、Concierge Agent が **1,917 自治体 × 12 統計指標 + scored_speeches + 既存 endpoint** を tool として叩き、**TOP5 候補 + トレードオフ表 + 議論されている政策** を返す対話型 Agent を実装する。

  Plan C で揃った ADK 基盤 (Translator/Relevance/Distributor の `as_tool()`) を **親子階層 (Concierge → 3 sub-agents)** として活用、ハッカソン審査基準①「マルチエージェント必然性」を体現する。

- **完了条件**:
  1. `agents/concierge/` 配下に Concierge ADK Agent 実装 (`adk_agent.py` + `tools.py` + `prompts/system.py`)
  2. ADK Tools: `search_municipalities` / `compare_municipalities` / `fetch_city_dashboard` / `fetch_city_speeches` の 4 つ実装
  3. **既存 ADK wrapper (Plan C) を sub-agent として組み込み**: `ADKTranslatorAgent.as_tool()` 等を Concierge の tools に追加 (= 親子階層成立)
  4. `apps/api/main.py` に `POST /v1/concierge` endpoint 追加 (request: 自然言語 + persona、response: agent reply + tool calls 履歴)
  5. `apps/web/src/app/concierge/page.tsx` 新規: chat-style UI、入力 + agent reply (streaming or polling)
  6. 新規 unit tests + integration test (~30 tests)
  7. ruff format/check pass、98+30=128 tests 全 pass、regression なし
  8. **demo スクリプト** `agents/demo_concierge.py`: 「26 歳、リモートワーク、子育て予定」固定 prompt で TOP5 候補返答を表示

## 設計方針

### 「既存資産再利用」 + 「親子階層」 アプローチ

```
┌──────────────────────────────────────────────────────┐
│ 🟣 Concierge Agent (NEW, ADK 親 Agent)               │
│   tools=[                                              │
│     # 新規 BQ tools                                    │
│     search_municipalities,                             │
│     compare_municipalities,                            │
│     fetch_city_dashboard,                              │
│     fetch_city_speeches,                               │
│     # 既存 ADK sub-agents (Plan C で実装済)            │
│     ADKTranslatorAgent.as_tool(),  ← 子 Agent          │
│     ADKRelevanceAgent.as_tool(),   ← 子 Agent          │
│   ]                                                    │
└──────────────────────────────────────────────────────┘
                       │ uses
                       ▼
┌──────────────────────────────────────────────────────┐
│ 既存 logic (再利用)                                    │
│   _fetch_municipality_stats() (apps/api/main.py:601)  │
│   _generate_neutral_observation() (main.py:950)       │
│   BQ scored_speeches_latest / municipality_stats      │
└──────────────────────────────────────────────────────┘
```

### 採用しない選択肢
- ❌ **Concierge から全ロジックを書き直し**: 既存 endpoint と logic 重複、保守地獄
- ❌ **conversation memory 内蔵**: 状態管理は L+LL (RAG Engine) で別タスク化、E はステートレスから始める
- ❌ **streaming response**: SSE 実装コスト大、最初は polling/synchronous で MVP

### ファイル配置

```
agents/concierge/
├── __init__.py
├── main.py                  ← ConciergeAgent (ADK Agent class)、system instruction 適用
├── adk_agent.py             ← ADKConciergeAgent wrapper (Plan C パターン)
├── tools.py                 ← 4 つの新規 BQ tool 関数
├── schema.py                ← ConciergeRequest / ConciergeResponse / ToolCallLog
├── prompts/
│   ├── __init__.py
│   └── system.py            ← Concierge の system prompt
└── tests/
    ├── __init__.py
    ├── test_tools.py        ← 各 tool の unit test (BQ mock)
    ├── test_concierge.py    ← Agent core logic test
    └── test_adk_agent.py    ← ADK wrapper test

apps/api/main.py             ← POST /v1/concierge endpoint 追加
apps/web/src/app/concierge/
└── page.tsx                 ← chat-style UI (新規)

agents/demo_concierge.py     ← 「26 歳子育て予定」固定 prompt の demo (mock + live)
```

## Tool 詳細設計

### Tool 1: `search_municipalities`
```python
def search_municipalities(
    age_group: str,          # "18-24"〜"50+"
    interests: list[str],     # ["住居", "子育て"]
    constraints: dict | None = None,  # 例: {"max_avg_rent_man": 10, "min_childcare_count": 50}
    limit: int = 5,
) -> list[MunicipalityCandidate]:
    """BQ municipality_stats から条件絞り込み + relevance スコア重み付けで TOP N 自治体を返す"""
```
入力: ペルソナ年代 + 関心軸 + 制約 (家賃上限、保育園数下限等)
出力: 5 自治体の名前 + 主要統計サマリ + match_score (0-100)

### Tool 2: `compare_municipalities`
```python
def compare_municipalities(
    municipality_codes: list[str],   # 2-3 件
    interest: str,                    # "子育て" 等
) -> ComparisonTable:
    """既存 _generate_neutral_observation を流用、Gemini 中立観察も含む"""
```
内部で `apps/api/main.py` の `/v1/compare` ロジックを呼ぶ (関数化が必要)

### Tool 3: `fetch_city_dashboard`
```python
def fetch_city_dashboard(
    municipality_code: str,
    user_id: str,    # ペルソナ ID
    limit: int = 10,
) -> CityDashboard:
    """既存 get_city_dashboard 流用、街の関心軸別カウント + 上位議題"""
```
内部で `/v1/cities/{code}` ロジックを呼ぶ (同上)

### Tool 4: `fetch_city_speeches`
```python
def fetch_city_speeches(
    municipality_code: str,
    interest: str | None = None,
    limit: int = 5,
) -> list[ScoredSpeechSummary]:
    """BQ scored_speeches_latest から自治体 + interest で絞り込み"""
```
BQ 直接 query (新規)

### Sub-agent tools (Plan C 流用)

```python
# 議題内容を翻訳して欲しい場合 (Concierge が裁量で呼ぶ)
ADKTranslatorAgent(project_id="citify-dev").as_tool()
# ペルソナと議題の関連性を測りたい場合
ADKRelevanceAgent(project_id="citify-dev").as_tool()
```

## システムプロンプト方針

```
あなたは Citify の街診断コンシェルジュです。
ユーザーは「自分に合う街」を探しています。
以下の手順で対話してください:

1. ユーザーの自己紹介を聞き出す (年代 / 職業 / 家族構成 / 関心軸)
2. `search_municipalities` で TOP5 候補を取得
3. 候補について `fetch_city_dashboard` で詳細情報を取り、トレードオフを提示
4. 必要に応じて `compare_municipalities` で 2-3 自治体を比較
5. 関連議題を `fetch_city_speeches` で取得、ユーザーに関連する話題を提示

倫理制約 (PROJECT.md §5):
- 政治家固有名詞・政党推奨はしない
- 「処方」「投票推奨」等の禁止語は出力しない
- 移住補助等の制度紹介は具体的金額のみ、政治的判断はしない
- 中立的・客観的なトーンを保つ
```

## 作業ステップ

### Phase 0: 🔴 Critical Pre-flight — Dockerfile 修正 (~1.5h)

**Plan C のリスク評価 #8 は Plan E では逆転する**: `apps/api/Dockerfile` は現状 `agents/` を COPY せず、`google-adk` も install しない。Concierge を main.py に書いた瞬間に Cloud Run image が **runtime import エラーで API 全体停止** する致命的問題。Phase 1 着手前に必ず修正。

1. [ ] `apps/api/Dockerfile` 修正:
   - Build context を repo root に変更 (`docker build -f apps/api/Dockerfile .`)
   - `uv pip install` に `google-adk>=2.1,<3.0` 追加
   - runtime stage に `COPY --chown=citify:citify agents ./agents` 追加
   - runtime stage に `COPY --chown=citify:citify pkg ./pkg` も確認 (`pkg.pubsub` 等が agents から import される)
2. [ ] ローカルで `docker build -t citify-api:plan-e -f apps/api/Dockerfile .` 実行確認
3. [ ] `docker run --rm citify-api:plan-e python -c "from agents.translator.adk_agent import ADKTranslatorAgent; print('OK')"` で import smoke test
4. [ ] `cloudbuild.yaml` / `cloudbuild-api.yaml` (もしあれば) の build context も修正
5. [ ] **既存 API endpoint の regression check** (ローカル uvicorn で /v1/feed 等を curl で確認)

### Phase 1: スケルトン + tools.py (~5h)
6. [ ] `agents/concierge/` ディレクトリ + `__init__.py` 作成
7. [ ] `agents/concierge/schema.py`: `ConciergeRequest` / `ConciergeResponse` / `ToolCallLog` / `MunicipalityCandidate` 等
   - `MunicipalityCandidate.match_score` の計算定義: `1 - L2(normalized(stats), normalized(constraint)) / sqrt(N)` で 0-100 に正規化、`interests` 重みは関心軸 hit 数 × 5 で加点
8. [ ] `agents/concierge/tools.py`: 4 tool 関数
9. [ ] `apps/api/_municipality_helpers.py` (新規) に `_fetch_municipality_stats` / `_generate_neutral_observation` を切り出し、main.py と tools.py の両方が import
10. [ ] `agents/_shared/forbidden.py` (新規) に `FORBIDDEN_PATTERNS` を集約、translator / relevance / concierge の 3 agent から import
11. [ ] `agents/concierge/tests/test_tools.py`: 各 tool の unit test (BQ mock)
12. [ ] ruff format/check + pytest pass

### Phase 2: Concierge ADK Agent (~5h)
13. [ ] `agents/concierge/prompts/system.py`: system instruction (Plan C の translator/relevance system prompt と一貫した倫理ガード)
14. [ ] `agents/concierge/main.py`: `ConciergeAgent` class (LLM call wrapper、post-validation で `agents._shared.forbidden.FORBIDDEN_PATTERNS` を使用)
15. [ ] `agents/concierge/adk_agent.py`: `ADKConciergeAgent` (Plan C パターン)
   - **tools + sub_agents のハイブリッド構成**: `tools=[search_municipalities, ...]` + `sub_agents=[ADKTranslatorAgent().as_agent(), ADKRelevanceAgent().as_agent()]`
   - これでハッカソン審査員 demo 動画で「Agent が Agent を呼ぶ」絵が明示的に出る
16. [ ] **ADK Runner smoke test**: sub_agents 構成で 1 回だけ実行確認 (LLM mock)、ADK ハンドオフ規約との相性検証
17. [ ] `agents/concierge/tests/test_concierge.py` + `test_adk_agent.py`
18. [ ] ruff + pytest pass

### Phase 3: FastAPI endpoint (~3h)
19. [ ] (Phase 1 #9 で既に切り出し済) `apps/api/_municipality_helpers.py` を main.py から import するよう refactor
20. [ ] `POST /v1/concierge` endpoint 追加 (request: 自然言語 + persona、response: agent reply + tool_calls 履歴)
21. [ ] endpoint 用 integration test
22. [ ] ローカル `uvicorn` で smoke test (curl POST で確認)
23. [ ] 既存 endpoint regression check (`/v1/feed`, `/v1/cities`, `/v1/compare` を curl で確認、main.py のリファクタで壊れていないこと)

### Phase 4: Frontend chat UI (~9h、見直し)
24. [ ] `apps/web/src/lib/api/concierge.ts`: TS client + Zod schema (既存 cities/compare と同じ pattern)
25. [ ] `apps/web/src/app/concierge/page.tsx`: chat-style UI MVP (React Hook で履歴 array、入力フォーム + agent reply 表示)
26. [ ] **tool_calls 履歴の折りたたみ UI** (審査員向け演出): 各 reply の下に「Agent が呼んだ tool」リストを `<details>` で表示
27. [ ] エラーハンドリング (タイムアウト、API エラー、空応答)
28. [ ] 「新しい相談を始める」ボタン (single-turn UX を明示、L+LL 実装まで session 切替で代替)
29. [ ] `apps/web` を `pnpm dev` で起動、Chrome で動作確認 + screenshot 取得

### Phase 5: 統合 + demo (~3h)
30. [ ] `agents/demo_concierge.py`: **3 persona fixture** で TOP5 自治体を返答する demo
   - persona 1: 「26 歳、リモートワーク、子育て予定」 (無難なベースライン、test 用)
   - persona 2: 「介護で実家に戻る 34 歳、東京の家賃が苦しい」 (痛みのある persona、審査員 demo 動画 main)
   - persona 3: 「待機児童 2 年待ちで詰んだ 30 歳ワーママ」 (子育てペルソナで具体課題、E の最強訴求力)
31. [ ] mock mode + live mode 両方サポート (Plan C の demo_adk_chain と同じパターン)
32. [ ] 全テスト一括実行 (98 + 新規 ~30 = ~128 tests) で pass
33. [ ] **ハッカソンデモ動画用の screenshot 取得** (Frontend UI で persona 2 の応答 + tool_calls 履歴展開)

### Phase 6: ドキュメント + commit (~1.5h)
34. [ ] `docs/ARCHITECTURE.md` §4.x に Concierge Agent の階層図追記 (ADK 親子関係を強調、tools + sub_agents 構成を明示)
35. [ ] `docs/AGENT_PROMPTS.md` に Concierge セクション追加
36. [ ] `docs/FEATURES.md` に E (Migration Concierge) を Must で追加
37. [ ] **5 commit 分割案** を user に提示 → user 手動 commit + push (Critical Dockerfile 修正を独立 commit に切る):
    - `fix(plan-e): Dockerfile に agents/ + google-adk 追加 (Cloud Run deploy 対応)`
    - `refactor(plan-e): _municipality_helpers.py + _shared/forbidden.py に共通 logic 抽出`
    - `feat(plan-e): Concierge ADK Agent (tools + agent core)`
    - `feat(plan-e): Concierge API endpoint + Frontend chat UI`
    - `docs(plan-e): Concierge ドキュメント更新 + demo`

## リスク・懸念点

| # | リスク | 緩和策 |
|---|---|---|
| 1 | LLM が `search_municipalities` で曖昧な絞り込み条件を出す | system prompt で「絞り込み条件は必ず数値化」と明示、test fixture で確認 |
| 2 | Sub-agent (Translator/Relevance) を呼びすぎて遅延 / コスト爆発 | Concierge prompt で「ユーザー説明には sub-agent 必須でなければ呼ばない」と制約。max_remote_calls=10 (ADK default) で gating |
| 3 | BQ query が遅い (municipality_stats フル scan) | Phase F v4 の 1,917 自治体は全てメモリに乗る (350 KB)、初回読み込み後 cache |
| 4 | 倫理制約 (政治家名/政党推奨) を Concierge が破る | post-validation を Translator と同じ FORBIDDEN_PATTERNS で実装、違反時 retry |
| 5 | Frontend で agent streaming が必要に見える | MVP は polling、L+LL 実装時に streaming 追加検討 |
| 6 | 🔴 **Cloud Run deploy で API 全体停止** (Critical): 現状 `apps/api/Dockerfile` は `agents/` を COPY せず google-adk も install しない | **Phase 0 で Dockerfile 修正必須**: build context を repo root へ、`COPY agents` 追加、`uv pip install google-adk` 追加。ローカル `docker build` で smoke test 必須 |
| 7 | conversation memory なしで UX 弱い | L+LL (次タスク) で persistence 追加するため許容、E は単発相談として明示。Frontend に「新しい相談を始める」ボタンで期待値コントロール |
| 8 | `_fetch_municipality_stats` のリファクタで既存 endpoint が壊れる | Phase 1 #9 で `_municipality_helpers.py` に切り出し、Phase 3 #23 で既存 endpoint regression check |
| 9 | 倫理制約の二重実装 (translator/relevance/concierge) | Phase 1 #10 で `agents/_shared/forbidden.py` に集約、3 agent から import |
| 10 | ADK の sub_agents ハンドオフ規約と相性 | Phase 2 #16 で Runner smoke test で早期検証、トラブル時は tools=[...] only にフォールバック |

## 工数見積もり

| Phase | 想定時間 |
|---|---|
| Phase 0 (🔴 Critical Dockerfile 修正) | 1.5 時間 |
| Phase 1 (tools.py + helpers + shared forbidden) | 5 時間 |
| Phase 2 (ADK Agent core + sub_agents smoke test) | 5 時間 |
| Phase 3 (API endpoint + regression) | 3 時間 |
| Phase 4 (Frontend chat UI、見直し +2h) | 9 時間 |
| Phase 5 (統合 + 3 persona demo) | 3 時間 |
| Phase 6 (ドキュメント + 5 commits) | 1.5 時間 |
| **合計** | **28 時間 = 4 営業日** |

ミニプラン 3-5 日想定の上限近く (Critical 修正 + Frontend 工数見直し反映)。

## 後続タスクへのインターフェース

E 完了後、L+LL (会話履歴 + Story Recall) は以下のように Concierge に統合できる:

```python
# agents/concierge/main.py (L+LL 追加後)
class ConciergeAgent(Agent):
    def __init__(self):
        super().__init__(
            name="concierge",
            tools=[
                search_municipalities,
                ADKTranslatorAgent().as_tool(),
                # L+LL で追加される tools
                load_conversation_history,    # ← L
                recall_past_interests,        # ← LL
            ],
        )
```

これで「**3 ヶ月前の会話の続きから始められる Concierge**」が完成 (デモの強力武器)。

## レビュー依頼観点 (subagent 用)

1. **既存 logic 再利用の妥当性**: `_fetch_municipality_stats` / `_generate_neutral_observation` を tool に分離する設計は妥当か。既存 endpoint との二重保守にならないか
2. **親子 Agent 階層の必然性**: Concierge tools=[..., ADKTranslator.as_tool(), ...] という構成が ADK ベストプラクティスに沿っているか。代わりに Sub-Agent (SubAgentReference) を使うべきか?
3. **conversation memory なしの MVP 判断**: 後続 L+LL で追加する設計判断は妥当か、ユーザビリティが致命的に弱くないか
4. **Frontend Phase の工数 7h**: chat UI 実装が 1 日でできるか過小評価ないか
5. **倫理制約の実装位置**: Concierge / Translator / Relevance のどこで FORBIDDEN_PATTERNS チェックすべきか
6. **demo スクリプトの内容**: 「26歳子育て予定」は審査員向け demo として強力か。もっと具体的なシナリオ案あるか
7. **CI / Dockerfile 影響**: Concierge エンドポイント追加で `apps/api/Dockerfile` の image rebuild が必要、CI が落ちないか
