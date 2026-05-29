# ミニプラン: Plan N 議論タイムライン Agent

## 概要

- **タスク ID**: TASK-N
- **目的**: ユーザーが選んだテーマ (interest 軸 + 自治体 or 全国 + 期間) について、議論変遷を時系列イベント 5-10 件 + 全体ナラティブとして可視化する。ハッカソン審査基準②「ストーリー性」を強化、Citify のキラー UX (議題が「点」ではなく「流れ」で見える)。
- **完了条件**:
  - 新規 `TimelineAgent` (Plan X の HeatmapAdvisor と一貫した独立 Agent 構造) が candidate speeches を受けて TimelineNarrative を返す
  - `GET /v1/timeline?interest=...&municipality_code=...&days=90` endpoint が実装され、BQ で候補 speeches 取得 → LLM ナラティブ生成 → response 返却
  - Frontend `/timeline` page が縦スクロール timeline UI、各イベントクリックで議題詳細 (`/feed/[speech_id]`) へ遷移
  - LLM 失敗時は raw 上位 5 speeches を「ナラティブなし fallback」として返す graceful degrade
  - 倫理ガード: TimelineNarrative の overall_summary / event.headline / event.detail に対し FORBIDDEN_PATTERNS post-validation、leak 検出時は安全な fallback
  - 10+ unit/integration test、既存 234 件と合わせて全 pass
  - docs/AGENT_PROMPTS.md §0.9 + docs/FEATURES.md A-18 追加
- **想定工数**: 3 日 = 18h

---

## 設計

### Agent 構成

```
TimelineAgent (Plan N 新規、HeatmapAdvisor と同じ独立 Agent パターン)
  ├─ 入力: TimelineRequest (theme_interest, municipality_code | None, days, persona)
  └─ 出力: TimelineNarrative
        ├─ theme_label: str (確定 theme 名 e.g. "保育園・待機児童問題")
        ├─ period_start: date / period_end: date
        ├─ overall_summary: str (200 字、議論の流れ全体)
        ├─ events: list[TimelineEvent] (5-10 件)
        │     ├─ date / municipality_code / municipality_name
        │     ├─ headline (40 字、キャッチーな見出し)
        │     ├─ detail (80 字、具体的な議論内容)
        │     ├─ source_speech_id (クリックで /feed/{id} 遷移)
        │     └─ importance (0-100、UI で大小強調)
        └─ source: "llm" | "rule_based" (fallback 判別)
```

### 動作フロー

```
[GET /v1/timeline]
  ↓
  1. BQ scored_speeches_latest から候補 speeches 取得 (上限 30 件):
       WHERE user_id=@user_id
         AND @interest IN UNNEST(matched_interests)
         AND (municipality_code = @muni OR @muni IS NULL)
         AND meeting_date BETWEEN @start AND @end
         AND municipality_code != '00000'  -- 国会除外オプション
       ORDER BY meeting_date ASC, relevance_score DESC
       LIMIT 30
  ↓
  2. 候補が < 3 件 → 「データ不足」エラー / 空 timeline 返却
  ↓
  3. TimelineAgent.narrate(candidates, request) で LLM call:
       - System prompt: 議論変遷を 5-10 イベントで要約
       - Chain-of-Thought (内部): 時系列ソート → 重複圧縮 → イベント抽出 → headline 生成
       - Output: TimelineNarrative (response_schema 強制)
  ↓
  4. 倫理 post-validation (overall_summary / 全 event.headline / 全 event.detail):
       - FORBIDDEN_PATTERNS regex
       - speaker_position 以外の固有名詞 leak
       → 違反検出時は fallback (raw 上位 5 speeches を date 順で並べた timeline、headline=title、detail=summary[0])
  ↓
  5. response: TimelineResponse(narrative=...)
```

### Schema 定義

```python
# agents/timeline/schema.py

class TimelineEvent(BaseModel):
    date: date
    municipality_code: str
    municipality_name: str
    headline: str = Field(max_length=40)
    detail: str = Field(max_length=80)
    source_speech_id: str
    importance: int = Field(ge=0, le=100, default=50)

class TimelineNarrative(BaseModel):
    theme_label: str = Field(max_length=40)
    period_start: date
    period_end: date
    overall_summary: str = Field(max_length=240)
    events: list[TimelineEvent] = Field(min_length=0, max_length=10)
    source: Literal["llm", "rule_based"] = "llm"

class TimelineRequest(BaseModel):
    user_id: str = "anon"
    theme_interest: Interest  # 10 軸のいずれか
    municipality_code: str | None = None  # None = 全国
    days: int = Field(default=90, ge=7, le=365)
```

### BQ query (集計行除外、interest UNNEST)

```sql
SELECT
  speech_id, title, summary, meeting_date,
  municipality_code, name_of_meeting, speaker_position,
  matched_interests, relevance_score
FROM `{table_fqn}`
WHERE user_id = @user_id
  AND meeting_date BETWEEN @start AND @end
  AND @interest IN UNNEST(matched_interests)
  AND (@muni IS NULL OR municipality_code = @muni)
  AND municipality_code != '00000'      -- 国会 (国会単体 timeline は別 Plan)
  AND municipality_code NOT LIKE '%000' -- 都道府県集計行を除外
ORDER BY meeting_date ASC, relevance_score DESC
LIMIT 30
```

→ BQ コスト: 1 query で ~30 行、scan 範囲は user_id × interest × 日付で絞られて軽量

### LLM (TimelineAgent) system prompt (Chain of Thought)

```
あなたは Citify の議論タイムライン編集者 (Timeline Editor) です。
与えられた議題候補 (時系列順) を分析し、若者向けに 5-10 個の重要イベントで議論変遷を物語化してください。

# Chain of Thought (内部思考)
1. 候補を時系列でグルーピング (重複・類似議題を圧縮)
2. 各グループから「最も重要な発言 / 転換点」を 5-10 個抽出
3. 各イベントに 40 字以内のキャッチーな headline + 80 字の detail を付与
4. 全体ナラティブ (overall_summary 200 字) で「議論はどこから始まり、どう発展し、今どこに居るか」を物語化

# 重要: 本 timeline は theme_interest 軸 (e.g. "住居") に絞った物語です
- candidates の matched_interests は複数軸を持つ場合あり (Reviewer Medium #5)
- theme_interest 軸に関連する話題のみを抽出し、他軸の話題は無視してください

# 出力 (TimelineNarrative schema 強制)
- theme_label / period_start / period_end / overall_summary / events[]

# 倫理ガード (絶対遵守、違反したら出力を破棄)
- 政治家・首長・議員の固有名詞は使わない (speaker_position まで使用可)
- 政党名・賛否表明は禁止
- 例 NG: "石破総理が提案" / "立憲民主党が反対"
- 例 OK: "総理大臣が提案" / "野党側が反対"
```

### LLM パラメータ (Reviewer Critical #2 反映)

```python
DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_TEMPERATURE = 0.3            # 物語化は多様性少し、再現性重視
DEFAULT_MAX_OUTPUT_TOKENS = 2048     # narrative (240) + events 10 × ~150 ≈ 1800 token
DEFAULT_THINKING_BUDGET = 512        # CoT (グルーピング + 重要度判定) 用に確保
```

**Token 見積もり** (Reviewer Critical #2):
- Input: candidates 30 件 × (title 40 + summary 1 行 60 + 自治体 + date) ≈ 3.6K token
  + system prompt + Chain-of-Thought instructions ≈ 1K = **入力 ~5K**
- Output: narrative 240 + events 10 × ~150 = ~1.7K → max_output_tokens=2048 で十分

### 倫理ガード強化 (Reviewer Critical #1 反映)

既存 `FORBIDDEN_PATTERNS` (forbidden.py) は処方/投票推奨/賛否表明のみで政治家名 regex なし。
Timeline ナラティブは「議論の流れ」を語る性質上、人名 leak リスクが Translator より高いため
**専用 post-validation `_contains_political_personal_name()` を追加**:

```python
# agents/timeline/main.py (新規 helper)
POLITICAL_PERSON_PATTERNS = [
    re.compile(r"[一-龥]{2,4}(議員|首相|総理|大臣|長官|知事|市長|町長|村長|区長)"),
    re.compile(r"[一-龥]{2,4}(氏|さん)"),  # 個人名末尾
    re.compile(r"(自民党|立憲民主党|公明党|国民民主党|共産党|維新の会|社民党|れいわ|参政党|N国|無所属)"),
]

def _contains_political_personal_name(text: str) -> str | None:
    for pattern in POLITICAL_PERSON_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group()
    return None
```

post-validation:
- overall_summary / 各 event.headline / event.detail に対し regex match
- match 検出 → leak をログ (ユーザー向け文には含めない、HeatmapAdvisor 同様) + raw fallback

**さらに**: candidate speeches の `speaker_position` だけを LLM に渡し、`speaker` (実名) は **BQ SELECT に含めない** (二重防御、Reviewer Critical #1 案 (b))

### source_speech_id 捏造防止 + 縮退ケース (Reviewer High #4 反映)

```python
# narrate() の post-process
candidate_ids = {s.speech_id for s in candidates}
valid_events = [e for e in narrative.events if e.source_speech_id in candidate_ids]

# 縮退ケース閾値:
# - valid_events が 0 件 → fallback (raw 上位 5 speeches を date 順)
# - valid_events が 1-2 件 → fallback (Reviewer 推奨: 「3 件未満なら timeline として弱い」)
# - valid_events が 3+ 件 → そのまま return
if len(valid_events) < 3:
    return self._rule_based_fallback(candidates, request, reason="too_few_valid_events")
```

### Frontend UI 動線差別化 (Reviewer High #3 反映)

speech 詳細 (`/feed/[speech_id]`) ページに **両 endpoint への動線を並列配置**:

```tsx
{/* 既存: 関連議題 (RAG semantic) */}
<RelatedSpeeches speechId={...} />
  ↳ "🔗 関連議題 (この発言と意味的に近いもの)"

{/* 新規: 議論タイムライン (この interest 全体の物語) */}
<TimelineLink interest={primaryInterest} municipalityCode={...}>
  🕰 議論の流れを見る ({interest} 軸、過去 90 日)
</TimelineLink>
```

UI コピー指針:
- `関連議題`: 「この発言の周辺、内容が似ている発言を 3 件」(point in space, semantic)
- `議論の流れ`: 「この interest 軸の議論変遷、5-10 個のマイルストーン」(time axis, narrative)

### Frontend 構成

```
apps/web/src/app/timeline/
├── page.tsx               # メインページ (interest + municipality 選択 + Timeline UI)
└── (内部 component)
    ├── TimelineList       # 縦スクロール event リスト
    ├── TimelineEventCard  # 1 event カード (date / headline / detail / 自治体 / source link)
    └── NarrativeBanner    # overall_summary を上部に banner 表示
apps/web/src/lib/api.ts     # fetchTimeline() 追加
```

### Frontend UX

- ホーム + フィードからナビリンク追加 (`🕰 議論タイムライン`)
- ペルソナ interests から initial focus_interest 選定
- 自治体は persona.municipality_codes 初期値 + 「全国」切替
- 期間: 30 / 90 / 365 日切替
- Event カード: 左 timeline dot + date、右 headline (大) + detail (小) + 自治体名 chip
- Event クリック → `/feed/{source_speech_id}` (既存 speech 詳細) へ遷移
- LLM fallback 時 (`source="rule_based"`) は banner を amber 系で「Agent 整理は失敗、生 data 表示」と表示

---

## 作業ステップ

### Phase 1 (6h): TimelineAgent + Backend API

1. [ ] **Step 1.1**: `agents/timeline/` ディレクトリ新規 (`__init__.py`, `schema.py`, `prompts/system.py`, `main.py`)
2. [ ] **Step 1.2**: `TimelineEvent` / `TimelineNarrative` / `TimelineRequest` Pydantic schema
3. [ ] **Step 1.3**: `TimelineAgent.narrate(candidates, request)` 実装 (Gemini Flash + Chain-of-Thought)
4. [ ] **Step 1.4**: 倫理 post-validation (FORBIDDEN_PATTERNS) + fallback (raw 上位 5)
5. [ ] **Step 1.5**: `agents/timeline/tests/test_timeline.py` (5+ test、fallback path 含む)
6. [ ] **Step 1.6**: `apps/api/main.py` に `GET /v1/timeline` endpoint 追加 + BQ candidate fetch
7. [ ] **Step 1.7**: `apps/api/tests/test_timeline_endpoint.py` (4+ test)

### Phase 2 (6-8h): Frontend /timeline page

8. [ ] **Step 2.1**: `apps/web/src/lib/api.ts` に `fetchTimeline()` + zod schema
9. [ ] **Step 2.2**: `apps/web/src/app/timeline/page.tsx` メインページ
10. [ ] **Step 2.3**: `TimelineList` + `TimelineEventCard` + `NarrativeBanner` component
11. [ ] **Step 2.4**: 議題詳細 (`/feed/[speech_id]`) と `cities/[code]` から timeline へのリンク追加
12. [ ] **Step 2.5**: `next build` smoke test

### Phase 3 (3h): nav + docs

13. [ ] **Step 3.1**: ホームに `🕰 議論タイムライン` リンク追加
14. [ ] **Step 3.2**: `docs/AGENT_PROMPTS.md` §0.9 TimelineAgent
15. [ ] **Step 3.3**: `docs/FEATURES.md` A-18 エントリ
16. [ ] **Step 3.4**: `ruff format/check` + 全 pytest 再走 → 全 pass

### Phase 4 (0.5h): 推奨 commit 提示

17. [ ] **Step 4.1**: 4 commit 構成 (agent / endpoint / frontend / docs) を提示

---

## 成果物

- [ ] `agents/timeline/` 新規モジュール (5 ファイル)
- [ ] `apps/api/main.py` + `apps/api/tests/test_timeline_endpoint.py`
- [ ] `apps/web/src/app/timeline/page.tsx` + `apps/web/src/lib/api.ts` 拡張
- [ ] ホーム + speech 詳細 + cities ダッシュボードからのリンク
- [ ] `docs/AGENT_PROMPTS.md` §0.9 + `docs/FEATURES.md` A-18

## 推奨 commit 構成

```
1. feat(plan-n-phase1): TimelineAgent + Chain-of-Thought + 5 unit test
2. feat(plan-n-phase1): GET /v1/timeline endpoint + BQ candidate fetch + 4 endpoint test
3. feat(plan-n-phase2): Frontend /timeline page + TimelineEventCard + NarrativeBanner
4. docs(plan-n): A-18 議論タイムライン + AGENT_PROMPTS §0.9 + miniplan
```

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| **候補 speeches がデータ不足 (< 3 件)** | 中 | early return: `TimelineNarrative(events=[], overall_summary="この期間のデータが不足しています")` で graceful、UI で「データ不足」表示 |
| **LLM context が長くなり token 上限超過** | 中 | 候補 speeches を 30 件で cap、各 speech の summary は最初の 1 行 + title のみ送信 (送信 token < 4K) |
| **倫理 violation (政治家名 leak)** | 高 | overall_summary + 各 event 全フィールドに FORBIDDEN_PATTERNS post-validation、leak 検出で raw fallback |
| **LLM が source_speech_id を捏造** | 高 | post-validation で event.source_speech_id を candidate 集合内 ID に限定、外れたら該当 event を削除 |
| **重複 speech (同自治体同日複数)** | 低 | BQ ORDER BY 自然優先、LLM が Chain-of-Thought で圧縮する想定 |
| **municipality_name lookup 失敗** | 低 | 既存 `_MUNI_NAME_MAP` + `自治体{code}` fallback (Plan X と同じ) |
| **/v1/timeline が related endpoint と機能重複** | 中 | related = RAG semantic 検索 (1 speech 起点)、timeline = 時系列ナラティブ (theme 起点) と差別化、UI 上も別 page |

---

## Out of Scope (Plan N では実装しない)

- 国会単体 timeline (municipality_code='00000' のみ、需要次第で Plan N-2)
- 複数 interest 軸の cross-cutting timeline (1 軸のみサポート)
- 関連自治体 (近隣自治体含む) の合算 timeline
- TimelineAgent を ADK 化、Concierge tool として再利用 (Plan X と同様、独立 Agent)
- Timeline の RSS / メール購読
- イベント間の因果関係抽出 (event A が event B を引き起こした、等)

---

## 受け入れ条件 (Definition of Done)

- [ ] `pytest agents/ apps/api/tests/` → 全 pass (234 + 新規 9+ = 243+)
- [ ] `TimelineAgent.narrate()` が LLM 成功時に events 5-10 件を返す
- [ ] LLM 失敗時 fallback で raw 上位 5 speeches が return、source="rule_based"
- [ ] source_speech_id は candidate 集合外なら除去される (捏造防止)
- [ ] FORBIDDEN_PATTERNS leak 検出時は fallback、leaked 文字列は user-facing 出力に残らない
- [ ] `GET /v1/timeline?theme_interest=住居&municipality_code=13104` が 200 で TimelineNarrative を返す
- [ ] Frontend `/timeline` で縦スクロール UI、event クリックで `/feed/[id]` 遷移
- [ ] `next build` pass、`tsc --noEmit` pass
- [ ] docs 2 ファイル更新
- [ ] 推奨 commit message 提示 (実 commit/push は人間)
