# 移住アクションプラン 設計 (Relocation Action Plan)

- 作成日: 2026-06-08
- ステータス: 設計確定（実装前）
- 目的: 移住ジャーニーの出口（⑤決断→⑥行動）の穴を埋め、カルテ/Watcher/コンシェルジュの分析を「持ち帰れる1枚の行動プラン」に収束させる。Citify だけで移住判断が**完結**する体感を作る。

## 背景（なぜ作るか）

第三者・専門家視点のジャーニー分析で、現状は②探す/③知る/④見守るは厚いが、**①前提整理・⑤決断・⑥行動・⑦定着が穴**と判明。特に⑥「行動」が完全欠落で、エージェントが結論を出した瞬間にジャーニーが行き止まる。本機能は最重要の穴（⑤⑥）を最小コストで埋める。

## 決定事項（brainstorming で確定）

| 論点 | 決定 |
|---|---|
| プランの核 | **意思決定サマリー中心**（最有力候補1つの結論を1枚に集約） |
| 含める行動要素 | 残る決め手(open_questions)／自治体公式リンク／現地訪問チェックリスト／家族共有 の4つ全て |
| 生成アーキテクチャ | **案A: Watcher 出力の再利用＋軽量生成**（結論は生成せず、チェックリストのみ新規生成） |

設計原則: **4つ目の結論を作らない**。Watcher の verdict/town_assessments/open_questions を再利用し、アクションプランを「マイ街エージェントの自然な出口」に位置づける（前回整理した"結論の分散"を再発させない）。

## 1. 体験とフロー

**役割の差別化（レビュー#1）**: `/agent`＝**分析（結論を出す）**、`/plan`＝**行動の段取り（次にやることを示す）**。両画面の冒頭に役割を一文で明示し、/plan は結論の再掲ではなく「**で、次にやること**」を主役にする。これにより「/agentの焼き直し」に見えるリスクを排す。

- 新規ページ `/plan`。入口は `/agent` の verdict 直下 CTA「📋 移住アクションプランを作る →」。BottomNav は増やさない（エージェントの出口として配置）。
- フロー: onboarding → 候補登録 → /agent で分析 → verdict 出現 → /plan（1枚に集約）→ 印刷/共有。
- 分析が無い場合（レビュー#6）: 空状態から**ワンタップで分析を実行し、完了後そのまま /plan を表示**（「まず分析」の2ステップを1アクションに圧縮。実行は既存 `POST /run` を叩いてからプラン取得）。

## 2. バックエンド

新エンドポイント `GET /v1/watcher/{uid}/plan`（認可は既存と同じ `x-user-id`）。

処理:
1. `repo.get_latest_analysis(uid)` で最新 `TownAnalysis` を取得。無ければ `{plan: null}`。
2. `recommended_code = verdict.recommended_code`（無ければ最高 fit_score）。
3. **モード分岐（レビュー#3）**:
   - `recommended_code != home` → **移住モード**（候補へ移る前提）。
   - `recommended_code == home` → **据え置きモード**: 文言・行動要素を切替。decision_summary=「今の街に住み続けるのが妥当」、行動＝「**今の街で見直す条件**（何が起きたら再検討するか）＋**今の街の活用余地**（未利用の支援/施設）」。移住相談窓口は**非表示**、訪問チェックリストは「自分の街を"移住者目線"で再点検」に置換。これにより home verdict で設計が破綻しない。
4. **再利用（生成なし）**: decision_summary←`verdict.headline` / reasons←推し街 assessment の strengths＋`verdict.reasoning` / open_questions←分析の open_questions。
5. **唯一の新規生成**: 現地訪問チェックリストを軽量 single-agent（JSONモード）1回で生成。**街固有性を担保（レビュー#4）**＝プロンプトに具体数値を投入（昼夜間人口比→通勤帯の混雑を見る、高齢化率→医療アクセス、人口減→学校統廃合リスク等）。汎用項目（"家賃を確認"）でなく"その街でしか出ない確認項目"を要求。**run_id でキャッシュ**。
6. **公式リンク**: LLM 不使用で構成（データ論点参照）。据え置きモードでは非表示。
7. **倫理スキャン**: 生成チェックリストに `find_forbidden_matches`。

スキーマ `ActionPlan`（pydantic＋zod 同型）:
```
mode: "relocate" | "stay"        # 据え置きモード分岐 (レビュー#3)
recommended_code / recommended_name / role(home|candidate)
decision_summary: str
reasons: list[str]
open_questions: list[str]
visit_checklist: list[str]      # 生成 (mode で文言/観点が変わる)
official_links: list[{label, url}]   # stay モードは空
run_id / generated_at
```

配置: `agents/watcher/action_plan.py`（純関数の組み立て＝テスト対象＋ `generate_visit_checklist` は ADK 呼び出しでモック）。Watcher 本体・日次Job は変更なし（プランは閲覧時のみ生成）。

### データ論点: 公式リンク（レビュー#2 反映）
Google 検索リンクは"自分で調べて"に見え完結感を削ぐため不採用。代わりに2層で信頼性を担保:
1. **信頼ポータルへ構成リンク**（全件）: 全国移住ナビ（JOIN／ニッポン移住・交流ナビ）等の公的ポータルへ、都道府県/市区町村名クエリで誘導。「行政系ポータルの入口」として中立かつ信頼できる。
2. **少数 seed の公式URL**（デモ対象の主要市）: `infra/seed/relocation_links.csv`（municipality_code, official_relocation_url, label）に**数十市だけ公式移住窓口URLをキュレーション**。`construct_official_links` は seed があればそれを優先、無ければ信頼ポータルにフォールバック。
- seed は git 管理の小さな CSV。将来全自治体へ拡張できる。BQ 投入は不要（API 起動時にロード or 直接読み）。
- 倫理: 不動産業者・政治的主体へは誘導しない（行政系ポータル/公式窓口のみ）。

## 3. フロント `/plan`

既存ページと同じ作法（`max-w-2xl`・モバイルファースト・client component・独立 fetch）。

状態: ロード中（スケルトン）／空（分析なし→/agent 誘導）／表示。

レイアウト（1枚・上から）。**行動を主役に（レビュー#1）**：結論は簡潔に置き、画面の主役は「次にやること」:
1. ヘッダー「📋 移住アクションプラン」＋役割一文（「分析の結論を"次の行動"に変える画面です」）＋生成日時
2. 結論ストリップ（**コンパクト**）: `recommended_name`＋バッジ＋`decision_summary` 1行（/agent の再掲なので大きくしない）
3. **次にやること（3ステップ）**＝この画面の主役: ①残る確認を潰す ②現地を見る ③窓口に相談 — 各ステップが下の該当セクションへアンカー
4. 決め手（なぜこの街か）: `reasons[]`（折りたたみ可、結論の根拠なので副次）
5. 残る確認事項: `open_questions[]` をチェックボックス
6. 現地訪問チェックリスト: `visit_checklist[]` をチェックボックス
7. 公式の相談窓口: `official_links[]`（別タブ・`rel=noopener`）
8. 家族と共有: 「🖨 印刷」（print用CSSでnav非表示）＋「📋 テキストでコピー」（プラン全文を平文化）
9. 倫理注記「中立な検討材料です。最終判断はご自身の価値観で」

こだわり:
- チェック状態は **localStorage に保持**（key=`plan:{user_id}:{run_id}`、レビュー#5）。"未保存DB"だが端末では残り、家族と相談中のリロードで消えない。印刷/コピー文面に反映。
- **到達フィードバック（レビュー#8）**: 確認事項＋チェックリストを全て潰すと「✅ 確認が揃いました。あとは現地で確かめましょう」を表示し決断を後押し。
- コピー文面は「結論／次の3ステップ／確認事項／チェックリスト／窓口リンク」を整形した平文（LINE等で家族にそのまま貼れる）。

api.ts: `ActionPlanSchema`（zod）＋ `fetchActionPlan(userId)`。

## 4. 倫理・エッジ・テスト

倫理:
- 中立な検討材料に徹する。生成チェックリストはサーバ側 `find_forbidden_matches`（処方・投票推奨・政治家名等を除去）。
- 公式リンクは中立な検索/移住ポータルのみ（不動産業者・政治的主体へ誘導しない）。
- decision_summary/reasons は Watcher 由来＝apply_ethics 通過済み。UIに免責明記。

エッジケース:
- 分析なし → 空状態からワンタップ分析（#6）。
- `recommended_code == home` → **据え置きモード**（§2 step3、移住相談窓口非表示・訪問→自街再点検）。
- recommended 未設定 → 最高 fit_score 採用、無ければ空状態。
- チェックリスト生成失敗 → graceful（該当セクション非表示、他は表示）。
- plan 取得失敗 → 注記（既存 SectionLoadError パターン）。

テスト:
- backend 純関数: `assemble_action_plan` の推し街選定・**mode判定（home→stay / candidate→relocate）**・reasons・open_questions・role／`construct_official_links` の**seed優先→信頼ポータルfallback**／stayモードでlinks空・窓口非表示／倫理スキャン適用（`generate_visit_checklist` モック）。
- API smoke: 200（分析あり）・空（分析なし）。
- frontend: tsc / next build（＋コピー文面整形の純関数を軽くテスト）。

検証ゲート: ruff・pytest(agents+api)・tsc・next build。

## デプロイ

- `agents/**`・`apps/api/**` 変更 → API 自動再デプロイ。BQ 変更なし（terraform/load 不要）。
- 日次Job(workers)は本機能を呼ばない（閲覧時のみ）ので再ビルド不要。

## スコープ外（今回やらない / バックログ）

- 支援金・補助制度マッチング（専用データ調達が要・別タスク）
- 優先順位の重み付け onboarding（①前提整理、別タスク Should）
- マイ移住プロジェクトの背骨統合（別タスク Should）
- 共有リンク（URL）での外部共有（印刷/コピーで代替、Could）

## レビュー反映履歴 (2026-06-08)

第三者・専門家レビュー＋審査基準チェックを受けて以下を反映:

| 項目 | 反映内容 |
|---|---|
| #1 役割の差別化（高） | /agent=分析・/plan=行動と役割を明示。/plan は結論を簡潔化し「次にやること（3ステップ）」を主役に |
| #2 公式リンク信頼性（高） | Google検索を廃し、信頼ポータル誘導＋少数 seed（`infra/seed/relocation_links.csv`）の2層に |
| #3 home推奨モード（高） | 据え置きモードを新設（文言/行動切替・窓口非表示）。スキーマに `mode` 追加 |
| #4 街固有チェックリスト（中） | 生成プロンプトに具体数値を投入し汎用化を防止 |
| #5 チェック保持（中） | localStorage 保持（リロードで消えない） |
| #6 空状態1ステップ（中） | 空状態からワンタップ分析→プラン表示 |
| #8 到達フィードバック（低） | 全チェック完了で「確認が揃いました」 |

**審査基準アライン**: 本機能は最弱だった **②課題アプローチ・④実用性** を直接補強。①は"分析→行動の一気通貫"として位置づけ毀損を回避。④は #2/#4 の品質が生命線（薄いと逆効果）。

