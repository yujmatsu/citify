# voices_asp_recon.md — VOICES/Web 構造調査記録 (Week 0)

> 自治体議事録パーサー第 2 系統「voices_asp」(製品名: **VOICES/Web**) の実装可能性判定のための事前調査記録。
>
> **実施日**: 2026-05-20 / **実施者**: Yuji + Claude Code
>
> **最終判定**: 🟢 **GREEN — BeautifulSoup + httpx で実装容易、Playwright 不要**
>
> ⚠️ **2026-05-21 改訂** (Phase I 実装中の発見、§11 詳細):
>    1. 年度トップ以降の SPA 風ページは **JavaScript 必須**
>    2. 個別議事録の実コンテンツは **`/voices/cgi/voiweb.exe` (robots.txt Disallow)** にあり、bot 取得は **倫理的に不可**
>    3. 結果として A-4b の content scraping は **drop**、scope を「年度メタデータ + 外部リンク」のみに縮小

---

## 0. Executive Summary

| 観点 | 結論 |
|---|---|
| 製品名 | **VOICES/Web** (HTML タイトル "...VOICES/Web" / "...会議録検索システム VOICES/Web" から判明) |
| 採用自治体数 | 推定 100+ (詳細は別途調査、Tier 1 で 9 件確認済) |
| HTML 構造 | **静的 XHTML 1.0 サーバーサイドレンダリング**、SPA ではない |
| JavaScript 依存 | **なし**(Google Analytics と SNS share button のみ、本体データには不要) |
| データ取得 | **HTML 内に全てインライン** で server-render される |
| robots.txt 規約 | **`/voices/*.asp` は明示的に許可**(`/voices/cgi/` のみ Disallow) |
| 文字コード | **Shift_JIS 統一** (charset=shift_jis、要 explicit encoding 指定) |
| ホスティング モデル | 中央型(`*.gijiroku.com`)/ 白ラベル 1(自治体独自サブドメイン)/ 白ラベル 2(独自ドメイン) の **3 種すべてで同一テンプレート** |
| 実装方式 | **BeautifulSoup + httpx + Shift_JIS handling** で十分 |
| 推定実装工数 | 1-1.5 日 (Vibe Coding、kaigiroku Playwright 案と比較して大幅に楽) |
| 採用判定 | **Week 3-4 で実装、A-4 (Plan A Playwright) と並行** |

→ A-4 (kaigiroku) が YELLOW(Playwright 必須)だったのに対し、voices_asp は **GREEN**。技術的にも倫理的にもクリーン。

---

## 1. ベンダ識別

### VOICES/Web (販売元未確定、おそらく「ぎじろくセンター」または別パートナー)

- HTML タイトルに `VOICES/Web` または `会議録検索システム VOICES/Web` が明示
- adachi のリダイレクト先タイトル: `足立区議会 会議録検索システム VOICES/Web`
- minato のタイトル: `会議録ライブラリ港議会`
- sapporo のタイトル: `札幌市議会 会議録検索システム`

技術的特徴(全テナント共通):
- XHTML 1.0 Strict / Transitional + CSS (古典的)
- `class="AreaHeader"` / `class="AreaContentsBase"` / `class="AreaGikaidoc"` などのテンプレ
- `*.asp` ASP/ASP.NET ベース(Microsoft 系)
- Google Analytics 1 件のみ(`gtag.js`)

DiscussNet (会議録研究所/NTT-AT)とは **別ベンダ**。kensakusystem.jp 系のような旧 HTML4 でもない、独自プロダクト。

## 2. Tier 1 で確認済の voices_asp 自治体 (9 件)

| 自治体 | scraper_base_url | ホスティング種別 |
|---|---|---|
| 札幌市 | `https://sapporo.gijiroku.com/voices` | 中央型 (gijiroku.com) |
| 港区 | `https://gikai2.city.minato.tokyo.jp/voices` | 白ラベル(独自サブドメイン) |
| 台東区 | `https://taito.gijiroku.com/voices` | 中央型 |
| 世田谷区 | `https://kugi.city.setagaya.tokyo.jp/voices` | 白ラベル |
| 杉並区 | `https://suginami.gijiroku.com/voices` | 中央型 |
| 板橋区 | `https://itabashi.gijiroku.com/voices` | 中央型 |
| 足立区 | `https://www.gikai-adachi.jp/voices` | 白ラベル(独自ドメイン) |
| 江戸川区 | `https://www.gikai.city.edogawa.tokyo.jp/voices` | 白ラベル |
| 大田区 | `https://www.gikai-ota-tokyo.jp/ota` | 白ラベル(`/ota/` サブパス変則) |

実地検証済テナント: **sapporo / minato / adachi** (3 種類のホスティング種別をカバー)

---

## 3. robots.txt 解析

**3 テナント全てで同一の robots.txt (1,621 bytes)** が使われている — つまり同じベンダ管理。

### 拒否対象 (`User-agent: *`)

```
Disallow: /voices/cgi/        ← 内部 CGI スクリプト
Disallow: /voices2/cgi/       ← V2 系の内部
Disallow: /gikai/cgi/         ← 旧名内部
Disallow: g07_Video_View.asp  ← 動画ページ群 (hot-link 防止)
Disallow: g07_Video_View_s.asp
Disallow: g07_Video2_View.asp
Disallow: g07_Video2_View_s.asp
Disallow: g08_Video_View.asp
Disallow: g08_Video_View_s.asp
Disallow: g08_Video2_View.asp
Disallow: g08_Video2_View_s.asp
Disallow: g07_Video_ViewSub.asp
Disallow: /voices/gikaidoc/index.html    ← 文書索引 (PDF 一覧)
Disallow: /voices/gikaidoc/index2.html
Disallow: /gikai/gikaidoc/index.html
Disallow: /gikai/gikaidoc/index2.html
Disallow: /gikai/voices/gikaidoc/index.html
Disallow: /gikai/voices/gikaidoc/index2.html
```

### SEO Bot 明示的拒否

DotBot, SemrushBot, AhrefsBot, BLEXBot, MJ12bot, Steeler, ltx71, Linguee, proximic, GrapeshotCrawler, Mappy, MegaIndex, Hatena::Russia::Crawler, PaperLiBot, PetalBot, YandexBot, CCBot, LivelapBot, Cincraw, Go-http-client, BaiduSpider — これらは全パス Disallow。

### Citify への含意

Citify UA (`Citify-Hackathon/0.1 ...`) は上記の SEO bot リストに該当しない → **`User-agent: *` 規約に従う**:
- ✅ `/voices/g07v_search.asp` / `g08v_viewh.asp` / `g08v_views.asp` 等の議事録ページは **許可**
- ❌ `/voices/cgi/` 内部 CGI は禁止
- ❌ 動画ページ群(`g0X_Video_*.asp`) は禁止 — Citify は動画を直接配信しないので無関係
- ❌ gikaidoc/index.html (PDF 一覧) は禁止

→ **議事録テキストの取得は明示的に許可**、PROJECT.md §5.2 の robots.txt 遵守要件を満たす。

---

## 4. URL 構造 (sapporo 例)

VOICES/Web は **URL クエリパラメタで階層的にデータをドリル**できる。極めてシンプル。

### 主要エンドポイント

| URL | 役割 | パラメタ |
|---|---|---|
| `/voices/index.asp` | トップ (ガイド + リンク集) | なし |
| `/voices/g08v_viewh.asp` | 本会議録 年度一覧 | なし (年度リスト出力) |
| `/voices/g08v_viewh.asp?Sflg=10` | 本会議録 全件 | `Sflg=10` 定例会すべて |
| `/voices/g08v_viewh.asp?Sflg=11&FYY=2025&TYY=2025` | 本会議録 N 年分 | `Sflg=11`, `FYY=N`, `TYY=N` |
| `/voices/g08v_viewh.asp?Sflg=20` | 臨時会 全件 | `Sflg=20` |
| `/voices/g08v_viewh.asp?Sflg=21&FYY=N&TYY=N` | 臨時会 N 年分 | `Sflg=21`, `FYY=N`, `TYY=N` |
| `/voices/g08v_views.asp` | 委員会記録 年度一覧 | (Sflg/FYY/TYY 同様の構造想定) |
| `/voices/g07v_search.asp` | 詳細検索 UI | フォーム POST |

### スクレイピング戦略

```
1. /voices/g08v_viewh.asp を GET → 年度リンク一覧(`<ul class="kaigi_view">` の `<li><a>`)を抽出
2. 各年度リンクの URL パラメタを抽出 (Sflg + FYY + TYY)
3. 個別年度ページを GET → 会議リンク一覧を抽出
4. 個別会議ページを GET → 発言ブロックを抽出
5. /voices/g08v_views.asp (委員会) も同様
```

サーバー再描画なし、すべて HTML 内に server-render 済。

---

## 5. Citify への影響

### A-4 (Playwright) との比較

| 観点 | A-4 (DiscussNet SPA) | voices_asp |
|---|---|---|
| 実装方式 | Playwright + Chromium 必須 | **BeautifulSoup + httpx** |
| Cloud Run コンテナサイズ | +400 MB (Chromium) | +50 MB (lxml 等) |
| メモリ要件 | 1-2 GiB | 256-512 MiB |
| 1 ページ取得時間 | 5-10 秒 | **0.3-1 秒** |
| 月次インフラコスト | ~$0.6 | **~$0.1** |
| 倫理判定 | robots.txt の `/dnp/` Disallow をブラウザ振る舞いで回避 | **直接許可** で完全クリーン |
| 実装工数 | 1.5-2 日 | **1-1.5 日** |

→ voices_asp は **全観点で A-4 より楽**。Yuji の選択した「3 系統並行戦略」がさらに正当化される。

### 9 自治体カバーの戦略意義

| ペルソナ | カバー対象 |
|---|---|
| A. 新社会人(東京 23 区) | **港区・台東区・世田谷区・杉並区・板橋区・足立区・江戸川区・大田区** = 8 区 |
| B. 実家気にする層(地方) | **札幌市** |
| C. 移住検討層 | (今後対応の地方都市) |

東京 23 区中 8 区(35%)、政令市 1 件 = ペルソナ A のカバレッジが一気に充実。これは voices_asp の戦略的価値。

---

## 6. 実装計画 (Week 3-4)

### Day 1 (3-4 時間)

- `scrapers/voices_asp/client.py` — httpx + Shift_JIS handling
- `scrapers/voices_asp/parser.py` — g08v_viewh.asp の年度一覧パース
- 1 自治体 (sapporo) で会議一覧取得確認

### Day 2 (3-4 時間)

- 個別会議ページ取得 + 発言ブロック抽出 (selector 確定要)
- マルチテナント対応 (`scraper_base_url` 切替)
- yokohama 互換テスト(白ラベル sapporo 比較)

### Day 3 (任意、半日)

- HTML fixture テスト
- BigQuery 投入バッチ統合
- 委員会記録 (g08v_views.asp) も同様にパース

### Drop Point (Week 3 末で発動判断)

- 個別会議ページに想定外の構造があり 1 日経っても発言抽出できない → 暫定的に「年度・会議名のメタ情報のみ取得」で妥協
- セッション cookie や CSRF を必要とする検索フォームが必要になった → POST 機能は Phase 3 に持ち越し、`g08v_viewh.asp` 経由の閲覧型のみ実装

---

## 7. 保存済 HTML Fixture (Week 3 で利用)

すべて `/tmp/citify-week0/voices_asp_recon/` に保存:

| ファイル | テナント | ページ | サイズ |
|---|---|---|---|
| `sapporo_robots.txt` | sapporo.gijiroku.com | /robots.txt | 1.6 KB |
| `minato_robots.txt` | gikai2.city.minato.tokyo.jp | /robots.txt | 1.6 KB (同一) |
| `adachi_robots.txt` | www.gikai-adachi.jp | /robots.txt | 1.6 KB (同一) |
| `sapporo_voices.html` | sapporo | /voices/ | 4.7 KB |
| `sapporo_index.html` | sapporo | /voices/index.asp | 4.7 KB (同内容) |
| `sapporo_g08v_viewh.html` | sapporo | /voices/g08v_viewh.asp | 10.7 KB ← 年度リスト 39 年分 |
| `minato_voices.html` | minato | /voices/ | 94 KB (議題リスト inline 展開含む) |
| `adachi_voices.html` | adachi | /voices/ | 284 B (meta-refresh) |

> 📦 Week 3 で `scrapers/voices_asp/fixtures/` に正式移植予定。

---

## 8. DATA_SOURCES.md 更新提案

以下を反映する PR を Week 1 着手前に作成想定:

- [ ] §2 (kaigiroku.net) と並列で **§3 (voices_asp)** セクションを新設
- [ ] 出典: 製品名 VOICES/Web、推定販売パートナーは別途調査
- [ ] URL パターン: `{scraper_base_url}/g08v_viewh.asp?Sflg=11&FYY=N&TYY=N` を明記
- [ ] robots.txt: `/voices/*.asp` Allow, `/voices/cgi/` Disallow を明記
- [ ] 文字コード: Shift_JIS、httpx で `encoding='shift_jis'` 明示指定
- [ ] BigQuery スキーマは `kaigiroku` と同じ(共通の `speeches` テーブル、`source` カラムで `voices_asp` を区別)

---

## 9. 残課題 (Week 3 着手時に depth dive)

- 個別会議ページ (`g08v_viewh.asp?Sflg=11&FYY=2025&TYY=2025` の先) の HTML 構造未確認
- 発言ブロックの selector (どの `<div>` / `<table>` に speaker / speech が入るか)
- 検索フォーム POST の挙動 (セッション cookie 必要か)
- 委員会記録 (`g08v_views.asp`) は本会議録と同構造かどうか
- gikai-ota-tokyo.jp の `/ota/` 変則サブパスが parser ロジックに与える影響
- 練馬区(13120) の実 URL 確定(`city.nerima.tokyo.jp/gikai/kaigiroku.html` indirection 先)

これらは Week 3 で 1 自治体パーサー実装時に併せて確定する。

---

## 10. 改訂履歴

- 2026-05-20 v1.0 初版作成 (Week 0 構造調査の第 2 系統 voices_asp、GREEN 判定)
- 2026-05-21 v1.1 §11 追加: Phase I 実装中に判明した「2 階層目以降 JS 必須」問題

---

## 11. Phase I 実装中の発見 — 2 階層目以降は JS 必須 (2026-05-21)

### 11.1 観察事実

`scrapers/voices_asp/` 実装後、sapporo の年度詳細ページ
(`g08v_viewh.asp?Sflg=11&FYY=2025&TYY=2025`) を GET したところ:

- HTML サイズ: **4014 bytes** (年度トップ 10133 bytes の 40%)
- table_count: 0、`ul.kaigi_view` count: 0
- noscript 内に「**当サイトではJavaScriptを使用しています。検索機能を利用するためには、JavaScriptをonにしてください**」

→ **会議一覧の実データは JS による AJAX で動的読み込み** されており、static GET では取得不可能。

### 11.2 影響範囲 (server-render で取れる / 取れない)

| ページ | 取得可能 (no JS) |
|---|---|
| `/voices/index.asp` | ✅ |
| `/voices/g08v_viewh.asp` (年度トップ) | ✅ ul.kaigi_view に 39 年 × 2 系統 = 78 entries |
| `/voices/g08v_viewh.asp?Sflg=10` (全件) | ❌ 4000 bytes の shell のみ |
| `/voices/g08v_viewh.asp?Sflg=11&FYY=N&TYY=N` (年度詳細) | ❌ 同上 |
| `/voices/g08v_views.asp?…` (委員会) | ❌ (推定、未確認だが同実装と想定) |
| 個別会議録ページ | ❌ (上流に依存) |

### 11.3 当初 recon 誤判定の原因

Week 0 recon は **3 ページしか saved していなかった** (sapporo_voices.html / sapporo_index.html / sapporo_g08v_viewh.html、いずれもトップ階層):

- これらは全て年度トップで server-render される
- recon 中に「2 階層目に drill down」して確認していなかった
- 結果: 全 voices_asp ページが server-render と誤認 → GREEN 判定

### 11.4 戦略再評価

| Option | 工数 | 評価 |
|---|---|---|
| A. Playwright 化 (A-4 と同じインフラ流用) | 2-3h | A-4 ツリー展開と並行解決可、最有力 |
| B. AJAX endpoint をリバース工学 (DevTools で XHR 観察) | 2-4h | 成功すれば軽量実装、ただし sapporo / minato / adachi で異なる可能性あり |
| C. voices_asp スコープ縮小 (年度メタデータ index のみ取得、本文は別経路) | 1h | 妥協案、フィード生成には使えない |

→ **🛑 上記の判定が更に変わった (Phase I 後半の DevTools 観察)**: 年度詳細クリック先は AJAX でなく **`/voices/cgi/voiweb.exe?ACT=200&...&UNID=...`** への画面遷移だった。`/voices/cgi/` は voices_asp robots.txt で明確に **Disallow**:

```
User-agent: *
Disallow: /voices/cgi/        ← 内部 CGI スクリプト
```

→ Playwright であろうと AJAX 直叩きであろうと、CitifyBot は bot として識別される以上 **倫理的に取得不可**。Option A / B は drop。**Option C (スコープ縮小) が唯一の道**。

### 11.5 Phase I 到達状況 (2026-05-21 終了時点)

| 項目 | 状態 |
|---|---|
| パッケージ構造 `scrapers/voices_asp/` | ✅ 完成 (6 ファイル ~700 LOC) |
| 18 ユニットテスト (httpx.MockTransport + fixture HTML) | ✅ 全 PASS |
| 年度一覧取得 (sapporo で 78 entries 動作確認) | ✅ |
| Shift_JIS デコード | ✅ |
| 個別会議一覧取得 | 🛑 **drop** (`/voices/cgi/` robots.txt Disallow) |
| 発言抽出 | 🛑 **drop** (同上) |
| minato / adachi 横断検証 | 🟡 metadata only (年度一覧) scope で実施余地あり |

実質 **scope 縮小 ・metadata only として完了** = アーキテクチャの土台 + 年度メタデータ取得は完成、content scraping は drop。

### 11.6 確定 scope: metadata only + 外部リンク

Citify における voices_asp の最終扱い:

1. **年度メタデータ取得** (`g08v_viewh.asp` トップ、robots.txt Allow) で「VOICES/Web 対応自治体」識別
2. UI 上で **「公式議会公報はこちら」リンク** で当該自治体の `/voices/index.asp` に飛ばす (議事録は scrape しない)
3. **議事録 content は scrape せず**、ペルソナ A (新社会人東京) の 8 区分のカバレッジは **B-7 プレス RSS 前倒し** で代替

### 11.7 代替戦略: B-7 プレス RSS 前倒し

Phase K で B-7 を Week 5 → Week 2 に前倒し実装:
- 東京 23 区 + 政令市の **公式プレスリリース RSS** は robots.txt 制約なし、合法的に取得可能
- 議事録の代わりに「プレス情報 (新着政策・施策発表)」をペルソナに配信
- voices_asp 対応自治体 (港・台東・世田谷・杉並・板橋・足立・江戸川・大田・札幌) でもプレス RSS は別経路
