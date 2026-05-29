# ミニプラン: C - ADK 化 (translator / relevance / distributor)

## 概要

- **タスクID**: TASK-C (バランス版 #1 / 基盤)
- **目的**:
  既存 3 agent (`agents/translator`, `agents/relevance`, `agents/distributor`) を **`google-adk` の Agent 抽象** でラップし、ハッカソン審査基準①「マルチエージェント必然性」+ ADK 使用要件を満たす。後続の E (Concierge) が ADK Tool として subcall できる土台を整える。
- **完了条件**:
  1. `apps/api/pyproject.toml` に `google-adk>=2.1,<3.0` を追加 + `pip install` 成功 (実在版 2.1.0 実測確認済)
  2. 各 agent ディレクトリに `adk_agent.py` 新規作成 (既存 `main.py` の core logic は変更しない)
  3. ADK 経由で既存 logic が呼び出せる (`adk_translator.run(...)` → 既存 `TranslatorAgent.translate()` 経由で Gemini 呼び出し)
  4. 既存 **68 tests が全て pass** (後方互換)
  5. 新規 unit test `test_adk_agent.py` × 3 ファイル (FakeLLM mock パターン + ADK Tool schema 検証 + `as_tool()` invoke 確認)
  6. ruff format / check pass
  7. **串刺し demo スクリプト** `scripts/demo_adk_chain.py` 作成: 1 speech を `translator → relevance → distributor` と 3 段 ADK Runner 経由で実行できる (C 単体でも "agent orchestration" を可視化)

## 設計方針: 「薄い wrapper」 アプローチ (low-risk)

```
agents/translator/
├── main.py             ← 既存 TranslatorAgent (内部 LLM logic、変更なし)
├── adk_agent.py        ← 新規: google.adk.Agent サブクラス
├── worker.py           ← 既存 (Pub/Sub 部分、変更なし)
├── schema.py           ← 既存 (変更なし)
├── prompts/system.py   ← 既存 (変更なし)
└── tests/
    ├── test_translator.py  ← 既存 (変更なし)
    ├── test_worker.py      ← 既存 (変更なし)
    └── test_adk_agent.py   ← 新規 (10-15 tests / agent)
```

### 採用しない選択肢
- ❌ **完全置換** (既存 TranslatorAgent を ADK に書き直す): 既存 68 tests が破壊される、リスク大、効果薄
- ❌ **worker.py を ADK の Runtime で置換**: Pub/Sub 統合パターンが変わる、Cloud Run Job 再 deploy 影響大

### Tool 定義の方針
各 agent の **public API method を 1 つの Tool として公開**:
- `translator_agent.translate_speech(input: TranslateInput) -> TranslatorOutput`
- `relevance_agent.score_speech(input: RelevanceInput, persona_id: str) -> RelevanceOutput`
- `distributor_agent.distribute(scored: ScoredSpeech) -> FeedSnapshot`

これで E (Concierge) から `translator_agent` を **ADK Tool として import** して使える。

## 作業ステップ (時系列)

### Phase 1: 依存追加 + 環境整備 (~30 分)
1. [x] `pip index versions google-adk` で実在版確認 → **2.1.0 GA 確認済 (2026-05-29 時点)**
2. [x] CI workflow / Dockerfile build context 影響調査 → **CI Lint は ruff のみ (影響なし)、workers Dockerfile は repo root context (新ファイル含まれる)、api Dockerfile は agents/ 不要**
3. [ ] `apps/api/pyproject.toml` の dependencies に `"google-adk>=2.1,<3.0"` 追加
4. [ ] `apps/api/.venv/bin/pip install -e ".[dev]"` または `pip install google-adk` 実行
5. [ ] `apps/api/.venv/bin/python -c "from google.adk import Agent; print(Agent)"` で import 成功確認
6. [ ] 既存 68 tests を実行 → 全て pass (regression なし) を確認
7. [ ] ADK 基本 API 学習 (~30 分): Agent / @tool / Runner の 3 つの最小 example を手元で動かす

### Phase 2: Translator の ADK 化 (~4-5 時間、初回 ADK 学習コスト込)
8. [ ] `agents/translator/adk_agent.py` 新規作成
   - `google.adk.Agent` サブクラス `ADKTranslatorAgent`
   - 内部で既存 `TranslatorAgent` を保持
   - `@tool` 関数 `translate_speech(input: TranslateInput) -> TranslatorOutput`
   - `.as_tool()` メソッドで他 agent から呼べる Tool 化
9. [ ] `agents/translator/tests/test_adk_agent.py` 作成
   - **既存パターン (4 軸)**: 入力検証 / 出力検証 / 例外伝播 / メタデータ (prompt_version)
   - **ADK 固有 (2 軸追加)**:
     - ADK Tool schema が `TranslateInput` の Pydantic schema と一致する
     - `as_tool()` で取得した Tool が ADK Runner から invoke 可能
10. [ ] pytest pass 確認 + ruff format/check

### Phase 3: Relevance の ADK 化 (~2 時間、Phase 2 で学習済の前提)
11. [ ] `agents/relevance/adk_agent.py` 新規作成 (同様パターン、persona context 注入が追加で必要)
12. [ ] `agents/relevance/tests/test_adk_agent.py` 作成 (Phase 2 と同じ 6 軸 + persona variation テスト)
13. [ ] pytest pass + ruff

### Phase 4: Distributor の ADK 化 (~2 時間)
14. [ ] `agents/distributor/adk_agent.py` 新規作成 (LLM 呼ばないので簡易)
15. [ ] `agents/distributor/tests/test_adk_agent.py` 作成
16. [ ] pytest pass + ruff

### Phase 5: 統合確認 (~1.5 時間)
17. [ ] **串刺し demo スクリプト** `scripts/demo_adk_chain.py` 作成
    - 1 speech (固定 fixture) を Translator ADK → Relevance ADK → Distributor ADK と 3 段で実行
    - ADK Runner 経由で chain を可視化、stdout に各 stage の出力を JSON で表示
    - C 完了の **デモ用 artifact**: ハッカソン審査員に「agent orchestration が動いている」絵を見せられる
18. [ ] 既存 worker.py の **統合テスト** `test_worker.py` を改めて実行 (FakePubSub で 1 envelope 通すテスト存在の確認 + pass)
19. [ ] 全テスト一括実行 (68 + 新規 ~30 = ~100 tests) で pass

### Phase 6: ドキュメント + commit (~45 分)
20. [ ] `docs/AGENT_PROMPTS.md` に「ADK 化済み、Tool 呼び出し可能」記載追加
21. [ ] `docs/ARCHITECTURE.md` の agent 構成図に ADK 階層 (ADKTranslatorAgent ↔ TranslatorAgent core) 追記
22. [ ] `CLAUDE.md` の technical stack 表に ADK 追記
23. [ ] `AGENTS.md` (他コーディングエージェント用) の技術スタックにも ADK 追記
24. [ ] **4 commit 分割案** を user に提示 → user 手動 commit + push:
    - `feat(plan-c): ADK 2.1 依存追加 + translator ADK wrapper`
    - `feat(plan-c): relevance ADK wrapper`
    - `feat(plan-c): distributor ADK wrapper`
    - `docs(plan-c): ADK 化に伴う技術スタック更新 + 串刺し demo`

## 成果物

- [ ] `agents/translator/adk_agent.py` (新規)
- [ ] `agents/translator/tests/test_adk_agent.py` (新規)
- [ ] `agents/relevance/adk_agent.py` (新規)
- [ ] `agents/relevance/tests/test_adk_agent.py` (新規)
- [ ] `agents/distributor/adk_agent.py` (新規)
- [ ] `agents/distributor/tests/test_adk_agent.py` (新規)
- [ ] `scripts/demo_adk_chain.py` (新規、串刺し demo for ハッカソン審査員可視化)
- [ ] `apps/api/pyproject.toml` (修正、`google-adk>=2.1,<3.0` 追加)
- [ ] `docs/AGENT_PROMPTS.md` (更新)
- [ ] `docs/ARCHITECTURE.md` (更新、ADK 階層図追記)
- [ ] `CLAUDE.md` (更新、stack 表に ADK 追記)
- [ ] `AGENTS.md` (更新、他コーディングエージェント向け技術スタックに ADK 追記)

## リスク・懸念点

| # | リスク | 緩和策 |
|---|---|---|
| 1 | ADK 2.1 (新 GA、API 安定性不明) | バージョン pin (`google-adk>=2.1,<3.0`)、Phase 1 #7 で基本 API 学習で挙動把握 |
| 2 | ADK の Tool decorator パターンが既存の Pydantic response_schema と衝突 | wrapper では Pydantic 入出力をそのまま通す、ADK 側の構造化出力機能は使わない |
| 3 | Cloud Run Job の image 再 build が必要 (workers が ADK 経由になる場合) | **本タスクでは worker.py を変更しない** ので image rebuild 不要 |
| 4 | テストで FakeLLM が必要だが ADK の test util が unstable | unittest.mock.MagicMock で `TranslatorAgent` を mock するパターン (既存 test_translator.py と同じ) |
| 5 | ADK 化 + 既存 SDK 共存で import 衝突 | ADK は内部で `google.genai` を使うので共存 OK (調査で確認済) |
| 6 | `google-adk` の依存追加で Cloud Run Job image サイズ増 | 増分は ~10MB 想定、許容範囲 |
| 7 | CI Lint workflow が新依存で fail | **影響なし確認済** (`.github/workflows/lint.yml` は `pip install ruff` のみ、project deps を install しない) |
| 8 | Dockerfile build context に新 ADK 関連ファイルが含まれない | **影響なし確認済** (apps/workers/Dockerfile は repo root context、agents/*/adk_agent.py 含まれる; apps/api/Dockerfile は agents/ 不要) |

## 工数見積もり

| Phase | 想定時間 |
|---|---|
| Phase 1 (依存追加 + 基本 API 学習) | 1 時間 |
| Phase 2 (Translator + 初回 ADK 学習) | 4-5 時間 |
| Phase 3 (Relevance) | 2 時間 |
| Phase 4 (Distributor) | 2 時間 |
| Phase 5 (統合 + 串刺し demo) | 1.5 時間 |
| Phase 6 (ドキュメント + commit) | 45 分 |
| **合計** | **11-12 時間 = 2 営業日強** |

予定 2-3 日に収まる。

## 後続タスクへのインターフェース

C 完了後、E (Concierge) は以下のように ADK Tool を使える:

```python
# agents/concierge/main.py (E で実装予定)
from agents.translator.adk_agent import ADKTranslatorAgent
from agents.relevance.adk_agent import ADKRelevanceAgent

class ConciergeAgent(Agent):
    def __init__(self):
        super().__init__(
            name="concierge",
            tools=[
                ADKTranslatorAgent().as_tool(),  # subcall 可能
                ADKRelevanceAgent().as_tool(),
                # + BQ tools, Reinfolib tools, etc.
            ],
        )
```

これで「親 Agent (Concierge) が子 Agent (Translator/Relevance) を subcall する階層」が **マルチエージェント必然性** として明示できる。

## レビュー依頼観点 (subagent 用)

1. **既存 68 tests への影響範囲**: 「薄い wrapper」 で本当に 0 影響か
2. **ADK Tool 定義の必然性**: 単に既存 method を呼ぶだけで Tool 化する意味があるか (E への伏線として十分か)
3. **テスト戦略**: FakeLLM mock パターンは適切か
4. **commit 単位**: 1 commit でまとめるか / agent 単位 (3 commit) か
5. **ドキュメント漏れ**: docs/AGENT_PROMPTS.md 以外に更新必要なドキュメントはあるか
