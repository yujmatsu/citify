# ProtoPedia 作品登録 — 転記用完全版

> ProtoPedia の各欄にそのまま貼り付けるためのドラフト (2026-07-02 作成)。
> 【必須】欄がすべて埋まらないと審査対象にならない。タグ `findy_hackathon` を忘れないこと。
> **Veo は使用していないため、開発素材・ストーリーのどこにも書かない**(審査基準⑤: 主張と実体の整合)。

---

## 作品ステータス【必須】

完成

## 作品タイトル【必須】

Citify — 自分の街、自分の世代の話を、60秒で。

## 概要【必須】(200字以内)

自治体の議事録・プレスリリースを AI が読み、役所言葉を若者の言葉に翻訳して TikTok 風フィードで届けるマルチエージェントプロダクト。「街の見張り番」Watcher エージェントが自分で調査計画を立て、統計・議題・人口推移を並列調査して「あなたに合う街」を自己検証つきで結論します。全国830の自治体・議会、3,700件超の議題を処理。

(↑ 172 字 / 上限 200 字)

## 動画【必須】

YouTube URL: (7/6 編集完了後に記入)

## 画像【任意・最大5枚】

1. For You フィード画面 (Imagen サムネ + 翻訳サマリ)
2. Watcher 自律実行トレース画面
3. 街比較ビュー
4. 街ダッシュボード (人口推移 + 関心軸)
5. アーキテクチャ図 (docs/assets/architecture.svg)

## システム構成【必須】

- アップロード画像: `docs/assets/architecture.svg` (PNG 変換版)
- 技術補足 (任意欄):

> フロントは Next.js (Firebase App Hosting)。API は FastAPI (Cloud Run)。
> 議事録・プレスは Pub/Sub 4段パイプライン (翻訳→影響度採点→配信→BigQuery) を Cloud Run Jobs + Cloud Scheduler で日次処理。
> 対話・自律系は ADK: Watcher (自律ツールループ + 自己検証)、Concierge (翻訳/影響度をサブエージェントに持つ親子階層)、Preferences (自然言語からの関心抽出)。
> 関連議題検索は Vertex AI RAG Engine (国会議事録コーパス 1,428 件、自治体議事録への拡張は今後)。サムネは Imagen 3 (person_generation=dont_allow + SynthID + AI 生成ラベル)。
> 運用もエージェント化: スクレイパー失敗診断 (Scraper Doctor)・コスト異常検知 (Cost Hunter) — いずれも自動実行はせず人間レビュー前提の提案まで。
> インフラは全て Terraform 管理、GitHub Actions + Cloud Build で main マージから本番まで自動デプロイ。

## 開発素材【必須】

Google Cloud: Cloud Run / Cloud Run Jobs / Pub/Sub / BigQuery / Firestore / Cloud Scheduler / Cloud Build / Cloud Storage / Cloud Logging / Secret Manager
AI: ADK (Agent Development Kit) / Gemini 2.5 Flash・Pro / Vertex AI RAG Engine / Vertex AI Embeddings (text-multilingual-embedding-002) / Imagen 3
アプリ: Next.js 16 / TypeScript / Tailwind CSS / FastAPI / Python 3.12 / Playwright / Firebase App Hosting
DevOps: Terraform / GitHub Actions / pytest / Vitest / ruff
データソース: 国会会議録検索 API / 自治体議事録 (kaigiroku.net) / 自治体プレスリリース RSS / e-Stat / 不動産情報ライブラリ (Reinfolib)

## タグ【必須】

`findy_hackathon` `citify` `ai-agent` `multi-agent` `adk` `gemini` `civic-tech` `devops`

## 関連URL【任意】

- デプロイ URL: https://citify-web--citify-dev.asia-east1.hosted.app/
- GitHub: https://github.com/yujmatsu/citify

---

## ストーリー【必須】

### ① 解決したい課題とその背景

私は地方出身、東京で働いて 5 年になるエンジニアです。住んでいる区の議会で何が議論されているか、一度も読んだことがありませんでした。家賃補助、子育て支援、防災——自分の生活に直結する意思決定が毎週行われているのに、議事録は専門用語の長文で、自治体サイトは「自分から探しに行く図書館」。読まれないのは若者の無関心のせいではなく、**情報の届き方が世代に合っていない**からだと考えました。

さらに、引越し・移住のような「街を選ぶ」場面では、複数の自治体の政策・統計・議論を横断して比べる手段がそもそも存在しません。

### ② 想定する利用ユーザー

18〜35 歳の都市生活者。具体的には:

- **上京して数年の若手社会人** — 自分の区で何が起きているかを知りたい
- **地方の実家が気になる世代** — 親の住む街の介護・空き家の議論を追いたい
- **移住・引越し検討層** — 候補の街の子育て支援・住居政策・人口動態を比較して選びたい

### ③ プロダクトの特徴

1. **役所言葉の翻訳フィード** — 議事録・プレスを Gemini が 3 行に平易化し、年代でトーンを変える。関心軸 × 年代 × 地理で採点し For You フィードに配信。原典リンクを必ず併記
2. **「街の見張り番」Watcher エージェント (ADK)** — ペルソナを読んで自分で調査計画を立て、統計比較・議題検索・人口推移などのツールを並列実行、結論前に自己検証。結果は根拠つきの街評価 + アクションプランに
3. **自治体比較・対話での街探し** — 2〜3 自治体をテーマ横断で比較。Concierge は翻訳/影響度エージェントをサブエージェントに持つ ADK 親子階層
4. **国会議事録 RAG** — Vertex AI RAG Engine (国会議事録コーパス) で関連する国会の論戦を検索し、議題詳細に根拠として表示
5. **運用のエージェント化 (DevOps × AI Agent)** — スクレイパー失敗を診断・修正提案する Scraper Doctor、コスト異常検知の Cost Hunter。自動実行はせず人間レビュー前提
6. **政治的中立と倫理** — 賛否は出さない・政治家名/党名の混入を多層ガードで検出・Imagen は人物生成禁止 + SynthID + AI 生成ラベル・robots.txt を尊重 (Disallow の議事録システムは対応コードごと Drop)
7. **規模と実運用** — 全国 1,795 自治体マスタ、830 自治体・議会の 3,700 件超の議題を処理。インフラは Terraform、CI/CD は GitHub Actions + Cloud Build で完全自動化

---

## 転記チェックリスト

- [ ] 動画 URL を記入した (YouTube 限定公開→提出時公開)
- [ ] アーキ図を「システム構成」にアップロードした
- [ ] タグ `findy_hackathon` を付けた
- [ ] 作品ステータス「完成」
- [ ] Veo への言及が無いことを最終確認した
- [ ] ProtoPedia 作品 URL を Google Form (7/9 提出) に貼った
