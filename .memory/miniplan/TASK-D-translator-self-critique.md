# ミニプラン: Plan D Translator Self-critique Loop

## 概要

- **タスク ID**: TASK-D
- **目的**: TranslatorAgent に Critic による Self-critique ループを追加し、翻訳品質 (Faithfulness / Simplicity / Tone / Ethics) を多軸スコアリング + 低スコア時の自動再生成で底上げする
- **完了条件**:
  - `translate_with_critique()` メソッドが TranslatorAgent に追加され、(draft → critic → revise) の 1-round loop が動作する
  - Critic は 4 軸 (faithfulness/simplicity/tone/ethics) 各 0-100 スコア + overall_score + feedback テキストを構造化出力で返す
  - `overall_score < threshold (default 70)` の場合は 1 度だけ revise を実行 (latency / cost を抑える)
  - 既存 `translate()` は不変 (backward compat)
  - `MAX_RETRIES=3` の倫理リトライ機構は維持 (Critic は追加層、ethics 二重チェック)
  - **7+ unit test**:
    - critic mock + threshold 判定 (score>=70 path)
    - revise あり path (score<70 → 1 revise → return)
    - 倫理 violation 強制 revise (ethics<60 強制 trigger、Reviewer High #1 反映)
    - empty draft への critique skip (Reviewer High #2 反映)
    - threshold 境界値 (69 / 70 / 71、Reviewer Medium 反映)
    - Pydantic ValidationError (scores が 0-100 範囲外、Reviewer Medium 反映)
    - revise 後も threshold 未達でも return (cost cap)
  - **既存 18 translator tests + 7 worker tests 全 pass**
  - `docs/AGENT_PROMPTS.md` に §0.7 Self-Critique Loop section
  - `docs/FEATURES.md` に A-16 エントリ
- **想定工数**: 1 日 (6h)

---

## 設計

### 動作フロー

```
[translate_with_critique]
  ↓
  1. translate() で draft 生成 (既存 flow、倫理リトライ 3 回まで含む)
  ↓
  2. critic LLM call で 4 軸スコア + feedback 取得
  ↓
  3a. overall_score >= threshold → return draft + critique (revision_count=0)
  3b. overall_score < threshold:
       ↓
       4. critic feedback を含めて再 prompt → revised draft 生成
       ↓
       5. revised draft で再 critique 評価
       ↓
       6. return revised + critique (revision_count=1)
       (revised が threshold 未達でも return、cost cap)
```

### Critic 評価軸 (rubric)

| 軸 | 0-100 範囲の意味 | 低スコア時の修正例 |
|---|---|---|
| **faithfulness** (原典忠実度) | 100: 原典の事実関係を正確に反映 / 0: 事実誤認、捏造、過度な単純化 | 原典に明示されていない数値・固有名詞・主張を削除 |
| **simplicity** (平易さ) | 100: 18-24 歳が辞書なしで理解可能 / 0: 専門用語・敬語・冗長表現が残存 | 役所言葉を口語に書き換え |
| **tone** (トーン適合) | 100: age_group の TONE_GUIDANCE に準拠 / 0: 不適合 (堅すぎ/砕けすぎ) | age_group=18-24 に対し formal を casual に |
| **ethics** (倫理) | 100: 政治家名/政党/賛否なし / 0: 固有名詞/賛否表明あり (既存 FORBIDDEN_PATTERNS の二重チェック) | 固有名詞除去、賛否を中立表現に |

### overall_score 算出 (Reviewer High #1 反映)

```python
# 単純平均 (4 軸均等)
overall_score = round((faithfulness + simplicity + tone + ethics) / 4)

# ただし ethics は強制 revise トリガー (倫理は絶対遵守、平均で薄まらせない)
should_revise = (overall_score < threshold) or (ethics < 60)
```

- **理由**: ethics は 60 未満なら他軸が完璧でも倫理 violation のリスクが高い。
  既存 `_validate_ethics` (regex) はその後で post-validation し、合算 retry も別途動作する。

### empty draft への critique skip (Reviewer High #2 反映)

```python
draft = self.translate(input)
# translate() が 倫理 give-up や空入力で empty() を返した場合は critique skip
if draft.notes.startswith("empty_reason:"):
    return TranslatorWithCritique(
        translation=draft,
        critique=CritiqueResult(
            scores=CriticScores(faithfulness=0, simplicity=0, tone=0, ethics=0),
            overall_score=0,
            feedback="draft が empty のため critique skip",
            passed=False,
        ),
        revision_count=0,
        initial_score=0,
    )
```

### 新規 schema

`agents/translator/schema.py` に追加:

```python
class CriticScores(BaseModel):
    faithfulness: int = Field(ge=0, le=100, description="原典忠実度")
    simplicity: int = Field(ge=0, le=100, description="平易さ")
    tone: int = Field(ge=0, le=100, description="トーン適合")
    ethics: int = Field(ge=0, le=100, description="倫理")

class CritiqueResult(BaseModel):
    scores: CriticScores
    overall_score: int = Field(ge=0, le=100, description="4 軸平均")
    feedback: str = Field(max_length=500, description="改善提案 (revise 時 prompt に注入)")
    passed: bool = Field(description="threshold 以上ならTrue")

class TranslatorWithCritique(BaseModel):
    translation: TranslatorOutput
    critique: CritiqueResult
    revision_count: int = Field(default=0, ge=0, le=1)
    initial_score: int = Field(ge=0, le=100, description="revise 前 overall_score (改善幅 demo 用)")
```

### 新規メソッド (main.py)

```python
DEFAULT_CRITIQUE_THRESHOLD = 70

def translate_with_critique(
    self,
    input: TranslateInput,
    threshold: int = DEFAULT_CRITIQUE_THRESHOLD,
) -> TranslatorWithCritique:
    """Self-critique loop で品質スコア付き翻訳を返す (1 round revise)。"""

def _critique(
    self,
    client: _GenAIClientProto,
    draft: TranslatorOutput,
    input: TranslateInput,
) -> CritiqueResult: ...

def _revise(
    self,
    client: _GenAIClientProto,
    draft: TranslatorOutput,
    critique: CritiqueResult,
    input: TranslateInput,
) -> TranslatorOutput: ...
```

### 新規 prompt (prompts/critic.py)

```python
CRITIC_PROMPT_VERSION = "v1.0"

CRITIC_SYSTEM_PROMPT = """あなたは翻訳品質の評価者 (Critic) です。
若者向け翻訳結果を 4 軸 (faithfulness/simplicity/tone/ethics) で
各 0-100 スコアリングし、改善 feedback を返してください。
..."""
```

### Backward compat

- `translate()` は完全不変
- `translate_with_critique()` は **新規 method**、worker や ADK wrapper は触らない
- demo script (`agents/translator/__main__.py`) と Concierge / Frontend は当面不変

---

## 作業ステップ

1. [ ] **Step 1**: `agents/translator/schema.py` に `CriticScores` / `CritiqueResult` / `TranslatorWithCritique` 追加
2. [ ] **Step 2**: `agents/translator/prompts/critic.py` 新規作成 (CRITIC_SYSTEM_PROMPT + build_critic_user_prompt + build_revise_user_prompt)
3. [ ] **Step 3**: `agents/translator/main.py` に `_critique` / `_revise` / `translate_with_critique` メソッド追加
4. [ ] **Step 4**: `agents/translator/tests/test_critic.py` 新規作成 (5+ test)
5. [ ] **Step 5**: 既存 18 translator + 7 worker tests regression check
6. [ ] **Step 6**: `docs/AGENT_PROMPTS.md` §0.7 + `docs/FEATURES.md` A-16 追記
7. [ ] **Step 7**: 全 pytest 再走 → 全 pass 確認 → 推奨 commit 案を提示

---

## 成果物

- [ ] `agents/translator/schema.py` (3 class 追加)
- [ ] `agents/translator/prompts/critic.py` (新規)
- [ ] `agents/translator/main.py` (3 method 追加)
- [ ] `agents/translator/tests/test_critic.py` (新規、5+ test)
- [ ] `docs/AGENT_PROMPTS.md` (§0.7 追加)
- [ ] `docs/FEATURES.md` (A-16 追加)

## 推奨 commit 構成 (人間が手動)

```
1. feat(plan-d-phase1): Translator Critic schema + prompt
   - agents/translator/schema.py, prompts/critic.py

2. feat(plan-d-phase2): translate_with_critique loop + 5 unit tests
   - agents/translator/main.py, tests/test_critic.py

3. docs(plan-d): A-16 + AGENT_PROMPTS §0.7
   - docs/FEATURES.md, docs/AGENT_PROMPTS.md
```

## リスク・懸念点

| リスク | 対策 |
|---|---|
| Critic が低スコアを乱発し latency 2 倍化 | threshold=70 で運用、revise は 1 round で cap (cost / latency 上限) |
| Worker (Pub/Sub) が translate_with_critique を呼んで本番 cost 増 | 当 Plan では worker.py は触らない、optional method として exposing のみ |
| Critic の politics 観点が translator post-validation と二重 | 二重防御として許容 (Critic は LLM 判定、post-validation は regex、互いに補完) |
| Gemini API mock の Pydantic schema 整合 | 既存 TranslatorAgent test と同じ `parsed` mock パターン踏襲 |

---

## Out of Scope (Plan D では実装しない)

- worker.py / Pub/Sub flow への組み込み (production cost 増回避)
- ADK wrapper (adk_agent.py) に Self-critique loop を反映
- Critic を独立 ADK Agent として親 Translator の sub_agent に格下げ
- Frontend からの translate_with_critique 呼び出し (demo script 経由のみ)

→ これらは Phase 2 として将来 (Plan D-2) 検討。

---

## 受け入れ条件 (Definition of Done)

- [ ] `pytest agents/translator/` → 全 pass (既存 18 + 7 + 新規 5+)
- [ ] `translate()` の戻り値 binary equality 維持 (既存 test で証明)
- [ ] `translate_with_critique()` で初回 draft が threshold 以上ならそのまま return + revision_count=0
- [ ] `translate_with_critique()` で初回 draft が threshold 未満なら 1 度 revise + revision_count=1
- [ ] CritiqueResult.scores が 0-100 範囲内 (Pydantic 制約)
- [ ] docs/AGENT_PROMPTS.md と docs/FEATURES.md 更新
- [ ] 推奨 commit message を提示 (実 commit/push は人間)
