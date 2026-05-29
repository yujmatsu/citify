# ミニプラン: Plan X 全国ヒートマップ Agent

## 概要

- **タスク ID**: TASK-X
- **目的**: ユーザーのペルソナ (年代/関心軸/free_form_context) を受けて、47 都道府県を「最も意味のある統計指標」で色付け表示する全国ヒートマップを提供。ハッカソン審査基準②「ストーリー性」と④「実用性」を補強。
- **完了条件**:
  - 新規 `HeatmapAdvisor` Agent がペルソナを受けて metric_column / direction / reasoning を返す
  - `GET /v1/heatmap?user_id=...&interest=...` endpoint が 47 都道府県集計 + 県別 TOP3 自治体を返す
  - Frontend `/heatmap` page が日本地図 (47 都道府県) を Chloropleth レンダリング
  - 都道府県クリックで TOP3 自治体モーダル表示 (Plan L+LL の HistoryModal パターン踏襲)
  - Agent 選定理由を画面上部 banner で表示 (ストーリー性)
  - LLM call 失敗時は固定 mapping rule (FALLBACK_METRIC_BY_INTEREST) で graceful degrade
  - 10+ unit/integration test、既存 217 件と合わせて全 pass
  - docs/AGENT_PROMPTS.md §0.8 + docs/FEATURES.md A-17 追加
- **想定工数**: 3 日 = 18h

---

## 設計

### Agent 構成

```
HeatmapAdvisor (Plan X 新規)
  ├─ 入力: ペルソナ (age_group, interests, free_form_context)
  └─ 出力: HeatmapAdvice
        ├─ metric_column: str (e.g. "used_apartment_median_price_man_yen")
        ├─ metric_label_ja: str (e.g. "中古マンション中央値")
        ├─ direction: "lower_is_better" | "higher_is_better"
        ├─ reasoning: str (max 200 字、ユーザーへの説明)
        └─ persona_summary: str (max 100 字、画面 banner 用)
```

### 都道府県 47 メッシュに絞る理由

| 案 | ポリゴン数 | 初期 payload | 描画 SVG ノード数 | 判定 |
|---|---|---|---|---|
| 1,917 自治体メッシュ | 1,917 | TopoJSON 3-5 MB | 数千 path | ❌ 初期ロード重、描画遅延 |
| **47 都道府県メッシュ + クリックで TOP3 自治体** | 47 | ~50KB | 47 path | ✅ **採用** |

### 選定可能 metric_column 一覧 (municipality_stats から)

| 軸 | metric_column | direction |
|---|---|---|
| 住居 | `used_apartment_median_price_man_yen` | lower_is_better |
| 住居 (㎡単価) | `used_apartment_median_unit_price_yen` | lower_is_better |
| 子育て | `childcare_facility_count` | higher_is_better |
| 医療 | `medical_facility_count` | higher_is_better |
| 防災 | `emergency_shelter_count` | higher_is_better |
| 将来人口 | `population_change_2025_2050_pct` | higher_is_better |
| 若者比率 | `youth_share_pct` | higher_is_better |
| 高齢比率 | `elderly_share_pct` | lower_is_better (若者目線) |
| 出生率 | `birth_rate_per_1000` | higher_is_better |

→ HeatmapAdvisor が **ペルソナ × 関心軸からこの一覧の中から 1 つを選ぶ** (LLM 1 call、出力 schema 強制で安全)。

### HeatmapAdvisor の Chain-of-Thought prompt (Reviewer High #3 反映)

マルチエージェント必然性を担保するため、LLM call は固定 mapping より「介入的説明」を生成する。

**System prompt 構造**:
```
あなたは Citify のヒートマップ指標選定 Agent です。
ユーザーのペルソナを踏まえ、47 都道府県を比較する際の「最も示唆的な指標」を
municipality_stats の中から 1 つ選び、選定理由を 200 字以内で説明してください。

# Chain of Thought (内部思考、最終出力に含めない)
1. ペルソナ要約: 年代 / 関心軸 / 自由記述 を 1 行にまとめる
2. 候補 metric 3 つ列挙: ペルソナと相性の良い候補を rubric から 3 つ
3. 最適 1 つ選定 + 理由: 「他 2 つではなくこの 1 つを選ぶ理由」を介入的に説明

# 出力 (HeatmapAdvice schema 強制)
- metric_column / metric_label_ja / direction / reasoning (200 字) / persona_summary (100 字)

# 倫理ガード (Reviewer Medium #5 反映)
- reasoning には **個別都道府県名 (北海道〜沖縄県の 47 県名) を含めない**
- 「あなたには XX 県が向いている」のような特定地域の推奨は禁止
- metric の選定理由のみを説明 (例: "子育て世帯には保育施設密度が指標になります" は OK、
  "東京都は施設数が多いので推奨" は NG)
```

**reasoning 文字列の prefix で LLM path と fallback を区別** (UI 表示用):
- LLM 成功時: 通常の本文 (prefix なし)
- LLM 失敗時 fallback: `"(rule-based) "` を先頭に付与

### LLM 失敗時の fallback (Reviewer 想定 Critical 予防)

```python
FALLBACK_METRIC_BY_INTEREST: dict[Interest, HeatmapMetricSpec] = {
    "住居": HeatmapMetricSpec(column="used_apartment_median_price_man_yen", direction="lower_is_better", label_ja="中古マンション中央値 (万円)"),
    "子育て": HeatmapMetricSpec(column="childcare_facility_count", direction="higher_is_better", label_ja="保育・幼児教育施設数"),
    "医療": HeatmapMetricSpec(column="medical_facility_count", direction="higher_is_better", label_ja="医療機関数"),
    "防災": HeatmapMetricSpec(column="emergency_shelter_count", direction="higher_is_better", label_ja="緊急避難場所数"),
    # ...
}
```

- LLM call timeout / parse failure 時はこの mapping にフォールバック
- reasoning = "(fallback rule) {interest} 軸では一般的に {label_ja} を指標とします"

### BQ query 設計

**重要 (Reviewer Critical #1 反映)**: 集計行を除外しないと 47 県 + 個別自治体が二重計上される。
既存 `apps/api/main.py` / `agents/concierge/tools.py` と同様に以下のフィルタを必須:

```
AND municipality_code NOT LIKE '%000'   -- 都道府県集計行 (XX000) を除外
AND municipality_code != '00000'        -- 国会集計行を除外
```

**都道府県集計** (中央値ベース、外れ値耐性):

```sql
WITH muni_with_pref AS (
  SELECT
    s.municipality_code,
    SUBSTR(s.municipality_code, 1, 2) AS prefecture_code,
    s.{metric_column}
  FROM `{project}.{dataset}.municipality_stats` s
  WHERE s.{metric_column} IS NOT NULL
    AND s.municipality_code NOT LIKE '%000'
    AND s.municipality_code != '00000'
)
SELECT
  prefecture_code,
  APPROX_QUANTILES({metric_column}, 100)[OFFSET(50)] AS metric_median,
  COUNT(*) AS muni_count
FROM muni_with_pref
GROUP BY prefecture_code
ORDER BY metric_median {direction};
```

**県別 TOP3 自治体** (1 query で 47×3 = 141 件):

```sql
SELECT prefecture_code, municipality_code, name, {metric_column}
FROM (
  SELECT
    SUBSTR(s.municipality_code, 1, 2) AS prefecture_code,
    s.municipality_code,
    m.name,
    s.{metric_column},
    ROW_NUMBER() OVER (PARTITION BY SUBSTR(s.municipality_code, 1, 2) ORDER BY s.{metric_column} {direction}) AS rk
  FROM `{project}.{dataset}.municipality_stats` s
  JOIN `{project}.{dataset}.municipalities` m USING (municipality_code)
  WHERE s.{metric_column} IS NOT NULL
    AND s.municipality_code NOT LIKE '%000'
    AND s.municipality_code != '00000'
)
WHERE rk <= 3;
```

→ BQ コスト: 1 endpoint call で 2 query、合計 ~1,917 行 scan、~100 KB

### API response shape

```python
class HeatmapResponse(BaseModel):
    advice: HeatmapAdvice               # HeatmapAdvisor 出力
    prefecture_values: list[PrefValue]  # 47 件
    top_municipalities: list[PrefTop]   # 47 件 (各 prefecture_code に 3 自治体)

class PrefValue(BaseModel):
    prefecture_code: str  # "01" ~ "47"
    prefecture_name: str  # "北海道" 等
    metric_median: float
    rank: int             # 1-47 (direction 反映後の順位)

class PrefTop(BaseModel):
    prefecture_code: str
    municipalities: list[MunicipalityCandidate]  # 既存 schema 再利用
```

### Frontend 構成

```
apps/web/src/app/heatmap/
├── page.tsx                    # メインページ (chloropleth + クリック)
└── (内部)
    ├── HeatmapMap component   # react-simple-maps + 47 都道府県 TopoJSON
    ├── AdviceBanner component # Agent reasoning + persona_summary を上部表示
    ├── PrefectureModal        # クリック後 TOP3 表示
    └── InterestSelector       # 関心軸プルダウン (10 軸)
apps/web/public/japan-prefectures-topo.json  # 47 県 TopoJSON (~50KB)
apps/web/src/lib/api.ts        # fetchHeatmap() 追加
```

### react-simple-maps の Next.js 16 / React 19 互換性 (Reviewer High #2 反映)

- 公式 v3.x は React 18+ 対応、React 19 で peer deps の警告/失敗の可能性あり
- **Phase 0 (90 分 spike) で smoke test 実施**:
  1. `npm install react-simple-maps @types/react-simple-maps` で peer dep 警告確認
  2. `npx tsc --noEmit` 通過確認
  3. 最小 page で `<ComposableMap><Geographies>` が render 成功するか確認
- **NG 確定時の fallback 詳細仕様** (具体化):
  - `apps/web/public/japan-prefectures-topo.json` を **GeoJSON 形式** に変換して使用
  - `apps/web/src/app/heatmap/SimpleSvgMap.tsx` 自前実装:
    - `<svg viewBox="0 0 800 800">` + `d3-geo` の `geoMercator()` で path 文字列生成 (47 path)
    - `onClick={(e) => onPrefectureClick(prefectureCode)}` で click handler
    - 色付けは `fill={interpolateBlues(value)}` で直接適用
  - 工数増分: +2h (Phase 2 を 6h → 8h、Phase 3 短縮で吸収)

---

## 作業ステップ (Reviewer Low #8 反映: Phase 0 追加、Phase 4 圧縮)

### Phase 0 (1.5h): React 19 互換 spike

0. [ ] **Step 0.1**: `apps/web/` で `npm install react-simple-maps @types/react-simple-maps` (peer dep 警告チェック)
1. [ ] **Step 0.2**: 最小 page で `<ComposableMap><Geographies>` smoke test
2. [ ] **Step 0.3**: NG なら `SimpleSvgMap.tsx` 自前実装方針確定 (詳細仕様は本文参照)、go/no-go 判定

### Phase 1 (6h): HeatmapAdvisor + Backend API

1. [ ] **Step 1.1**: `agents/heatmap_advisor/` ディレクトリ新規 (`__init__.py`, `schema.py`, `prompts/system.py`, `main.py`)
   - **`population_change_2025_2050_pct` の符号確認** (Reviewer Low #7): `apps/api/main.py:525` の schema 定義を読んで direction を最終確定
2. [ ] **Step 1.2**: `HeatmapAdvice` / `HeatmapMetricSpec` Pydantic schema 定義
3. [ ] **Step 1.3**: `HeatmapAdvisor.suggest_metric(persona, interest)` メソッド実装
   - Gemini Flash + Chain-of-Thought prompt (Reviewer High #3)
   - LLM-failure fallback + `"(rule-based) "` prefix (Reviewer Medium #5)
   - **倫理ガード**: reasoning に 47 県名禁止
4. [ ] **Step 1.4**: `agents/heatmap_advisor/tests/test_advisor.py` (**5+ test**、Reviewer Medium #6):
   - LLM 成功 path / LLM 失敗 fallback path
   - 全 47 県名が reasoning に含まれない検証
   - 全 10 interest 軸の metric mapping 網羅
   - direction の符号正しさ
5. [ ] **Step 1.5**: `apps/api/main.py` に `GET /v1/heatmap` endpoint 追加 + BQ query 2 本
   - **`NOT LIKE '%000'` + `!= '00000'` フィルタ必須** (Reviewer Critical #1)
6. [ ] **Step 1.6**: `apps/api/tests/test_heatmap_endpoint.py` (**4+ test**):
   - 200 with mock advisor + mock BQ
   - advisor LLM 失敗 graceful (rule-based fallback)
   - BQ クラッシュ 500 graceful
   - 集計行 (XX000) フィルタが効くこと (mock data で混入させて検証)

### Phase 2 (6-8h): Frontend /heatmap page

7. [ ] **Step 2.1**: Phase 0 結果で確定したライブラリ採用 (react-simple-maps or SimpleSvgMap)
8. [ ] **Step 2.2**: `apps/web/public/japan-prefectures-topo.json` (47 県 TopoJSON、dataofjapan/land MIT) を配置
9. [ ] **Step 2.3**: `apps/web/src/lib/api.ts` に `fetchHeatmap()` + zod schema
10. [ ] **Step 2.4**: `apps/web/src/app/heatmap/page.tsx` (chloropleth + AdviceBanner + InterestSelector)
11. [ ] **Step 2.5**: `PrefectureModal` component (クリック後 TOP3 表示、既存 HistoryModal パターン踏襲)
12. [ ] **Step 2.6**: `next build` smoke test

### Phase 3 (3h): ペルソナ統合 + docs

13. [ ] **Step 3.1**: フィードページから `/heatmap` へのリンク追加 (既存 navigation 拡張)
14. [ ] **Step 3.2**: `docs/AGENT_PROMPTS.md` §0.8 HeatmapAdvisor section
15. [ ] **Step 3.3**: `docs/FEATURES.md` A-17 エントリ
16. [ ] **Step 3.4**: `ruff format/check` + 全 pytest 再走 (217 + 新規 **9+** = 226+) → 全 pass

### Phase 4 (0.5h): 推奨 commit 提示

17. [ ] **Step 4.1**: 4 commit 構成 (advisor / endpoint / frontend / docs) を提示

**合計工数**: Phase 0 1.5h + Phase 1 6h + Phase 2 6-8h + Phase 3 3h + Phase 4 0.5h = **17-19h** (~3 日)

### テスト合計 (Reviewer Medium #6 反映)

| 階層 | 件数 | カバー範囲 |
|---|---|---|
| `agents/heatmap_advisor/tests/test_advisor.py` | **5+** | LLM success / fallback / ethics guard / interest 網羅 / direction |
| `apps/api/tests/test_heatmap_endpoint.py` | **4+** | 200 / advisor fail graceful / BQ fail graceful / 集計行フィルタ |
| **合計** | **9+** | (既存 217 + 9+ = 226+) |

---

## 成果物

- [ ] `agents/heatmap_advisor/` 新規モジュール (5 ファイル)
- [ ] `apps/api/main.py` + テスト (2 BQ query + 1 endpoint)
- [ ] `apps/web/src/app/heatmap/page.tsx` + components
- [ ] `apps/web/public/japan-prefectures-topo.json` 配置
- [ ] `docs/AGENT_PROMPTS.md` §0.8 + `docs/FEATURES.md` A-17

## 推奨 commit 構成 (人間が手動)

```
1. feat(plan-x-phase1): HeatmapAdvisor Agent + LLM-failure fallback + 5 unit test
2. feat(plan-x-phase1): GET /v1/heatmap endpoint + BQ 都道府県集計 + 4 endpoint test
3. feat(plan-x-phase2): Frontend /heatmap page (react-simple-maps + Chloropleth + TOP3 modal)
4. docs(plan-x): A-17 全国ヒートマップ + AGENT_PROMPTS §0.8 + miniplan
```

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| **react-simple-maps が React 19 / Next.js 16 で動かない** | 高 (Phase 2 全体ブロック) | Phase 2 開始前に smoke test、NG なら軽量 svg 直書きフォールバック (47 path 描画は実装可能) |
| **HeatmapAdvisor LLM 失敗時に endpoint がクラッシュ** | 高 | FALLBACK_METRIC_BY_INTEREST 固定 mapping、try/except で graceful fallback、reasoning に "(fallback rule)" prefix |
| **municipality_stats に prefecture_code 直列なし** | 中 | SUBSTR(municipality_code, 1, 2) で抽出 (5 桁コードの上位 2 桁が県コード、要 BQ 動作確認) |
| **BQ コスト増** | 低 | endpoint で 1 hour TTL cache (既存 _STATS_CACHE と同じ pattern)、scan 上限 1,917 行 |
| **TopoJSON の入手元と再頒布性** | 中 | dataofjapan/land (MIT License) を採用、apps/web/public/ にコミット |
| **ペルソナ × 関心軸の組合せ爆発** | 低 | LLM が動的選定、固定マッピングは 10 軸 × default のみ管理 |

---

## Out of Scope (Plan X では実装しない)

- 1,917 自治体メッシュ表示 (UX/負荷的に不適、別 Plan で要件次第)
- 地図のズーム / パン (47 県固定スケールで十分)
- 時系列ヒートマップ (年別変化アニメーション、別 Plan)
- 比較ビュー (Plan B-2 の比較機能と統合は別 Plan)
- HeatmapAdvisor の ADK 化 (Plan E Concierge から呼び出すなら別 Plan)
- **Concierge tool としての再利用** (Reviewer High #4 反映): HeatmapAdvisor は **完全に独立 Agent**
  として実装、Concierge から tool として呼び出さない。Concierge との API 形状の互換性は確保しない。
  将来再利用が必要になったら別 Plan で adapter 層を追加する。

---

## 受け入れ条件 (Definition of Done)

- [ ] `pytest agents/ apps/api/tests/` → 全 pass (217 + 新規 10+)
- [ ] `HeatmapAdvisor.suggest_metric()` が LLM 失敗時に fallback mapping を確実に返す
- [ ] `GET /v1/heatmap?user_id=X&interest=住居` が 200 で advice + 47 prefecture + 141 muni を返す
- [ ] Frontend `/heatmap` で日本地図が色付け表示、クリックで TOP3 モーダル表示
- [ ] `next build` pass、`tsc --noEmit` pass
- [ ] docs 2 ファイル更新
- [ ] 推奨 commit message 提示 (実 commit/push は人間)
