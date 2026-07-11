# FEATURES.md — 機能仕様書

> Citify の全機能を優先度別に整理した仕様書です。各機能には説明・受け入れ条件・依存関係・Drop 判断条件を記載しています。
>
> Coding Agent は実装前に該当機能の仕様を必ず確認してください。

> **⚠️ 実装との差分 (2026-07)**:本書は設計時仕様。実装は Watcher/feed 中心にピボット。Veo(B-3)は未使用、メディアは Imagen 静止サムネ10種。エージェントは13体(pipeline4/ADK3/分析4/運用2)。矛盾時はコード(main.py・agents/*/schema.py・infra DDL)が正。

## 優先度の定義

- **Must**:これが動かないとプロダクトとして成立しない。最優先で実装
- **Should**:差別化要素。Must が完成してから着手
- **Could**:時間があれば実装。Must/Should の余力で
- **Won't**:今回はやらない。ピッチで「拡張可能性」として言及するに留める

---

## A. コア機能(Must)

### A-1. ユーザーオンボーディング

**説明**:初回起動時に住所(郵便番号 OK)、年代、関心軸を入力させ、自治体マスタとマッチング。Firestore にユーザープロファイルを保存。

**受け入れ条件**:
- 郵便番号から自治体を判定できる(国土交通省の住所マスタ or 民間 API)
- 年代は 10 歳刻みで選択(18-24 / 25-29 / 30-34 / 35-)
- 関心軸は複数選択(住居・雇用・結婚・子育て・税・起業・防災・医療・教育・移住)
- 入力完了で For You フィード画面に遷移

**依存**:自治体マスタ(A-2)

**Drop 判断**:このまま実装(コア体験の入口)

---

### A-2. 自治体マスタとマイ自治体登録

**説明**:全国 1,795 自治体のマスタデータを Firestore で管理。ユーザーは複数自治体を「マイ自治体」として登録できる(自分の街、実家、引越し候補等)。

**受け入れ条件**:
- 1,795 自治体の自治体コード・名称・都道府県・対応スクレイパー種別が登録されている
- ユーザーは最大 5 自治体を登録できる
- マスタには初期値として「対応済み」フラグが入る(Tier 1/2/3)
- 未対応自治体を登録した場合、リクエスト記録が残る

**依存**:なし(マスタは事前に整備)

**Drop 判断**:このまま実装

---

### A-3. 国会会議録 API クライアント

**説明**:国立国会図書館の国会会議録検索 API(認証不要、JSON 対応)から議事録を取得。発言単位で取得して BigQuery に保存。

**受け入れ条件**:
- 直近 30 日の発言を取得できる
- 検索キーワードで絞り込みできる
- レート制限を遵守(リクエスト間 1 秒以上)
- BigQuery にスキーマ(speechID, speaker, speakerGroup, speech, date, meetingURL)で保存

**依存**:BigQuery セットアップ

**Drop 判断**:このまま実装(国会データはコア素材)

---

### A-4. 議事録パーサー 1: DiscussNetPremium / kaigiroku.net

**説明**:`ssp.kaigiroku.net/tenant/{tenant_id}/` パターンの議事録を一括スクレイピング。数百自治体をこのパーサー 1 個でカバー。

**受け入れ条件**:
- tenant_id を渡せば該当自治体の議事録一覧を取得できる
- 会議名・日付・発言を構造化して BigQuery に保存
- 利用規約を遵守(レート制限、robots.txt 確認)
- 失敗時は自治体ごとにログを残してスキップ

**依存**:自治体マスタ、BigQuery

**Drop 判断**:このまま実装(これがないと自治体カバレッジが死ぬ)

---

### A-5. 翻訳 Agent

**説明**:役所言葉・法律用語を、ユーザーの年代と関心軸に応じた平易な言葉に変換する Gemini ベースのエージェント。

**受け入れ条件**:
- 議題テキストを入力 → 平易化された 3 行サマリを出力
- ユーザーの年代に応じてトーンを調整(20 代は親しみやすく、30 代は丁寧めに)
- 専門用語には括弧で補足を付ける
- 「賛成 / 反対」の立場を示す表現は生成しない(中立)

**依存**:Gemini API

**Drop 判断**:このまま実装(差別化の心臓部)

---

### A-6. 影響度 Agent

**説明**:議題とユーザープロファイル(年代、関心軸、登録自治体)のマッチング度をスコアリングする Gemini ベースのエージェント。

**受け入れ条件**:
- 議題と ユーザープロファイルを入力 → 0-100 のスコアと理由を出力
- スコア 50 以上の議題のみフィードに表示
- バッチでも単発でも実行可能

**依存**:Gemini API、自治体マスタ

**Drop 判断**:このまま実装

---

### A-7. 配信 Agent

**説明**:ユーザーごとに優先度順にソートされたフィードを生成・通知タイミングを判定する Agent。

**受け入れ条件**:
- ユーザーごとに直近 7 日の議題から影響度上位 10 件を選択
- 重複(同議題の複数回出現)を除去
- 通知タイミングは曜日と時間帯を学習(初期は固定で月曜 9 時)

**依存**:影響度 Agent

**Drop 判断**:このまま実装

---

### A-8. For You フィード(縦スクロール UI)

**説明**:ホーム画面に並ぶ縦スクロール型のフィード。1 議題 = 1 カード。タップで詳細ビュー。

**受け入れ条件**:
- 上から優先度順に議題カードが並ぶ
- カードにはタイトル、3 行サマリ、自治体名、サムネ画像が表示される
- 縦スワイプで次のカードに移動
- タップで A-9(議題詳細)に遷移

**依存**:配信 Agent、画像生成(B-3 または C-1)

**Drop 判断**:このまま実装

---

### A-9. 議題詳細ビュー

**説明**:1 つの議題に対する詳細ページ。サマリ、関連議事録発言、原典リンク、関連統計、関連議題を束ねた画面。

**受け入れ条件**:
- 平易化されたタイトル + 役所表記の正式タイトル両方を表示
- 議事録の関連発言を RAG 検索結果として 3 件表示
- 原典(議事録 URL or 自治体 HP)へのリンク必須
- 「気になる / 関係なさそう」ボタン(B-1)
- 動画があれば再生プレイヤー表示(B-3)

**依存**:議事録 RAG、配信 Agent

**Drop 判断**:このまま実装

---

### A-10. 議事録 RAG 基盤

**説明**:Vertex AI RAG Engine を用いて議事録・政策文書を index 化。エージェントから検索可能にする。

**受け入れ条件**:
- 国会議事録と取得済み自治体議事録を index 化
- セマンティック検索で関連発言を 3〜5 件取得できる
- 自治体・期間でフィルタできる
- 更新は日次バッチ

**依存**:議事録収集(A-3, A-4)、Cloud Storage

**Drop 判断**:このまま実装

---

### A-11. Cloud Run デプロイ + Firebase Hosting

**説明**:バックエンド API は Cloud Run、フロントエンドは Firebase Hosting にデプロイ。常時アクセス可能な公開 URL を持つ。

**受け入れ条件**:
- 本番環境 URL でアクセスできる
- リクエストがない時は Cloud Run のスケーリング 0 でコスト最小化
- HTTPS、CORS 設定済み
- 健全性チェックエンドポイントあり

**依存**:なし

**Drop 判断**:このまま実装(提出要件)

---

### A-12. CI/CD パイプライン

**説明**:GitHub Actions で Lint + Test、Cloud Build で自動デプロイ。

**受け入れ条件**:
- main へのマージで自動デプロイされる
- PR では Lint と Test が走る
- パスベース変更検知で関係ある部分だけビルドが走る(AIZAP 方式)
- ロールバック手順がドキュメント化されている

**依存**:Cloud Run デプロイ

**Drop 判断**:このまま実装(DevOps テーマ要件)

---

### A-13. Terraform IaC

**説明**:全 GCP リソースを Terraform で管理。dev/prod 環境を分離。

**受け入れ条件**:
- `terraform apply` で全リソースを構築できる
- dev と prod で同じモジュールを使い、変数で差分を表現
- State はリモート(GCS)に保存
- README に手順が書かれている

**依存**:Cloud Run デプロイ

**Drop 判断**:このまま実装(DevOps テーマ要件)

---

### A-14. Migration Concierge Agent(Plan E、街診断 AI)

**説明**:ユーザーが自然言語で自己紹介(年代 / 関心軸 / 制約 / 家族構成)すると、1,795 自治体から TOP5 候補 + トレードオフ表 + 議論されている政策を返す対話型 Agent。本番実行体は `GenaiConciergeRunner`(function-calling 単一エージェント)。Plan C で築いた ADKTranslatorAgent / ADKRelevanceAgent を親子階層に組んだ構成は `demo_adk_chain.py` の別成果物として存在する。マルチエージェント必然性は Watcher の specialist crew と Pub/Sub パイプラインで示す。

**受け入れ条件**:
- `POST /v1/concierge` endpoint が稼働(Cloud Run)
- 4 tool が動作:`search_municipalities` / `compare_municipalities` / `fetch_city_dashboard` / `fetch_city_speeches`
- ADK Agent.sub_agents=[translator, relevance] 親子階層は `demo_adk_chain.py` に別途実装(本番 `/v1/concierge` は GenaiConciergeRunner を使用)
- google.genai 関数呼び出しで反復実行(max_iterations=5)
- 倫理ガード:`agents/_shared/forbidden.py` で 3 agent 共通の post-validation
- Frontend chat UI(`/concierge`):Markdown rendering + 候補 cards + tool_calls 折りたたみ
- 3 persona demo script(`agents/demo_concierge.py`):26 歳子育て / 介護 34 歳 / ワーママ 30 歳

**依存**:Plan C(ADK 化)、A-2(自治体マスタ)、A-3 統計データ、A-5 翻訳 / A-6 影響度

**Drop 判断**:このまま実装(バランス版 9 機能の主役、デモ動画の中核)

---

### A-22. Cost Anomaly Hunter Agent(Plan CC、最後の余裕枠 COULD)

**説明**:GCP リソース (BigQuery / Cloud Run / Firestore / Vertex AI 等) の日次 cost data から **異常スパイク検知 + 根本原因仮説 + 削減提案** を 2 段階 Agent で生成。Plan F (Scraper Doctor) と類似パターンの「運用負荷を Agent が肩代わり」演出 + cost ドメイン固有の **横断パターン認識** + **削減金額予測** で差別化。**自動 cost 削減 action は絶対実装しない**(PROJECT.md §5)。

**受け入れ条件**:
- `agents/cost_hunter/` 独立モジュール:`CostAnomalyDetector`(純計算、Plan Z forecast engine と一貫) + `CostRootCauseAgent`(LLM、Plan F と一貫)
- 異常分類 4 種:`spike` / `drift_up` / `drift_down` / `normal`(Reviewer Medium #5、slope 符号で drift 方向区別)
- 提案 action 5 種:`scale_down` / `optimize_query` / `investigate_logs` / `rate_limit` / `manual_review`
- **3 層構造的安全性**:
  1. `monthly_savings_estimate_jpy` schema `le=100_000` + server clamp(Reviewer Critical、LLM overshoot 二重防御)
  2. `requires_human_review=True` schema 強制(Plan F と一貫)
  3. `scale_down` + `vertex_ai`/`cloud_run` → 自動 `risky` 上書き(Reviewer High #3、ユーザー影響大誤提案防止)
- 倫理ガード:Plan PP / F と同じ `_detect_any_leak` を rationale + hypothesis に適用、leak 時 rule_based fallback
- `GET /v1/cost-health?days=30&limit_entries=20` endpoint
- Sample seed(`infra/seed/cost_observations_sample.json`、30 日 × 4 services = 120 観測点、`days_ago` 相対日付で将来腐敗回避(Reviewer Low #6))
- Plan F との差別化:**`detect_cross_service_pattern`**(同日複数 service spike で deploy 起因 rule-based 推定、Reviewer Medium #4)
- Frontend `/admin/costs` page:**常設 disclaimer**(自動削減なし)+ **簡易 admin ガード** + Suspense ラップ + StatsSummary(**¥ savings 表示**) + CrossServicePattern banner + AnomalyCard
- 34 unit/integration test、既存 366 + 34 = 400 passed
- 工数 10-12h 実績(余裕枠 18h 想定の圧縮版)

**依存**:Plan Z(純計算 engine パターン流用)、Plan F(2 段階 Agent + admin ガード + disclaimer)、Plan PP(`_detect_any_leak` 流用、3 層)

**Drop 判断**:このまま実装(余裕枠 COULD で完了、バランス版 11 機能の最後を埋める)

---

### A-21. Reasoning Transparency Agent(Plan PP、Meta-Reasoner)

**説明**:各 Agent (Concierge / Translator / Critic / Heatmap / Timeline / Forecast / Doctor の 7 種) の `reasoning` を **第三者観測者視点で再構成 + counterfactual 付与** する Meta-Agent。Reflexion (Shinn 2023) / Self-Refine (Madaan 2023) / Chain-of-Verification (Dhuliawala 2023) 系の文献的支持があり、内部ログをユーザー向け説明に変換する独立 Agent として機能する(単なる 2 回 LLM 呼び出しではない)。

**受け入れ条件**:
- `agents/reasoner/` 独立モジュール:`MetaReasoningAgent`(Plan X/Z/F と一貫した独立 Agent 構造)
- `AgentName` Literal で 7 種限定
- 出力:`plain_summary`(250-300 字)+ `influencing_factors[]`(3-5)+ `counterfactuals[]`(2-3)+ `caveats[]`(1-3)+ `confidence` + `source`
- **3 層倫理ガード**:
  1. 入力 leak 連鎖防止(`raw_reasoning` / `agent_output_summary` / `persona_context` 全てに `_detect_any_leak`、Reviewer High #1)
  2. 出力 leak 検出(`plain_summary` + 3 list 全要素に `_detect_any_leak`、Reviewer Medium #4)
  3. `AgentName` Pydantic Literal で 7 種限定
- LLM 失敗 / leak 時は agent 別 `_RULE_BASED_TEMPLATES`(7 種全カバー)で fallback
- `thinking_budget=512`(6 フィールド埋めるため forecast 256 から増、Reviewer Medium #5)
- `GET /v1/reasoning/explain` endpoint(cache なし、on-demand)
- Frontend `ReasoningExplainerButton`再利用可能 component(Forecast page の NarrativeBanner 下に挿入、次セッションで Concierge / Heatmap / Timeline / Doctor にも挿入予定)
- 22 unit/integration test、既存 344 + 22 = 366 passed
- 工数 6h 実績(1 日想定通り)

**依存**:Plan Z(`_detect_any_leak` 流用、47 県 + 主要市区 + 政治家/政党 3 層検出)、各既存 Agent の `reasoning` フィールド

**Drop 判断**:このまま実装(短期 1 日、文献根拠のある独立 Agent 構造)

---

### A-20. Self-healing Scraper Agent(Plan F、ハッカソン主役)

**説明**:スクレイパー失敗ログを 2 段階 Agent (`DiagnosticAgent` 8 種カテゴリ分類 + `RepairProposalAgent` 6 種 action 提案) で診断 + 修正提案。**自動 PR / commit は実装しない**(PROJECT.md §5 倫理境界、人間レビュー前提)。スクレイパー運用の主要機能の 1 つで、Citify の運用ストーリー(「Agent が運用負荷を肩代わり」)を体現。

**受け入れ条件**:
- `agents/scraper_doctor/` 独立モジュール:`DiagnosticAgent` + `RepairProposalAgent` + `FailureLogRepository` (Firestore) + `pii.py` (PII マスク)
- **4 層倫理ガード**:
  1. PII regex マスク (10 種、Reviewer Critical 予防):email / 電話 (固定 + 090/080/070) / 郵便番号 / IPv4 / Bearer token / Cookie / URL の api_key/token/secret
  2. 政治家・政党名 leak (Plan N の `POLITICAL_PERSON_PATTERNS` 流用)
  3. 47 県 + 主要市区町村名 43 件 leak (Plan Z の `_detect_geographic_leak` 流用、`PREFECTURE_NAMES_JA` + `MAJOR_MUNI_NAMES`)
  4. `requires_human_review=True` schema 強制(LLM が False を返してもサーバー側で True 上書き、Auto-PR 構造防止)
- `GET /v1/scraper-health?days=7&limit=50&use_sample=false` endpoint
- Firestore `scraper_failures` collection で失敗ログ保存(`html_snippet` / `stack_trace` は保存時に PII マスク再適用、`html_signature` (tag-only sha256[:16]) で重複排除)
- Sample seed (`infra/seed/scraper_failures_sample.json`、10 件)で Firestore 未投入時の graceful fallback、demo 用に実 error_type 反映(5 scraper × 2 件)
- Frontend `/admin/scrapers` page:**常設 disclaimer banner**(Reviewer High #1)+ **簡易 admin ガード**(Reviewer Medium、`NEXT_PUBLIC_ADMIN_TOKEN` env + URL token 比較、production では IAM 認証に置換)+ Suspense ラップ(Next.js 16 要件)+ StatsSummary + DropCandidates + FailureCard(Diagnostic + Repair + stack_trace + code_hint コピー)
- 60 unit/integration test、既存 284 + 60 = 344 passed
- 工数 22-24h 実績(4-5 日想定 24-30h を圧縮)

**依存**:Plan N(`POLITICAL_PERSON_PATTERNS` 流用)、Plan Z(`_detect_geographic_leak` + `MAJOR_MUNI_NAMES` 流用)、Firestore

**Drop 判断**:このまま実装(運用ストーリー演出に必須の主要機能)

---

### A-19. 議題件数トレンド予測 Agent(Plan Z、余裕枠 COULD)

**説明**:月別議題件数を Engine が純計算 (移動平均 + 線形回帰 + 標準誤差) で 3 か月予測、Narrator が「上昇/下降/横ばい/急騰/急減」5 分類 + 介入的説明を生成。Plan X (空間軸) と Plan N (イベント時系列) に続く「数値時系列予測」軸で、2 段階 Agent (Engine + Narrator) により数値計算と説明生成を分離した構造。

**受け入れ条件**:
- `agents/forecast/` 独立モジュール:`ForecastEngine` (純計算、numpy 等の依存なし) + `ForecastNarrator` (Gemini Flash)
- 信頼度 3 段階(`high`/`medium`/`low`):`history < 6`/`CV > 0.5`/`t 値 < 2.0` の階層判定(Reviewer High #2)
- LLM schema には `slope` / `trend` を含めず数値捏造を構造防止(Reviewer Medium #5)
- 3 層倫理ガード:47 都道府県名 + 主要市区町村名 (政令市 20 + 23 特別区) + 政治家/政党名(Reviewer High #1)
- `GET /v1/forecast?theme_interest=...&user_id=...&municipality_code=...&history_months=...` endpoint
- BQ query:`FORMAT_DATE("%Y-%m", meeting_date)` 月別集計、`meeting_date IS NOT NULL` + 集計行除外 + 10 軸 allowlist
- Frontend `/forecast` page:**disclaimer banner 常設**(行動推奨ではないと明示、Reviewer High #1)、自前 SVG ForecastChart(d3 等依存追加なし)、NarrativeBanner + TrendBadge 5 色分け
- 20 unit test + 7 endpoint test、既存 257 + 27 = 284 passed
- 工数 12-14h 実績(余裕枠 18h 想定の圧縮版)

**依存**:Plan A(scored_speeches_latest)、Plan N(`POLITICAL_PERSON_PATTERNS` 流用)、Plan X(`PREFECTURE_NAMES_JA` 流用)、独立 endpoint

**Drop 判断**:このまま実装(余裕枠 COULD で 1.5 日で完了、Plan N/X と並ぶ「数値時系列軸」のキラー機能)

---

### A-18. 議論タイムライン Agent(Plan N)

**説明**:ユーザーが選んだテーマ(interest 軸 + 自治体 or 全国 + 期間)について、議論変遷を時系列イベント 5-10 件 + 全体ナラティブとして Agent が物語化。Citify のキラー UX「議題が点ではなく流れで見える」を実現する。

**受け入れ条件**:
- `agents/timeline/` 独立 Agent (HeatmapAdvisor と同パターン、Concierge tool 再利用なし)
- Chain-of-Thought prompt:候補 30 件を時系列グルーピング → 5-10 マイルストーン抽出 → headline 40 字 + detail 80 字 + overall_summary 240 字
- LLM 失敗時 / 倫理 leak 検出時 / source_speech_id 捏造で 3 件未満時は rule_based fallback (raw 上位 5 speeches を date 順)
- 倫理ガード:`POLITICAL_PERSON_PATTERNS` (議員/首相/総理/大臣/知事/市長/氏 + 主要 10 政党) を Timeline 専用追加、`_ROLE_ONLY_PREFIXES` で「総理大臣」等の generic 役職名は除外。BQ SELECT から `speaker` 列除外で二重防御 (Reviewer Critical #1)
- LLM パラメータ:max_output_tokens=2048 / thinking_budget=512 (Reviewer Critical #2、token 見積もり明示)
- source_speech_id 捏造防止:candidate 集合外の event 削除、削除後 3 件未満なら fallback (Reviewer High #4)
- `GET /v1/timeline?theme_interest=...&user_id=...&municipality_code=...&days=...` endpoint
- BQ query:`@interest IN UNNEST(matched_interests)` + `municipality_code != '00000' AND NOT LIKE '%000'` + ScalarQueryParameter 化 + 10 軸 allowlist
- Frontend `/timeline` page:Interest selector + 自治体コード入力 + 期間 (30/90/365) 切替、NarrativeBanner + 縦タイムライン UI、event クリックで `/feed/[speech_id]` 遷移
- speech 詳細 (`/feed/[speech_id]`) に Plan N nav カードで「🕰 議論の流れを見る」を関連議題 (RAG) と並列配置 (Reviewer High #3 UI 動線差別化)
- 15 unit test + 8 endpoint test、既存 234 + 23 = 257 passed
- 工数 18h (3 日想定通り)

**依存**:Plan A(scored_speeches_latest)、Plan E と独立、Plan X HeatmapAdvisor と独立並列

**Drop 判断**:このまま実装(短期 3 日で完了、Citify のキラー UX を実現)

---

### A-17. 全国ヒートマップ Agent(Plan X)

**説明**:ペルソナ(年代/関心軸/自由記述)を踏まえて 47 都道府県を比較する「最も示唆的な統計指標」を `HeatmapAdvisor` Agent が自動選定し、タイルマップで Chloropleth 表示。タイルクリックで県内 TOP3 自治体を表示。Plan A の客観統計(Reinfolib + 国勢調査)を「全国規模」で活用する Agent。

**受け入れ条件**:
- `agents/heatmap_advisor/` 独立 Agent (DI / ADK 化と無関係、google.genai 直接 call)
- Chain-of-Thought prompt: ペルソナ要約 → 候補 3 つ → 最適 1 つ + 介入的説明 (200-300 字)
- LLM 失敗時 / 倫理 leak 検出時は `FALLBACK_METRIC_BY_INTEREST` (10 関心軸 × 9 指標) で graceful degrade、`source="rule_based"` で UI 区別可能
- 倫理ガード: reasoning に 47 都道府県名禁止、post-validation で leak 検出時は fallback、leaked 県名はユーザー向け文には含めず log のみ
- `GET /v1/heatmap?focus_interest=...&user_id=...` endpoint が 47 県中央値 + 県別 TOP3 (141 自治体) を返す
- **集計行 (XX000) と国会 (00000) を SQL で必ず除外** (Reviewer Critical #1、`NOT LIKE '%000'`)
- SQL injection 防止: `metric_column` を allowlist で検証 (9 指標のみ許可)
- Frontend `/heatmap` page: tile-grid 日本地図 (FT/Reuters 方式、TopoJSON 不要)、AdviceBanner で Agent reasoning + persona_summary 表示、タイルクリックで PrefectureModal が県内 TOP3 を表示
- HeatmapAdvisor 10 unit test + endpoint 7 test、既存 217 件と合わせて全 234 passed
- 工数 17-19h (3 日想定通り)

**依存**:Plan A(municipality_stats テーブル)、Phase F(Reinfolib データ充填)、Plan E と独立

**Drop 判断**:このまま実装(短期 3 日で完了、全国比較のキラー機能)

---

### A-16. Translator Self-Critique Loop(Plan D)

**説明**:翻訳結果を独立 Critic Agent が 4 軸 (faithfulness/simplicity/tone/ethics) で 0-100 点スコアリングし、threshold 未達なら 1 度自動 revise する Self-Critique ループ。翻訳品質を自己批評し、必要な場合のみ再翻訳を判断する独立 Agent 構造。デモ動画で「改善幅 (initial_score → final overall_score)」を可視化可能。

**受け入れ条件**:
- `agents/critic/` ディレクトリに `CriticAgent` クラス独立 (DI で Translator が受け取り、ADK 化への布石)
- `CriticScores` Pydantic schema が 4 軸各 0-100 (`ge=0, le=100`) 強制
- `TranslatorAgent.translate_with_critique(input, critic, threshold=70)` メソッドが (draft → critic → revise → re-critique) の 1-round loop を実行
- `overall_score = round((4 軸平均))`、ただし `ETHICS_HARD_FLOOR=60` で ethics<60 は強制 revise (倫理は他軸で薄めない)
- `revision_count` 0/1、`initial_score` で revise 前スコアを保持 (改善幅 demo 用)
- empty draft (`notes` が `empty_reason:` で始まる) は critique skip + revise skip
- 既存 `TranslatorAgent.translate()` は完全不変 (backward compat)
- **本番 worker への配線 (2026-07-02 追加)**: `CITIFY_ENABLE_CRITIQUE=1` 環境変数で translator worker が critique loop を使用 (**既定 OFF** = 本番挙動不変。Pub/Sub payload 形状も不変で `.translation` を unwrap)。デモ・検証時のみ有効化する運用
- 17 unit test 追加 (critic 9 + self_critique integration 8) + worker 配線 test 追加、translator 系 47 passed

**依存**:Plan C(ADK wrapper)、`agents/_shared/forbidden.py`(倫理ガード regex)

**Drop 判断**:このまま実装(短期 1 日で完了、Plan E の Concierge 内部品質も将来補強可能)

---

### A-15. Concierge 会話履歴 + Story Recall(Plan L+LL)

**説明**:Concierge との対話を Firestore に永続化し、過去の関心軸を踏まえた「Story Recall」体験を提供。再訪時に「前回は子育て・住居の話をしました。今回は ○○ ですね」のような連続性を演出する。

**受け入れ条件**:
- Firestore `concierge_history` collection(1 turn = 1 doc)に保存(user_id / timestamp / message / reply / short_summary / candidates_codes / matched_interests / embedding[768])
- Vertex AI `text-multilingual-embedding-002` で embedding 計算、in-memory cosine similarity で類似検索(scan limit 50 turn)
- `matched_interests` は rule-based 固定辞書で抽出(LLM call なし、save 高速化)
- `GET /v1/concierge/history/{user_id}`(x-user-id header 認可、403 on mismatch)
- ConciergeAgent は倫理 OK の時のみ fire-and-forget で `save_turn()` 呼び出し、save 失敗はユーザー応答に影響しない(graceful)
- 25 unit test + 5 endpoint test、全 200 件 pass

**依存**:Plan E(A-14、Concierge endpoint)、Firestore、Vertex AI Embedding

**Drop 判断**:このまま実装(Plan E の必須拡張。Frontend history modal は Phase 4 として後続)

---

## B. 差別化機能(Should)

### B-1. 「気になる / 関係なさそう」リアクション + 「みんなの反応」

**説明**:議題に対する 2 択リアクション。集計値をマイクロインタラクションとして可視化(「あなたの世代の 65% が気になると回答」)。

**受け入れ条件**:
- ボタンタップで Firestore にイベント記録
- 集計値は議題ごとに年代別バケットで集計
- 個人は識別不能(集計のみ表示)
- 集計値は 1 時間ごとに更新

**依存**:議題詳細ビュー(A-9)

**Drop 判断**:Week 4 終了時点で未着手なら Should から Could に降格

---

### B-2. 比較ビュー(複数自治体)

**説明**:選択した 2〜3 自治体の同一テーマ議題を横並びで表示。「あなたの街 vs 隣の街」自動レコメンド機能も。

**受け入れ条件**:
- マイ自治体から 2 つ選んで「比較」ボタンを押せる
- 同テーマ(児童手当、起業支援等)について両自治体の状況を並べて表示
- 差分(独自制度、補助額等)が強調表示される
- 自治体 HP では絶対に提供できない体験

**依存**:議事録 RAG、分類 Agent

**Drop 判断**:Week 5 中盤までに着手できなければ降格。ただしこの機能は Citify のキラー体験なので、優先順位は最も高く維持

---

### B-3. 【未実装・スコープ外】Veo 60 秒解説動画

> 実装では Veo は使用していない(スコープ外、将来候補として仕様のみ残す)。

**説明**:議題の概念を抽象シーンで説明する 60 秒縦動画を Veo で生成。政治家の顔は描かない、SynthID + AI 生成ラベル必須。

**受け入れ条件**:
- 議題 1 つに対して 60 秒の縦動画(9:16 比率)を生成
- 動画内容は政策の概念図、街並み、家族、自然等の抽象シーン
- 必ず「AI が説明用に作成した動画です」ラベルを表示
- 動画は Cloud Storage に保存、CDN で配信
- 生成コストを抑えるため、フィード上位の議題のみ生成(優先度フィルタ)

**依存**:Imagen 連携、Cloud Storage

**Drop 判断**:Veo の品質安定が Week 4 までに出ない場合、静止画 + テキストに代替

---

### B-4. Imagen サムネ生成

**説明**:議題ごとに Imagen 3 でフィード用サムネ画像を生成。**実装では関心軸ごとの Imagen 生成サムネ10種を全国で再利用する方式(議題ごとの生成ではない)**。

**受け入れ条件**:
- 1 議題に対して 1 枚のサムネ(横長 16:9 または正方形 1:1)
- 抽象的・象徴的なビジュアル(政治家描写は禁止)
- フィードカードに表示される
- 生成済み画像はキャッシュ

**依存**:Cloud Storage

**Drop 判断**:Week 4 中盤までに動作確認できなければ、ストック画像ライブラリで代替

---

### B-5. 通知(メール / Push)

**説明**:週次の「今週のあなたの街」配信。初期はメール、可能なら Web Push。

**受け入れ条件**:
- ユーザーが通知 ON を選択している場合のみ送信
- メール本文には上位 3 議題のサマリと Citify アプリへのリンク
- 配信時刻は固定(月曜 9 時)、将来的に学習機能で個別化可能なアーキテクチャ

**依存**:配信 Agent、SendGrid or Cloud Tasks + SES など

**Drop 判断**:メール送信基盤の構築が Week 6 までにできなければ、アプリ内通知のみに縮小

---

### B-6. 議事録パーサー 2: DB-Search — **DROPPED (2026-05-25)**

**説明**:大和速記情報センターの DB-Search を採用している 150+自治体に対応するパーサー。

**Drop 理由 (2026-05-25 recon)**:対象 4 区 (千代田・文京・江東・品川) すべての `*.dbsr.jp` 系 robots.txt が以下の通り、議事録パスを全面 Disallow:
```
User-agent: *
Disallow: /
Allow: /$
Allow: /index.php$
Allow: /index.php/$
```
許可されているのはルートと `/index.php` (末尾 `$` アンカー) のみ。議事録本文ページ (`/searchByYear/...`, `/minute/...` 等) は全て Disallow 対象。PROJECT.md §5「スクレイピング先の robots.txt と利用規約を必ず尊重」に抵触するため Drop。

**代替カバレッジ**:kaigiroku.net (DiscussNet) で 350+ 自治体カバー済 + 国会 API + voices_asp (限定) で MVP スコープには十分。

**受け入れ条件** (Drop 前):
- DB-Search の URL パターンを解析できる
- 議事録を構造化して BigQuery に保存
- 既存の DiscussNetPremium パーサーと同じスキーマで保存

**依存**:議事録 RAG、自治体マスタ

---

### B-7. 自治体プレスリリース RSS 収集

**説明**:都道府県 47 + 政令市 + 中核市 約 130 自治体のプレスリリース RSS を取得。

**受け入れ条件**:
- RSS URL を自治体マスタに保持
- 日次でクロール
- BigQuery に保存(タイトル、本文、URL、公開日)
- 議事録より高頻度の素材として For You フィードに混在表示

**依存**:自治体マスタ

**Drop 判断**:Week 5 終わりまでに最低 47 都道府県分が動かなければ Could に降格

---

### B-8. ペルソナ別プリセット

**説明**:「新社会人」「U ターン検討」「移住検討」など、複数のペルソナで関心軸セットを切り替えられる。

**受け入れ条件**:
- 設定画面でペルソナを選択
- 選択により関心軸のデフォルトが切り替わる
- 個別の関心軸調整も可能

**依存**:オンボーディング(A-1)

**Drop 判断**:Week 6 までに着手できなければ Could に降格

---

## C. 拡張機能(Could)

### C-1. ストック静止画ライブラリ

**説明**:Veo が間に合わない場合のバックアップ。Imagen で事前生成した汎用サムネ集。

**Drop 判断**:Veo が動けば実装不要

---

### C-2. 議事録パーサー 3: Sophia / DNP

**説明**:残りの主要議事録システム対応。

**Drop 判断**:Week 6 終わりまでに着手できなければ諦める

---

### C-3. e-Gov パブコメ取得

**説明**:現在募集中のパブコメ案件を取得し、関連議題として表示。

**Drop 判断**:Week 6 終わりまでに着手できなければ諦める

---

### C-4. 自治体オープンデータポータル統合

**説明**:推奨データセット準拠自治体のオープンデータを取得し、議題の裏付けに使う。

**Drop 判断**:Week 6 終わりまでに着手できなければ諦める

---

### C-5. 政府審議会議事録収集

**説明**:こども家庭庁、厚労省、文科省などの審議会議事録を取得。会期外の素材として。

**Drop judgment**:Week 6 終わりまでに着手できなければ諦める

---

### C-6. 自治体公報 PDF パース

**説明**:Document AI で自治体公報 PDF を構造化。

**Drop 判断**:Week 6 終わりまでに着手できなければ諦める

---

### C-7. SNS シェア用カード生成

**説明**:議題を SNS でシェアする際の OGP 画像を Imagen で生成。

**Drop 判断**:Could から動かない可能性大

---

### C-8. 検索機能

**説明**:議事録全文検索。

**Drop 判断**:Could から動かない可能性大

---

### C-9. お気に入り保存・閲覧履歴

**説明**:議題のお気に入り保存と閲覧履歴の管理。

**Drop 判断**:Could から動かない可能性大

---

## D. 今回は実装しない(Won't)

明確に範囲外。ピッチでは「拡張可能性」として説明:

- 議員 / 役所への質問テンプレ自動生成
- 「あなたの体験を言葉にする」アシスタント(パブコメ意見書ドラフト)
- 政府審議会全網羅
- e-Stat 統計の本格統合
- 履歴・アクティビティ分析
- ユーザー間のコメント・チャット
- 多言語対応
- iOS/Android ネイティブアプリ

---

## 機能依存関係の早見表

```
A-1 (オンボーディング)
  └── A-2 (自治体マスタ)
        └── A-3 (国会 API)
              └── A-10 (RAG)
                    └── A-5 (翻訳 Agent)
                          └── A-6 (影響度 Agent)
                                └── A-7 (配信 Agent)
                                      └── A-8 (For You フィード)
                                            └── A-9 (議題詳細)
                                                  ├── B-1 (リアクション)
                                                  ├── B-3 (Veo 動画)
                                                  └── B-4 (Imagen サムネ)
        └── A-4 (DiscussNetPremium パーサー)
        └── B-7 (プレス RSS)
        └── B-2 (比較ビュー) [複数自治体 + RAG 依存]

A-11 (デプロイ) ↔ A-12 (CI/CD) ↔ A-13 (Terraform)
  └── これら 3 つは並行で着手し、A-1 着手前に完了させる
```

最も依存が深いのは A-9(議題詳細)。これに辿り着くまでに 7 つの依存を満たす必要がある。スケジュール上、最優先で Week 1-3 で依存解消する。
