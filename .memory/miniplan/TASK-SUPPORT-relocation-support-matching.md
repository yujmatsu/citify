# ミニプラン: 移住支援金マッチング (Relocation Support Matching)

## 概要
- **タスクID**: TASK-SUPPORT
- **目的**: 移住者の最重要ニーズ「お金」を埋める。国の移住支援金の対象可能性・概算額を persona から判定し、自治体独自支援を抽出してアクションプランに提示。アドバイザーとして"教える"(決断させない)。
- **設計**: [docs/plans/2026-06-09-relocation-support-matching-design.md](../../docs/plans/2026-06-09-relocation-support-matching-design.md)
- **位置づけ**: 街の状況と"あなたにとっての意味"を教えるアドバイザー。金額・該当は断定せず公式リンクへ。
- **完了条件**:
  1. `match_national_support` が home(get_watchlist由来)/recommended(分析由来)/household＋seed から対象可能性・概算額・要件を返す（全参加リストの完全網羅は別タスク、ルールは任意seedで動く）
  2. `extract_local_support` が google_search グラウンディングで自治体独自支援(制度名/概要/公式/出典)を抽出(金額断定なし・倫理スキャン)
  3. `/plan` に「💰 受けられる可能性のある支援金」が表示(国制度＋独自、空時graceful)
  4. 断定回避・公式リンク・要確認・出典 を必ず表記
  5. ruff・pytest(agents+api)・tsc・next build がすべて green

## 作業ステップ

### P1: 国制度(決定的・確実)
1. [ ] `agents/watcher/data/relocation_support.csv`: 国の参加自治体を seed(入手分を一括。municipality_code, participates, official_url, note)
2. [ ] `agents/watcher/support.py`(or action_plan.py内): `match_national_support(home_code, recommended_code, household, seed)` 純関数。東京圏判定(23区=131xx/東京圏11-14/それ以外)＋参加判定＋概算額(単身60/世帯100＋子加算上限)＋要件文＋eligibility(likely/conditional/unlikely)
3. [ ] `ActionPlan` schema に `support.national` 追加(pydantic＋zod)
4. [ ] `/plan` endpoint で **`repo.get_watchlist(user_id)`(WatchInput=home/household保持)から現住所・世帯を取得**し `match_national_support` に渡して national を算出・付与（レビュー#1）。watchlist 未登録時は home 未設定扱い→「現住所により判定」注記。※`get_latest_analysis`(TownAnalysis)は home/household を持たないため必須
5. [ ] `/plan` ページに「💰 支援金」セクション(国制度: 対象可能性・概算・要件・公式リンク。断定回避表記)

### P2: 自治体独自(agentic・LLM抽出)
6. [ ] google_search グラウンディング可否を Vertex で確認(不可なら議事録RAG/公式リンクのみにフォールバック)
7. [ ] `extract_local_support(name)` 軽量エージェント(グラウンディング)＋parse＋倫理スキャン＋出典付与＋キャッシュ
8. [ ] `ActionPlan.support.local` 追加＋/plan endpoint で付与(on-demand)
9. [ ] `/plan` に独自支援リスト表示(概算・公式リンク・出典)

### 検証
10. [ ] tests(`match_national_support` 各分岐/seedローダ/extract parse＋倫理、LLMモック/API smoke/コピー)＋ruff/pytest/tsc/build → コミット案提示

## 成果物
- [ ] P1: seed CSV＋`match_national_support`＋schema＋endpoint＋/plan表示
- [ ] P2: `extract_local_support`(グラウンディング)＋schema＋endpoint＋/plan表示
- [ ] tests＋検証ログ(全green)＋コミット/デプロイ手順

## 留意
- 倫理最優先: 金額・該当を断定しない/公式リンク・出典必須/中立(forbiddenスキャン)
- 既存 persona(home/household/recommended) を再利用(前回の前提整理が効く)
- BQ変更なし。seed は agents 配下でイメージ同梱。google_search は Vertex 権限要確認
- フェーズ毎に green を保ち、P1(決定的)だけでも一貫した価値が残る
