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

- 新規ページ `/plan`。入口は `/agent` の verdict 直下 CTA「📋 移住アクションプランを作る →」。BottomNav は増やさない（エージェントの出口として配置）。
- フロー: onboarding → 候補登録 → /agent で分析 → verdict 出現 → /plan（1枚に集約）→ 印刷/共有。
- 分析が無い場合: 空状態で「まず分析しましょう →」と /agent へ誘導（行き止まりを作らない）。

## 2. バックエンド

新エンドポイント `GET /v1/watcher/{uid}/plan`（認可は既存と同じ `x-user-id`）。

処理:
1. `repo.get_latest_analysis(uid)` で最新 `TownAnalysis` を取得。無ければ `{plan: null}`。
2. `recommended_code = verdict.recommended_code`（無ければ最高 fit_score、住む街のみなら「住み続ける妥当性」プラン）。
3. **再利用（生成なし）**: decision_summary←`verdict.headline` / reasons←推し街 assessment の strengths＋`verdict.reasoning` / open_questions←分析の open_questions。
4. **唯一の新規生成**: 現地訪問チェックリストを軽量 single-agent（JSONモード）1回で生成。入力＝推し街の strengths/concerns/population_outlook 等。**run_id でキャッシュ**。
5. **公式リンク**: LLM 不使用で構成（データ論点参照）。
6. **倫理スキャン**: 生成チェックリストに `find_forbidden_matches`。

スキーマ `ActionPlan`（pydantic＋zod 同型）:
```
recommended_code / recommended_name / role(home|candidate)
decision_summary: str
reasons: list[str]
open_questions: list[str]
visit_checklist: list[str]      # 生成
official_links: list[{label, url}]
run_id / generated_at
```

配置: `agents/watcher/action_plan.py`（純関数の組み立て＝テスト対象＋ `generate_visit_checklist` は ADK 呼び出しでモック）。Watcher 本体・日次Job は変更なし（プランは閲覧時のみ生成）。

### データ論点: 公式リンク
自治体の公式移住窓口URLは未保有。MVP は中立な**構成リンク**（「〇〇市 移住 相談窓口」検索 or 都道府県移住ポータル）で代替し、"検索への入口"として正直に提示。将来 seed で公式URLを追加できる設計にする。

## 3. フロント `/plan`

既存ページと同じ作法（`max-w-2xl`・モバイルファースト・client component・独立 fetch）。

状態: ロード中（スケルトン）／空（分析なし→/agent 誘導）／表示。

レイアウト（1枚・上から）:
1. ヘッダー「📋 移住アクションプラン」＋生成日時
2. 結論ヒーロー: `recommended_name`＋バッジ＋`decision_summary`（emerald 強調）
3. 決め手（なぜこの街か）: `reasons[]`
4. 残る確認事項: `open_questions[]` をチェックボックス（local state）
5. 現地訪問チェックリスト: `visit_checklist[]` をチェックボックス
6. 公式の相談窓口: `official_links[]`（別タブ・`rel=noopener`）
7. 家族と共有: 「🖨 印刷」（print用CSSでnav非表示）＋「📋 テキストでコピー」（プラン全文を平文化）
8. 倫理注記「中立な検討材料です。最終判断はご自身の価値観で」

こだわり:
- チェックは**未保存**（持ち帰り用、家族と潰す体験）。チェック状態は印刷/コピー文面に反映。
- コピー文面は「結論／決め手／確認事項／チェックリスト／窓口リンク」を整形した平文（LINE等で家族にそのまま貼れる）。

api.ts: `ActionPlanSchema`（zod）＋ `fetchActionPlan(userId)`。

## 4. 倫理・エッジ・テスト

倫理:
- 中立な検討材料に徹する。生成チェックリストはサーバ側 `find_forbidden_matches`（処方・投票推奨・政治家名等を除去）。
- 公式リンクは中立な検索/移住ポータルのみ（不動産業者・政治的主体へ誘導しない）。
- decision_summary/reasons は Watcher 由来＝apply_ethics 通過済み。UIに免責明記。

エッジケース:
- 分析なし → 空状態CTA。
- `recommended_code == home` → 「住み続ける妥当性」プランに文言切替。
- recommended 未設定 → 最高 fit_score 採用、無ければ空状態。
- チェックリスト生成失敗 → graceful（該当セクション非表示、他は表示）。
- plan 取得失敗 → 注記（既存 SectionLoadError パターン）。

テスト:
- backend 純関数: `assemble_action_plan` の推し街選定・reasons・open_questions・role 判定／`construct_official_links` のURL生成／倫理スキャン適用（`generate_visit_checklist` モック）。
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
