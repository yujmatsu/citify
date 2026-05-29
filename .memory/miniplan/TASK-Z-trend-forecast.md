# ミニプラン: Plan Z 議題件数トレンド予測 Agent

## 概要

- **タスク ID**: TASK-Z (バランス版 余裕枠 COULD #1)
- **目的**: ユーザーが選んだ interest 軸の議題件数を月別時系列で集計し、過去 6-12 か月のトレンドから将来 3 か月を線形外挿で予測。`ForecastNarrator` Agent がトレンドを「上昇/下降/横ばい/急騰/急落」分類 + 介入的説明。ハッカソン審査基準①「マルチエージェント必然性」+ ④「実用性」を補強し、Plan X (空間ヒートマップ) と Plan N (時系列ナラティブ) に続く「数値時系列予測」のキラー機能。
- **完了条件**:
  - `ForecastEngine` (純粋計算、LLM 不要、numpy 等の追加依存なし) が月別件数 → 単純線形回帰 + 移動平均で 3 か月予測 (clip 0+)
  - `ForecastNarrator` 独立 Agent (Plan X / Plan N と同パターン) がトレンドを 5 分類 + 介入的説明
  - `GET /v1/forecast?theme_interest=...&user_id=...&municipality_code=...&history_months=12` endpoint
  - Frontend `/forecast` page で SVG 折れ線グラフ (自前実装、Chart.js 等の依存追加なし) + NarrativeBanner + InterestSelector
  - LLM 失敗時 / 倫理 leak 時は rule-based fallback (trend 分類のみ、ナラティブなし)
  - 倫理ガード: `POLITICAL_PERSON_PATTERNS` (Plan N と共有) + 「特定地域推奨禁止」(narrative に都道府県名 leak チェック、Plan X 流用)
  - 10+ unit/integration test、既存 257 件と合わせて全 pass
  - docs/AGENT_PROMPTS.md §0.10 + docs/FEATURES.md A-19 追加
- **想定工数**: 3 日 = 18h (余裕枠なので圧縮可能、Phase 2 frontend を MVP に縮小して 12-14h 着地目標)

---

## 設計

### Agent 構成

```
ForecastEngine (純粋計算、LLM なし)
  ├─ 入力: 月別件数 list[MonthCount]
  └─ 出力: ForecastSeries (historical + forecast 3 か月 + trend_classification + slope)

ForecastNarrator (独立 Agent、Plan X HeatmapAdvisor と同型)
  ├─ 入力: ForecastSeries + PersonaContext (年代/関心軸)
  └─ 出力: ForecastNarrative
        ├─ headline (40 字、e.g. "住居議題は緩やかに増加中")
        ├─ reasoning (200 字、Chain-of-Thought ベース介入的説明)
        ├─ confidence: "high" | "medium" | "low" (データ件数 + slope の安定度で判定)
        └─ source: "llm" | "rule_based"
```

### ForecastEngine 計算ロジック (numpy なし、Reviewer High #2 反映)

```python
def forecast_series(monthly_counts: list[int], horizon: int = 3) -> ForecastResult:
    """過去 N か月 → 未来 horizon か月予測。

    実装:
        1. 移動平均 (window=3) で smoothing
        2. 最後の 6 ヶ月で単純線形回帰 (slope = covariance / variance)
        3. slope 標準誤差を計算 (純 Python、Reviewer High #2):
             se(slope) = sqrt( sum((y_i - y_hat_i)^2) / (n-2) / sum((x_i - x_mean)^2) )
        4. forecast[i] = max(0, min(last_smoothed + slope * (i+1), last_smoothed * 3))  # clip 0+ & 上限
        5. trend 分類:
           - slope > 1.5 → "surge"
           - slope > 0.5 → "increasing"
           - slope < -1.5 → "crash"
           - slope < -0.5 → "decreasing"
           - else → "flat"
        6. confidence 判定 (Reviewer High #2 標準誤差ベース + 分散ベース):
           - history < 6 ヶ月 → "low"
           - stddev / mean > 0.5 (CV 大) → "low"
           - |slope| / se(slope) < 2.0 (t 値小) → "medium"
           - 上記すべて満たさず → "high"
    """
```

### UI Disclaimer (Reviewer High #1 反映: PROJECT.md §5 境界)

特定 `municipality_code` 指定時のトレンド表示は、その自治体の「議題件数が増えている」事実を示しても **「ここに移住すべき / ここがホット」のような推奨ではない** ことを明示する。

**MVP 必須実装**:
1. Frontend `/forecast` page 上部に **常設 disclaimer banner**:
   > 📊 このグラフは議題件数の数値推移を可視化したものです。特定の自治体への移住・行動を推奨するものではありません。
2. `ForecastNarrative.reasoning` の post-validation に **自治体名 leak チェック** を追加:
   - Plan X の `PREFECTURE_NAMES_JA` (47 都道府県) 検出 → fallback
   - **加えて主要市区町村名 blocklist** (`_MUNI_NAME_MAP` の値から取得、政令市 + 特別区) → leak 検出で fallback
3. DoD に「reasoning に自治体名が含まれない」テスト追加

### LLM 出力 schema 制約 (Reviewer Medium #5 反映: 数値捏造防止)

`ForecastNarrative` schema には **`slope` / `trend_classification` を含めない**:
- 数値は Engine 側で確定し、frontend で結合表示
- Narrator は `headline` + `reasoning` のみ生成 (LLM が数値を勝手に書き換えるリスクを構造的に排除)
- Plan N の `source_speech_id` 捏造防止と同パターン

### ForecastNarrator system prompt (Chain-of-Thought)

```
あなたは Citify の議題トレンド予測ナレーター (Forecast Narrator) です。
渡された月別件数時系列 + 計算済み trend_classification + slope を元に、
ユーザー (年代 + 関心軸) 向けに「何が起きているのか」を 200 字以内で介入的に説明してください。

# Chain of Thought (内部思考)
1. trend_classification ("increasing" / "decreasing" / "flat" / "surge" / "crash") を読む
2. ユーザーペルソナ (年代 + 関心軸) を考慮
3. 「なぜそのトレンドが重要なのか」「ユーザーにとって何を意味するか」を介入的に説明
4. 40 字キャッチーな headline + 200 字 reasoning

# 倫理ガード (絶対遵守)
- 47 都道府県名禁止 (特定地域推奨回避、Plan X と同方針)
- 政治家名 / 政党名 / 賛否表明禁止 (Plan N と同パターン)
- 「今後 XX 県に移住すべき」のような推奨を含めない
- トレンドの「示唆」を語る、特定の行動を「推奨」しない

# トーン
- 若者向け、客観的、データドリブン
- 例 OK: "住居議題は半年で 30% 増加、議論の場で住宅政策がホットトピックに"
- 例 NG: "東京都の住居議題が活発なので移住推奨"
```

### BQ query (集計行除外 + 月別集計、Reviewer Medium #4 反映: NULL date 除外)

```sql
SELECT
  FORMAT_DATE("%Y-%m", meeting_date) AS year_month,
  COUNT(DISTINCT speech_id) AS speech_count
FROM `{table_fqn}`
WHERE user_id = @user_id
  AND meeting_date IS NOT NULL                       -- Reviewer Medium #4
  AND meeting_date BETWEEN @start_date AND @end_date
  AND @interest IN UNNEST(matched_interests)
  AND (@muni IS NULL OR municipality_code = @muni)
  AND municipality_code != '00000'
  AND municipality_code NOT LIKE '%000'
GROUP BY year_month
ORDER BY year_month ASC
```

→ 1 query で月別件数を ~12 行で返す、scan 量は user_id × interest × 期間で絞られる

### Schema 定義

```python
# agents/forecast/schema.py

class MonthCount(BaseModel):
    year_month: str  # "2026-03"
    speech_count: int

class ForecastPoint(BaseModel):
    year_month: str
    speech_count: float  # 予測値 (clip 0+ 後)
    is_forecast: bool

class ForecastSeries(BaseModel):
    historical: list[MonthCount]  # 過去 6-12 ヶ月
    forecast: list[ForecastPoint]  # 未来 3 ヶ月
    trend_classification: Literal["surge", "increasing", "flat", "decreasing", "crash"]
    slope: float  # 月あたり件数増減
    confidence: Literal["high", "medium", "low"]

class ForecastNarrative(BaseModel):
    headline: str = Field(max_length=40)
    reasoning: str = Field(max_length=240)
    source: Literal["llm", "rule_based"]

class ForecastResponse(BaseModel):
    series: ForecastSeries
    narrative: ForecastNarrative
```

### Frontend `/forecast` 構成

```
apps/web/src/app/forecast/
├── page.tsx              # メインページ (interest + 自治体 + 期間選択)
└── (内部 component)
    ├── ForecastChart    # 自前 SVG 折れ線グラフ (Chart.js 依存追加なし)
    ├── NarrativeBanner  # headline + reasoning + source 区別
    └── TrendBadge       # surge/increasing/flat/decreasing/crash の色分け
```

#### SVG 折れ線グラフ自前実装方針

- viewBox: `0 0 600 300`
- X 軸: 過去 12 か月 + 未来 3 か月の 15 ティック
- Y 軸: 0 〜 max(speech_count) * 1.2
- historical: 実線青、各点を circle で描画
- forecast: 破線オレンジ + 半透明信頼区間バンド (slope の絶対値で幅調整)
- 依存追加なし、Plan X tile-grid と同じ「軽量・依存最小」方針

---

## 作業ステップ

### Phase 1 (5-6h): Backend (ForecastEngine + ForecastNarrator + endpoint)

1. [ ] **Step 1.1**: `agents/forecast/` ディレクトリ新規 (5 ファイル: `__init__.py` / `schema.py` / `engine.py` / `main.py` / `prompts/system.py`)
2. [ ] **Step 1.2**: `ForecastEngine.forecast_series()` 実装 (移動平均 + 線形回帰 + clip + trend 分類)
3. [ ] **Step 1.3**: `ForecastNarrator.narrate()` 実装 (Gemini Flash + Chain-of-Thought + LLM 失敗時 rule_based fallback)
4. [ ] **Step 1.4**: 倫理 post-validation (Plan N の `POLITICAL_PERSON_PATTERNS` 流用 + Plan X の `PREFECTURE_NAMES_JA` を import)
5. [ ] **Step 1.5**: `agents/forecast/tests/test_forecast.py` (engine 5+ test + narrator 4+ test)
6. [ ] **Step 1.6**: `GET /v1/forecast` endpoint 追加 + BQ 月別集計
7. [ ] **Step 1.7**: `apps/api/tests/test_forecast_endpoint.py` (4+ test)

### Phase 2 (5-7h): Frontend `/forecast` page

8. [ ] **Step 2.1**: `apps/web/src/lib/api.ts` に `fetchForecast()` + zod schema
9. [ ] **Step 2.2**: `apps/web/src/app/forecast/page.tsx` メインページ
10. [ ] **Step 2.3**: `ForecastChart` SVG component (自前折れ線、依存追加なし)
11. [ ] **Step 2.4**: `NarrativeBanner` + `TrendBadge` component
12. [ ] **Step 2.5**: `next build` smoke test

### Phase 3 (2-3h): nav + docs

13. [ ] **Step 3.1**: ホームに「📈 議題トレンド予測」リンク追加
14. [ ] **Step 3.2**: `docs/AGENT_PROMPTS.md` §0.10 ForecastNarrator
15. [ ] **Step 3.3**: `docs/FEATURES.md` A-19 エントリ
16. [ ] **Step 3.4**: `ruff format/check` + 全 pytest 再走 → 全 pass

### Phase 4 (0.5h): 推奨 commit 提示

17. [ ] **Step 4.1**: 4 commit 構成提示

---

## 成果物

- [ ] `agents/forecast/` 新規モジュール (5 ファイル + tests)
- [ ] `apps/api/main.py` + `apps/api/tests/test_forecast_endpoint.py`
- [ ] `apps/web/src/app/forecast/page.tsx` + `apps/web/src/lib/api.ts` 拡張
- [ ] ホーム + speech 詳細からの導線
- [ ] `docs/AGENT_PROMPTS.md` §0.10 + `docs/FEATURES.md` A-19

## 推奨 commit 構成

```
1. feat(plan-z-phase1): ForecastEngine + ForecastNarrator + 9+ unit test
2. feat(plan-z-phase1): GET /v1/forecast endpoint + BQ 月別集計 + 4+ endpoint test
3. feat(plan-z-phase2): Frontend /forecast page + 自前 SVG ForecastChart
4. docs(plan-z): A-19 議題トレンド予測 + AGENT_PROMPTS §0.10 + miniplan
```

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| **線形外挿の過大予測** (slope が大きいと 3 か月後に異常値) | 高 | clip 0+ で下限、`min(forecast, last_value * 3)` で上限 cap。slope を `confidence="low"` 判定に使用 |
| **データ不足** (history < 6 か月) | 高 | early return: `series=raw + forecast=[]` + `narrative="データ不足"` |
| **倫理 leak** (政治家名 / 政党 / 都道府県名) | 高 | Plan N / Plan X の検出ロジックを 2 つとも適用、leak 検出で rule_based fallback |
| **「予測」UI が投資推奨と誤解** | 中 | UI コピーで「議論件数の数値推移、特定行動の推奨ではない」と明示、disclaimer banner |
| **LLM context 長く token 超過** | 低 | historical 12 行 + forecast 3 行 = ~15 行を JSON で送る、~1K token |
| **/v1/heatmap と /v1/timeline と機能重複** | 低 | heatmap=空間軸 / timeline=時系列イベント / forecast=数値時系列予測 で明確に差別化、ホーム nav に 3 つ並べる |
| **numpy 等追加依存** | 低 | 純 Python 計算で実装 (sum/mean/list comprehension のみ、線形回帰は手書き) |
| **frontend Chart ライブラリ依存** | 低 | 自前 SVG 折れ線 (Plan X tile-grid と同方針)、依存追加ゼロ |

---

## Out of Scope (Plan Z では実装しない)

- 複数 interest 軸の同時予測 (1 軸のみ)
- ARIMA / Prophet 等の高度な時系列モデル (3 か月予測には線形回帰で十分)
- 信頼区間の厳密計算 (frontend で slope ベース簡易表示のみ)
- ヒートマップとの統合 (Plan X と独立、別 page)
- ForecastNarrator の ADK 化 / Concierge tool 化 (Plan N と同じ Out of Scope)
- 予測の精度評価 (backtesting、別 Plan)

---

## 受け入れ条件 (Definition of Done、Reviewer Low #6 反映: テスト件数 13+)

- [ ] `pytest agents/ apps/api/tests/` → 全 pass (257 + 新規 **13+** = 270+)
- [ ] `ForecastEngine.forecast_series(monthly_counts=[1,2,3,4,5,6])` が `slope > 0` + `trend="increasing"` を返す
- [ ] `forecast_series([10,8,6,4,2])` が `slope < 0` + `trend="decreasing"` を返す
- [ ] data 不足 (history < 6) → empty forecast + `confidence="low"`
- [ ] 分散大ケース (CV > 0.5) で `confidence="low"` 強制 (Reviewer High #2)
- [ ] 標準誤差大ケース (t 値 < 2) で `confidence="medium"` (Reviewer High #2)
- [ ] `ForecastNarrator` LLM 失敗 → rule_based fallback (trend 分類のみ、ナラティブテンプレ)
- [ ] 倫理 leak (都道府県名 or 政治家名 or **主要市区町村名 Reviewer High #1**) → fallback、leaked 文字列ユーザー向けに残らない
- [ ] `ForecastNarrative` schema に `slope` / `trend` 含まれない (Reviewer Medium #5: 数値捏造防止)
- [ ] `GET /v1/forecast?theme_interest=住居&days_back=365` で 200 + ForecastResponse
- [ ] Frontend `/forecast` で SVG 折れ線 + NarrativeBanner + TrendBadge + **常設 disclaimer banner** (Reviewer High #1)
- [ ] `next build` pass、`tsc --noEmit` pass
- [ ] docs 2 ファイル更新
- [ ] 推奨 commit message 提示
