# 移住支援金マッチング 設計 (Relocation Support Matching)

- 作成日: 2026-06-09
- ステータス: 設計確定（実装前）
- 目的: 移住者の最重要ニーズ「お金」を埋める。persona から国の移住支援金の対象可能性・概算額を判定し、自治体独自支援を抽出して提示。アクションプラン(⑥行動)の"決め手"を本物にする。

## 位置づけ（重要・アドバイザー型）

Citify は「移住を**決断させる**ツール」ではなく「**街の状況と"あなたにとっての意味"を教えてくれるアドバイザー**」。支援金も「だから移住しろ」でなく「**あなたの状況だと、この街ではこういう支援が受けられます（公式で確認を）**」と**教える**情報として提示する。PROJECT.md の倫理（処方・断定をしない／事実と論点に留める）と一致。listings 競争には参加せず、上流の"判断材料を最も上手く整理する存在"に徹する。

## 全体像

出口 `/plan`（アクションプラン）に新セクション「💰 受けられる可能性のある支援金」。2層:
1. **国の移住支援金 = ルール判定（決定的・正確）** — 既存 persona で評価。
2. **自治体独自支援 = LLM抽出（agentic・google_search グラウンディング）** — 概算＋公式リンク、金額は断定しない。

## 1. 国の移住支援金（決定的・seed＋純関数）

- **参加自治体 seed**: `agents/watcher/data/relocation_support.csv`（`municipality_code, participates, official_url, note`）。国の対象自治体は公的に一覧公開(1300超)→入手分を一括seedし「多数カバー」を担保。完全入手はデータ作業（公開CSV/県別から収集）。ルールは任意の seed コードで動く。
- **東京圏判定（現住所＝persona.home）**: 23区(`131xx`)=対象者可能性高 / 東京圏(11/12/13/14)=「23区へ通勤なら対象」conditional / それ以外=対象外可能性。
- **対象先**: 推し街(recommended_code)が seed participates=true なら対象地域。
- **概算額**: 単身60万 / 世帯100万 ＋「子1人あたり最大100万加算」（子数未取得→上限表現）。要件（対象求人就業/テレワーク継続/起業）を条件付きで併記。
- **純関数** `match_national_support(home_code, recommended_code, household, seed) -> NationalSupport`（テスト容易・LLM不要・高速）。

## 2. 自治体独自支援（agentic・LLM抽出）

- **google_search グラウンディングを新規追加**（Vertex 検索ツール）。`extract_local_support(municipality_name) -> list[{name, summary, official_url, source_url}]`。
- **金額は断定しない**。信頼部分＝制度の存在＋公式リンク＋出典。額は「概算・公式で要確認」。
- on-demand（/plan 閲覧時）＋ code でキャッシュ。失敗時は空（graceful）。倫理スキャン(find_forbidden_matches)を抽出結果に適用。

## スキーマ（ActionPlan に追加）

```
support:
  national: { eligibility: "likely"|"conditional"|"unlikely",
              amount_man: int|null, requirements: str, official_url: str, note: str }
  local: [ { name, summary, official_url } ]
```

## 倫理・エッジ・テスト

倫理: 金額・該当を断定しない（国制度=「対象の可能性」、独自=「概算・公式で要確認」）。公式リンク必須・出典明示。中立（処方/投票推奨なし、forbidden スキャン適用）。アドバイザーとして"教える"トーン。

エッジ: 東京圏外/非参加→「対象外の可能性」と正直表示（独自分は表示）。子数未取得→上限表現。就業要件→条件付き。独自抽出空/失敗→非表示 or 公式リンクのみ。home 未設定→「現住所により判定」と注記。

テスト: `match_national_support`（23区×参加×世帯→100万＋子加算/単身→60万、東京圏→conditional、東京圏外→unlikely、非参加先→対象外）／seedローダ／`extract_local_support` の parse＋倫理＋出典（LLMモック）／API smoke（/plan に support、空時graceful）／tsc・build。

検証ゲート: ruff・pytest(agents+api)・tsc・next build。

## フェーズ

- **P1**: 国制度（seed＋`match_national_support`＋ActionPlan.support.national＋/plan表示）＝決定的・確実・即価値。
- **P2**: 自治体独自（google_search グラウンディング＋extract_local_support＋ActionPlan.support.local＋/plan表示）＝agentic 上積み。

## デプロイ留意

google_search グラウンディングは Vertex 権限要確認。`agents/**`+`apps/api/**` で API 自動再デプロイ。seed CSV は agents 配下（relocation_links と同様イメージ同梱）。BQ 変更なし。

## スコープ外

- 仕事/求人・賃貸listings（上流アドバイザーに徹する方針。外部API依存で見送り）
- 全参加自治体リストの完全網羅（入手分をseed、段階拡張）
- 子の人数の厳密入力（上限表現で代替）
