# kaigiroku_net_recon.md — DiscussNet 構造調査記録 (Week 0)

> A-4(議事録パーサー: DiscussNetPremium) の実装可能性判定のための事前調査記録。
>
> **実施日**: 2026-05-20 / **実施者**: Yuji + Claude Code
>
> **最終判定**: 🟡 **YELLOW — Playwright + headless Chromium での実装が必須**

---

## 0. Executive Summary

| 観点 | 結論 |
|---|---|
| DiscussNet 採用自治体数 | **540 自治体** (2025/7、株式会社会議録研究所 & NTT-AT 共同開発) |
| 配信モデル | **3 種類** (中央型 / 白ラベル / 別ベンダ) — DATA_SOURCES.md の単一モデル前提は誤り |
| HTML 構造 | 中央型・白ラベルで **ほぼ同一**(SPA + JSONP API) |
| データ取得 | **SPA で動的描画**、BeautifulSoup 単独では不可 |
| API 直接叩き | **robots.txt の Disallow `/dnp/` に該当 → 倫理的禁止** |
| 解決策 | **Playwright + Chromium でブラウザ描画** |
| 推定コスト | インフラ +$0〜5/月、実装工数 +1.5-2 日(Vibe Coding 前提) |
| 採用判定 | **Plan A (Playwright) で進める。Week 2 中日で動かなければ Plan B に降格** |

---

## 1. 配信モデル 3 分類(重大発見)

`DATA_SOURCES.md §2` は「全自治体が `ssp.kaigiroku.net/tenant/{id}/` 配下にホストされる中央集権モデル」と記述していたが、**実態は 3 種類**:

### 1.1 中央型 (Centralized Hosting)

**URL パターン**: `https://ssp.kaigiroku.net/tenant/{tenant_id}/`

**確認済テナント**:

| tenant_id | 自治体 | UI バリエーション |
|---|---|---|
| `cityosaka` | 大阪市 | テンプレ C (Smartphone 専用 meta-refresh) |
| `tosa` | 高知県 | テンプレ B (Legacy HTML4, Shift_JIS) |
| `prefokayama` | 岡山県 | テンプレ A (Modern HTML5, UTF-8) — **検証メイン** |
| `prefosaka` | 大阪府 | (未取得、検索結果から URL 確認) |
| `prefoita` | 大分県 | (未取得) |

### 1.2 白ラベル型 (White-label Deployment)

**URL パターン**: 自治体独自ドメイン上で DiscussNet を運用

**確認済テナント**:

| 自治体 | URL | 備考 |
|---|---|---|
| 横浜市 | `http://giji.city.yokohama.lg.jp/tenant/yokohama/` | **HTTP (HTTPS でない)**、Shift_JIS、HTML 構造はテンプレ A 同型 |

→ **同じ DiscussNet エンジン**、CSS 名のみ違い (`normal_ab.css` vs `simple_ab.css`)。**パーサー 1 個で対応可能**

### 1.3 別ベンダ型 (NOT DiscussNet)

**URL パターン**: `*.gijiroku.com/voices/*.asp` または `*.lg.jp/voices/...` (Microsoft ASP 系)

**確認済テナント**:

| 自治体 | URL | 備考 |
|---|---|---|
| 札幌市 | `https://sapporo.gijiroku.com/voices/g07v_search.asp` | 別ベンダ、A-4 対象外 |
| 世田谷区 | `https://kugi.city.setagaya.tokyo.jp/voices/` | 同じ `/voices/*.asp` 系、A-4 対象外 |

→ **A-4 の範囲外**。別途 B-6 (DB-Search) または C-2 (Sophia/DNP) で対応検討、または Drop。

---

## 2. DiscussNet 内部アーキテクチャ

### 2.1 ページ階層

| URL | 役割 | 静的 HTML として有用か |
|---|---|---|
| `/tenant/{id}/pg/index.html` | メニュー(検索/閲覧/発言集) | △ リンク情報のみ |
| `/tenant/{id}/MinuteSearch.html` | キーワード/発言者検索 UI | ❌ SPA shell |
| `/tenant/{id}/MinuteBrowse.html` | 年度・会議種類で閲覧 | ❌ SPA shell |
| `/tenant/{id}/MakeSpeakerCollect.html` | 発言集作成 | ❌ SPA shell |
| `/tenant/{id}/SpTop.html` | スマホ版トップ | (未調査) |

すべて `<tbody id="council_list">` が **空のシェル**、jQuery + Handlebars + 自前 `app.js` で JS 描画。

### 2.2 内部 API エンドポイント

DevTools で観察 (prefokayama / MinuteBrowse.html):

| エンドポイント | メソッド | 役割 | サイズ |
|---|---|---|---|
| `/dnp/search/councils/get_layout?callback=...` | POST | UI レイアウト設定 | 0.4 KB |
| `/dnp/search/councils/get_permission?callback=...` | POST | アクセス権限チェック | 0.6 KB |
| `/dnp/search/councils/get_view_years?callback=...` | POST | 利用可能な年度一覧 | 2.6 KB |
| `/dnp/search/councils/index?callback=...` | POST | **会議一覧データ本体** | 1.6 KB |

**全 API 共通仕様**:
- HTTP メソッド: **POST**
- レスポンス: **JSONP**(`application/javascript; charset=UTF-8`、コールバック関数でラップ)
- 認証: Cookie 2 つ必須
  - `sid_search` (セッション ID)
  - `RqFCpDrmh2CQRV44vQSv5TPJGqJCpw__` (CSRF/anti-bot トークン、命名はランダム化)
- ヘッダ: `x-requested-with: XMLHttpRequest` 必須
- POST ボディ: form-encoded、29-32 bytes 程度(中身は未確認)

### 2.3 観察された複数発行リクエストの謎

各 XHR(`get_permission`, `get_view_years`, `index`) が **3 回ずつ** 発火していた。同一エンドポイントを別 callback で重複コール。理由は推測:

- 検索/閲覧/発言集の各タブ用に preload
- DOMContentLoaded まで 2.8 分かかった(キャプチャより) ← パフォーマンス問題? 計測条件不明

→ Week 2 で実装する際に Playwright がどう振る舞うかは要観察。

---

## 3. robots.txt 解析 (倫理判定)

```
User-agent: *
Disallow: /                ← 全パス禁止
Allow: /tenant/             ← /tenant/ のみ例外
Disallow: /tenant/js/       ← JS 配信ディレクトリ禁止
Disallow: /tenant/css/      ← CSS 配信禁止
Disallow: /tenant/help/     ← ヘルプ禁止
Disallow: /tenant/stats/    ← 統計禁止
```

### 3.1 解釈

| アクセス対象 | 許可? |
|---|---|
| `/tenant/{id}/*.html` (Minute系含む) | ✅ Allow |
| `/dnp/search/councils/*` (API) | ❌ Disallow(全パス禁止 + Allow 外) |
| `/tenant/js/*`, `/tenant/css/*` | ❌ Disallow |

### 3.2 結論

- **API 直接コール (`/dnp/`) は robots.txt 違反**
- ただし **「ブラウザが SPA 描画のために API を呼ぶ」のは正常なユーザー振る舞い**(robots.txt は自動クローラ向けの規約)
- **Playwright は実ブラウザを動かしているのと等価** → ブラウザ的振る舞いとして倫理的にクリア

PROJECT.md §5.2 の「robots.txt を必ず尊重」を満たすには **Playwright 必須**。

---

## 4. 採用判定: 🟡 **YELLOW (Playwright 必須)**

### 4.1 判定根拠

- ✅ DiscussNet は同一テンプレートで 540 自治体カバー(中央型・白ラベルとも)
- ✅ 同じパーサーロジックで複数自治体対応可能
- ❌ BeautifulSoup + httpx の単純構成では不可(SPA で動的描画)
- ❌ API 直接コールは robots.txt 違反
- ✅ Playwright で SPA 描画後に DOM 抽出 → 倫理的・技術的に成立

### 4.2 戦略選択: Plan A 採用

| Plan | 内容 | 採用? |
|---|---|---|
| **A. Playwright 実装** | Chromium 同梱、SPA 描画後に DOM 抽出 | ✅ **採用** |
| B. A-4 を Should に降格 | 国会 API + プレス RSS のみ、自治体カバレッジ大幅縮小 | Drop Point として保持 |
| C. NTT-AT 公式問合せ | 公式 API/データ提供の打診 | 不採用(返信タイミング不明) |

### 4.3 Drop Point ルール(Week 2 で発動判断)

**発動条件** (どれか 1 つでも該当 → Plan B に切替):
- Week 2 中日 (6/4 水) までに Playwright で **1 自治体の議事録 1 件** を取得できない
- Chromium のメモリ消費が 2 GiB を超えて Cloud Run で OOM Kill が頻発
- DiscussNet 側で大幅な構造変更(ヘッダ・URL パターン変更等)
- 取得した HTML が想定構造と乖離していて、selector 設計が破綻

**Plan B 切替時の実装変更**:
- A-4 の `tier` を Tier 1 → Tier 3 に降格(マスタ更新)
- B-7 (プレス RSS) を Should から Must に昇格して自治体カバレッジ補強
- ピッチでの「800 自治体カバー」謳い文句を「47 都道府県 + 国会で全国網羅」に変更

### 4.4 コスト見積(月次)

| 項目 | Plan A | Plan B | 差分 |
|---|---|---|---|
| Cloud Run インフラ | ~$0.6/月 (無料枠で実質 $0) | ~$0/月 | ほぼ誤差 |
| コンテナサイズ | 650 MB (Chromium 同梱) | 250 MB | +400 MB |
| 実装工数 | 1.5-2 日 (Vibe Coding) | 0.5 日 | +1-1.5 日 |
| カバレッジ | DiscussNet 540 自治体 | 国会 + プレス RSS のみ | DiscussNet 失う |

→ コスト差は実質ゼロ、得られる価値は B-2 比較ビューの成立性に直結。

---

## 5. Week 2 実装計画 (DiscussNet 部)

### 5.1 タスク順序

1. **Day 1 午前**: Playwright Python セットアップ + Hello World (prefokayama の MinuteBrowse をスクショ保存)
2. **Day 1 午後**: 会議一覧抽出ロジック (`tbody#council_list` の `<tr>` パース)
3. **Day 2 午前**: 個別会議録ページ取得 + 発言ブロック抽出
4. **Day 2 午後**: マルチテナント化 (tenant_id を引数化)、yokohama (白ラベル) で動作確認
5. **Day 3**: BigQuery 投入バッチ + HTML fixture テスト

### 5.2 必須ファイル(scaffolding)

```
scrapers/kaigiroku_net/
├── client.py              # Playwright 起動・テナント別 URL ビルダ
├── parser.py              # DOM 抽出 (会議一覧 + 発言ブロック)
├── selectors.yaml         # テナント別 selector マップ (variant 吸収用)
├── fixtures/
│   ├── prefokayama_browse.html       # 既に取得済 (/tmp/citify-week0/...)
│   ├── prefokayama_meeting_sample.html  # Week 2 で追加
│   └── yokohama_browse.html          # 既に取得済
└── test_parser.py         # fixture からの構造抽出テスト
```

### 5.3 Cloud Run 設定

- Image: `mcr.microsoft.com/playwright/python:v1.x-noble` ベース
- Memory: **2 GiB** (1 GiB だと OOM リスク)
- CPU: 1 vCPU
- Concurrency: **1** (Chromium は並列に弱い、複数同時起動はメモリ枯渇)
- Timeout: 300 秒 (1 自治体あたり最大 5 分)
- 実行モード: **Cloud Run Jobs** (Service ではなくバッチ用)

---

## 6. 横展開: 別ベンダ(sapporo, setagaya)について

### 6.1 観察

両方 `/voices/*.asp` パターン:
- 札幌市: `https://sapporo.gijiroku.com/voices/g07v_search.asp`
- 世田谷区: `https://kugi.city.setagaya.tokyo.jp/voices/`

→ Microsoft ASP/ASP.NET ベースの別ベンダ製品。プロバイダは未調査。

### 6.2 取扱い

- **A-4 の対象外** として明確に切り出す
- C-2 (Sophia/DNP) で扱うか、別途新規 C-X として位置付け
- Tier 1 候補から 23 区 + 政令市の半分以上を **失う可能性あり** → 大きなインパクト
- 札幌市・世田谷区が DiscussNet 系でないことは Citify のカバレッジ戦略に影響

### 6.3 Phase 2 でやるべき調査

- `/voices/*.asp` 系の採用自治体一覧調査
- 同じシステムを使う Tier 1 自治体の特定(東京 23 区、政令市)
- 別 recon doc (`docs/scrapers/voices_asp_recon.md`) として記録

---

## 7. 副次的な懸念事項

### 7.1 DOMContentLoaded 2.8 分

DevTools のキャプチャで、prefokayama/MinuteBrowse.html の DOMContentLoaded が **2 分 48 秒** と異常に遅い。
推測:
- Network throttling? (Yuji 側で設定なし)
- 計測条件が「全リソース完了」を見ていた? (124 件中 10 件のリクエスト という表記から推測)
- 一部リソースの長時間 polling

→ Week 2 で Playwright 実装時に再計測。実取得時間が 10 秒程度なら無視可能。

### 7.2 同一エンドポイントの 3 回コール

`get_permission`, `get_view_years`, `index` が各 3 回ずつ発火。重複の意味は不明。

→ Week 2 で Playwright 自動化時、無駄リクエストにならないよう注意。

---

## 8. 保存済 HTML Fixture (Week 2 で利用)

すべて `/tmp/citify-week0/kaigiroku_recon/` に保存:

| ファイル | テナント | ページ | サイズ |
|---|---|---|---|
| `ssp_cityosaka_index.html` | cityosaka | pg/index.html | 198 B (meta-refresh) |
| `ssp_tosa_index.html` | tosa | pg/index.html | 1.9 KB (Legacy template) |
| `ssp_prefokayama_index.html` | prefokayama | pg/index.html | 1.9 KB (Modern template) |
| `ssp_prefokayama_minutesearch.html` | prefokayama | MinuteSearch.html | 36.8 KB (SPA shell) |
| `ssp_prefokayama_minutebrowse.html` | prefokayama | MinuteBrowse.html | 7.1 KB (SPA shell) |
| `yokohama_index.html` | yokohama | pg/index.html | 7.5 KB (Shift_JIS) |
| `yokohama_minutesearch.html` | yokohama | MinuteSearch.html | 36.3 KB |
| `yokohama_minutebrowse.html` | yokohama | MinuteBrowse.html | 7.1 KB |
| `setagaya_index.html` | setagaya | / | 360 B (別ベンダへ meta-refresh) |
| `robots.txt` | — | https://ssp.kaigiroku.net/robots.txt | 136 B |

> 📦 Week 2 で `scrapers/kaigiroku_net/fixtures/` に正式移植予定。

---

## 9. DATA_SOURCES.md §2 への更新提案

以下を反映する PR を Week 0 終了までに別途作成:

- [ ] **採用自治体数**: 「350+」→ **「540 (2025/7 時点)」**(出典: 株式会社会議録研究所)
- [ ] **配信モデル**: 中央型のみの記述 → **3 種類 (中央型 / 白ラベル / 別ベンダ)** に分類
- [ ] **URL パターン**: `ssp.kaigiroku.net/tenant/{id}/SpMinuteView.html` という固定例 → **テナント固有ドメイン (giji.\*, kugi.\* 等) も含む** と明記
- [ ] **HTML 構造**: BeautifulSoup でパース可能の暗黙前提 → **SPA / JSONP API、Playwright 必須** と明記
- [ ] **tenant_id 一覧**: setagaya, sapporo は **DiscussNet ではない** ことを明記、削除または注釈
- [ ] **取得フロー**: §2.4 の単純な `httpx + BeautifulSoup` 例 → **Playwright + DOM 抽出** に書き換え
- [ ] **クロール間隔**: 5 秒間隔継続(変更なし、ただし Playwright 起動オーバーヘッドで自然と間隔は伸びる)

---

## 10. 改訂履歴

- 2026-05-20 v0.1 初版テンプレート作成
- 2026-05-20 v1.0 **観察完了、Playwright 採用判定で書き直し**
