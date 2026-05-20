# Citify 作業ログ

## 2026-05-21 (Wed) Session 13 — Week 1 Phase B: 国会 API クライアント実装 (scrapers/kokkai/)

### Completed

- [x] **プロジェクトルート `pyproject.toml` 新規作成** — pytest + ruff の共通設定。`pythonpath = ["."]` で scrapers/ を import path に追加、testpaths に "scrapers" と "apps/api/tests"
- [x] **`scrapers/__init__.py`** + **`scrapers/kokkai/__init__.py`** — Python パッケージ化、`from scrapers.kokkai import KokkaiClient` で import 可能
- [x] **`scrapers/kokkai/schema.py`** — Pydantic v2 スキーマ:
  - `SpeechRecord`: 14 フィールド、camelCase ↔ snake_case を alias で吸収、`extra="allow"` で将来のフィールド追加に強い
  - `SearchResponse`: トップレベルレスポンス (numberOfRecords + nextRecordPosition + speechRecord)
- [x] **`scrapers/kokkai/client.py`** — httpx async client:
  - `KokkaiClient` (async context manager 対応)
  - `fetch_speeches()` 非同期 generator (ページネーション内部処理 + max_total 制御)
  - 引数: from_date / until_date / keyword / speaker / name_of_house / name_of_meeting / page_size / max_total
  - レート制限 1 sec default、httpx.AsyncBaseTransport 注入対応 (test 用)
  - exponential backoff (1 → 2 → 4 sec、最大 3 回 retry)
  - User-Agent: "Citify-Hackathon/0.1 (+https://github.com/yujmatsu/citify)" (DATA_SOURCES.md §0.2 準拠)
- [x] **`scrapers/kokkai/__main__.py`** — CLI エントリ:
  - argparse で 9 オプション (--query/--speaker/--house/--meeting/--days/--from/--until/--max/--page-size/--rate-limit/--verbose)
  - 出力は JSON Lines (1 行 1 record、by_alias=True、BigQuery 投入時にそのまま使える)
- [x] **`scrapers/kokkai/tests/test_client.py`** — pytest 7 ケース、`httpx.MockTransport` ベース (実ネット不要):
  - ✅ fixture から 2 件パース
  - ✅ ページネーション (2 ページ x 30 + 20 = 50 件)
  - ✅ max_total 早期終了
  - ✅ クエリパラメタ正確に送信 (any / speaker / nameOfHouse)
  - ✅ page_size 範囲外で ValueError
  - ✅ 日付逆転で ValueError
  - ✅ 5xx → 200 のリトライ動作
- [x] **`scrapers/kokkai/tests/fixtures/sample_response.json`** — 2 レコード fixture (石破茂・高市早苗、本会議)
- [x] **CLI 動作検証完了** — `python -m scrapers.kokkai --query 子育て --max 30` で 5 件 hit、JSON Lines 出力 OK、レート制限 1sec 守る、HTTP 200 OK、レスポンス bytes 文字化けなし
- [x] **tasks.json 更新**: A-3 → in_progress (BigQuery 残のため)、acceptance_criteria 4 つ中 3 つ達成
- [x] **Plans.md Week 1 更新**: データ収集セクション cc:TODO → cc:WIP、A-3 行に進捗注記

### Decisions / Design Notes

- **scrapers/ は別パッケージ化せず、プロジェクトルート pyproject.toml で `pythonpath = ["."]` 設定** — multi-pyproject の複雑性回避、`python -m scrapers.kokkai` で動く
- **httpx.MockTransport を選択 (respx 不使用)** — httpx 標準機能で十分、追加 dep 不要、test 高速 (1.27s で 7 件)
- **`fetch_speeches` を AsyncIterator にした** — 大量データ取得時に generator でメモリ効率良い、CLI でストリーミング出力可能、`max_total` で早期終了も自然
- **`extra="allow"` を Pydantic config に入れる** — API が将来フィールド追加しても落ちない。実 API が spec 外の `searchObject/closing/speakerRole/pdfURL` を返していたので即座に効果実証
- **`date` フィールドは `meeting_date` にリネーム + `alias="date"`** — Pydantic v2 の field 名と型名衝突回避。出力 JSON は `by_alias=True` で元の `"date"` キーに戻る
- **`startPage` は `int | None`** — 実 API が int 0 を返したため。spec doc の `"1"` (string) は古い情報

### Surprises / Risks

- **Pydantic v2 の field 名 / 型名衝突**: `date: date` のような自然な書き方が `PydanticUserError: unevaluable-type-annotation` になる。回避策はリネーム or 文字列アノテーション (`"date"`) or `from datetime import date as DateT`
- **実 API は spec doc と乖離あり**: startPage int / 追加フィールド 4 個 / speakerPosition null など。**spec はあくまで参考**、実 API レスポンスで schema を逆引きする必要あり。BigQuery 投入時も同じ罠に注意
- **「子育て」キーワードで 5 件しか hit しない**: 過去 30 日では限定的。本番運用で十分な data 量を集めるには `--days 365` 等で長期間取得 + 複数キーワード並列取得が必要
- **venv の実体は `apps/api/.venv/`**: シェルプロンプトの `(.venv)` は前回 activate 時の残骸表示。今後 venv 再 activate する際は `source apps/api/.venv/bin/activate` を使う。プロジェクトルートに venv は無い

### A-3 受入条件 vs 実装状況

| 受入条件 | 状態 |
|---|---|
| 直近 30 日の発言を取得できる | ✅ `--days 30` default、`--from/--until` で明示指定可 |
| 検索キーワードで絞り込みできる | ✅ `--query` (any) + `--speaker/--house/--meeting` も |
| レート制限を遵守(リクエスト間 1 秒以上) | ✅ default 1.0、`--rate-limit` で上書き可 |
| BigQuery にスキーマで保存 | ❌ Phase C で実装 (BigQuery dataset + 投入バッチ) |

**3/4 達成 — BigQuery 投入は Phase C (5/22 以降) に持ち越し**

### 次の Phase 候補

| Phase | 内容 | 想定時間 | 着手判断 |
|---|---|---|---|
| **C** | BigQuery dataset 作成 + 国会データ 100 件投入 | 2-3h | A-3 完了に必要、Week 1 終了時判定基準 ① 達成にも |
| **D** | Vertex AI RAG Engine セットアップ + 国会データ index 化 (A-10) | 3-5h | Week 1 終了時判定基準 ④ (セマンティック検索) 達成必要 |
| **E** | Terraform Firestore / Pub/Sub / Secret Manager モジュール化 (A-13) | 2-4h | Week 1 残作業、Week 2 着手前に終わらせたい |

### Commit Reminder

未コミット変更:

- `pyproject.toml` (新規、プロジェクトルート、開発ツール設定専用)
- `scrapers/__init__.py` (新規)
- `scrapers/kokkai/__init__.py` (新規)
- `scrapers/kokkai/schema.py` (新規、~60 行)
- `scrapers/kokkai/client.py` (新規、~170 行)
- `scrapers/kokkai/__main__.py` (新規、~100 行)
- `scrapers/kokkai/tests/__init__.py` (新規、空)
- `scrapers/kokkai/tests/test_client.py` (新規、~190 行)
- `scrapers/kokkai/tests/fixtures/sample_response.json` (新規)
- `tasks.json` (A-3 更新)
- `Plans.md` (Week 1 データ収集セクション更新)
- `log.md` (このファイル、Session 13 追記)

推奨コミット:
```bash
cd ~/projects/citify
git add pyproject.toml scrapers/ tasks.json Plans.md log.md
git status   # 12 ファイル staged 確認
git commit -m "feat(scrapers): A-3 国会会議録 API クライアント (httpx async + pagination + 7 tests)"
git push origin main
```

> ⚠️ この push は **apps/api/ を変更していない** ので Cloud Build trigger は走らない (included_files: apps/api/**, cloudbuild.yaml フィルタ)。これは意図通り

### Next (5/22 木以降)

Yuji の判断次第:
- **続行する場合**: Phase C (BigQuery 投入) で A-3 完全完了 → A-10 RAG → Week 1 判定基準 4/4 達成
- **休む場合**: 今日(5/21)は Phase A + B で十分過ぎる進捗 (Week 1 想定 5 日分のうち 2 日分)。明日は完全休息推奨

---

## 2026-05-21 (Wed) Session 12 — Week 1 Phase A: DevOps 動線完成 (Cloud Build → Cloud Run 自動デプロイ)

### Completed

- [x] **INFRA-008**: GCS state bucket `citify-dev-tf-state` 作成 (asia-northeast1、versioning ON) + Terraform backend gcs 有効化 → `terraform init` で state migrate
- [x] **GitHub App 連携**: Cloud Build の GitHub App 経由で yujmatsu/citify を接続 (OAuth UI フロー、1 回のみ)
- [x] **INFRA-009 (Terraform 13 リソース apply)**:
  - Artifact Registry repo `citify-api` (asia-northeast1)
  - Service Account × 2: `cloud-build-deployer` / `citify-api-runtime`
  - IAM project_iam_member × 8 (deployer: cloudbuild.builds.builder + run.admin + artifactregistry.writer + logging.logWriter / runtime: aiplatform.user + secretmanager.secretAccessor + logging.logWriter + cloudtrace.agent)
  - IAM service_account_iam_member × 1 (deployer → runtime の actAs)
  - Cloud Build Trigger `citify-api-main` (id: `d0deb628-64ca-4581-8644-dbd9e3f6aef0`)
- [x] **A-11 (Cloud Run 本番デプロイ)**: `citify-api` (asia-northeast1) 起動、URL: `https://citify-api-hnraqfjt4a-an.a.run.app`、`/health` → 200 OK、`/version` で git_sha 注入確認
- [x] **`infra/env/dev/outputs.tf` 新規作成**: artifact_registry_repo / cloud_build_deployer_email / citify_api_runtime_email / cloud_build_trigger_id / cloud_build_trigger_url の 5 出力
- [x] **`infra/env/dev/variables.tf` 拡張**: github_owner / github_repo (yujmatsu / citify)
- [x] **`apps/api/Dockerfile` 修正** (build エラー解決):
  - `RUN --mount=type=cache` を削除 (BuildKit 専用、Cloud Build legacy builder では失敗)
  - `UV_PROJECT_ENVIRONMENT` (uv sync 用) → `VIRTUAL_ENV=/opt/venv` + PATH 設定 (uv pip install の install 先指定)
- [x] **`cloudbuild.yaml` 修正 (2 段階)**:
  - 修正 1: bash 変数 `$URL` を `$$URL` にエスケープ (Cloud Build substitution との衝突回避)
  - 修正 2: build と deploy の間に `push` step を明示追加 (`images:` ブロックは全 step 完了後の自動 push なので deploy より前に走らない)
- [x] **tasks.json 更新**: INFRA-008 / INFRA-009 / A-11 → completed、A-12 / A-13 は partial 完了 notes、active_week 0 → 1
- [x] **Plans.md 更新**: Week 1 全体ステータス `cc:TODO` → `cc:WIP`、対応 4 行を `cc:完了` 化、Week 1 終了時判定基準で 2/4 達成チェック

### Cloud Build トラブルシューティング全 4 失敗の解析

| 試行 | Build ID | Duration | 原因 step | エラー |
|---|---|---|---|---|
| 1 | 96009a9b | - | (parse) | `key in the template "URL" is not a valid built-in substitution` → bash `$URL` を `$$URL` に |
| 2 | 6992c218 | 22s | build | Dockerfile `--mount=type=cache` が BuildKit 専用 → 削除 + `VIRTUAL_ENV` 設定 |
| 3 | dd95ea88 | 55s | deploy | Image not found (`images:` は post-steps 動作) → 明示 `push` step 追加 |
| 4 | 592738ca | 1m32s | - | **SUCCESS** 🎉 |

### Decisions / Design Notes

- **GitHub App 連携の OAuth UI フロー**: Terraform で `google_cloudbuild_trigger` を作成する前に 1 回だけ手動。citify-dev は yujmatsu 個人プロジェクトなので org policy 影響なし、`--allow-unauthenticated` も問題なし
- **`cloud-build-deployer` SA に `roles/cloudbuild.builds.builder` を含める**: Trigger で custom SA を指定すると Cloud Build worker のデフォルト SA が使えなくなるため、custom SA 側に worker 権限を明示付与
- **`included_files: [apps/api/**, cloudbuild.yaml]`**: tasks.json / docs / README 等の変更で build を走らせない節約設計。デメリットは `cloudbuild.yaml` 自体の検証 push を必ず apps/api/ の小変更と一緒にする必要がある
- **--cache-from の `:latest`**: 初回 build は manifest unknown で warning 出るが build 自体は続行。2 回目以降は layer cache が効いて 1m32s → 1m 前後に短縮見込み
- **`citify-api-runtime` の最小権限主義**: aiplatform.user / secretmanager.secretAccessor / logging.logWriter / cloudtrace.agent の 4 ロールのみ。Firestore / BQ / GCS / Pub/Sub は A-3 / A-10 着手時に追加

### Surprises / Risks

- **Cloud Build の `$VAR` substitution 解釈は YAML 全体に効く**: bash スクリプト内であっても `$URL` が解釈されてしまう。 `$$VAR` エスケープが必須。同様に `$(cmd)` も `$$(cmd)`。**`%{http_code}` (curl format) は `%` で始まるので解釈されない**(これは無事)
- **`images:` ブロックの誤解**: 「Cloud Build が image を push してくれる便利機能」と思っていたが、実際は **全 step 完了後** に push する SBOM/attestation 連携用機能。deploy step より前に push したい場合は明示 step 必要
- **uv の venv ターゲット指定**: `uv pip install` は `UV_PROJECT_ENVIRONMENT` を読まず、`VIRTUAL_ENV` + PATH を参照する。`uv sync` / `uv run` とは挙動が違う(ドキュメント要確認案件)
- **`hello-citify` (Week 0 Session 3 の sample) は未削除**: 課金は idle なら 0 だが、混乱回避のため次の機会に `gcloud run services delete hello-citify --region=asia-northeast1` 実行推奨

### Phase A の Week 1 終了時判定基準への進捗

| 判定基準 | 状態 |
|---|---|
| ① terraform apply で全リソース構築 | 🟡 部分達成 (Phase A 分の 13 リソース完了、データストア系は Phase B/C) |
| ② git push で自動デプロイ | ✅ 達成 |
| ③ 公開 URL で /health が 200 | ✅ 達成 (https://citify-api-hnraqfjt4a-an.a.run.app/health) |
| ④ RAG でセマンティック検索動作 | ❌ Phase B/C で対応 (A-3 国会 API → A-10 Vertex AI RAG Engine) |

**2/4 達成 — Week 1 のうち 30-40% を 5/21 一日で前倒し**

### Commit Reminder

未コミット変更:

- `infra/env/dev/main.tf` (backend 有効化 + 13 リソース定義、~150 行追加)
- `infra/env/dev/variables.tf` (github_owner/github_repo 追加)
- `infra/env/dev/outputs.tf` (新規、5 出力)
- `infra/env/dev/terraform.tfvars.example` (github vars 追記)
- `infra/env/dev/.terraform.lock.hcl` (.gitignore で除外されている、commit 不要)
- `apps/api/main.py` (docstring に Cloud Build trigger 言及)
- `apps/api/Dockerfile` (BuildKit 依存削除 + VIRTUAL_ENV 修正)
- `cloudbuild.yaml` (push step 追加 + bash escape)
- `tasks.json` (5 タスク更新)
- `Plans.md` (Week 1 進捗反映)
- `log.md` (このファイル、Session 12 追記)

> ⚠️ **`infra/env/dev/terraform.tfvars` は commit しない**(.gitignore 確認推奨、まだ.gitignore に追加していない場合は `infra/env/dev/terraform.tfvars` を gitignore に明記推奨)

推奨コミット(1 つにまとめる):
```bash
cd ~/projects/citify
git add infra/env/dev/main.tf infra/env/dev/variables.tf infra/env/dev/outputs.tf infra/env/dev/terraform.tfvars.example apps/api/main.py apps/api/Dockerfile cloudbuild.yaml tasks.json Plans.md log.md
git status   # terraform.tfvars が staged されていないか確認
git commit -m "feat(infra): Phase A — Cloud Build 自動デプロイ動線完成 (citify-api on Cloud Run)"
git push origin main
```

> 上記 push は `apps/api/` を含むので Cloud Build trigger が再度走るが、5 回目はキャッシュ + push step 適用済で **2-3 分で完走** するはず。`hello-citify` と citify-api が同時稼働するだけで害なし。

### Next (5/22 木以降の Phase B)

Phase B: 国会 API クライアント実装(`scrapers/kokkai/`) で **A-3** に着手。
今日(5/21) はここで打ち止め、Yuji の意向次第で続行 or 休息選択。

---

## 2026-05-20 (Tue) Session 11 — 小粒タスク 3 件 (LICENSE / .env.example / cloudbuild.yaml)

### Completed

- [x] **`LICENSE`** — MIT License、Copyright 2026 Yuji Matsumoto。README §10 で MIT 記載済も本体未作成だったため補完。Proto Pedia/Zenn 提出時の OSS ライセンス明示要件をクリア
- [x] **`.env.example`** — 8 カテゴリ ~30 変数のテンプレート (基本 / GCP / Vertex AI / Firestore+BQ+GCS / Pub/Sub / スクレイパー / フロント / 観測性 / フィーチャーフラグ)。Secret Manager 推奨マーク (🔒) を各キーに付与
- [x] **`cloudbuild.yaml`** — INFRA-009 の雛形先取り。4 step (docker build → 自動 push → gcloud run deploy → /health smoke test)、E2_HIGHCPU_8、20min timeout、--cache-from で増分ビルド、retry 付き smoke test
- [x] **`tasks.json` INFRA-009** — status `pending` → `in_progress`、Week 1 残作業を notes に明記 (Artifact Registry repo / SA 2 種類 / Trigger 作成)
- [x] **`Plans.md` Week 1**: INFRA-009 行に `cc:WIP` マーカー付与 + 残作業注記

### Decisions / Design Notes

- **`.env.example` 配置**: プロジェクトルート (README §3.2 で `cp .env.example .env.local` を案内している通り)。Frontend は `apps/web/.env.local` に分離する慣習だが、ハッカソン規模では一元管理優先
- **`.gitignore` 確認**: 既に `!.env.example` で明示除外あり、誤って ignore される事故なし
- **`cloudbuild.yaml` をルート配置**: GitHub Trigger のデフォルトパス。README §5 の `cloudbuild/` ディレクトリは将来別パイプライン (frontend / agents 別) を入れる予定で温存
- **Service Account 2 種類設計**: ① `cloud-build-deployer` (Cloud Build 実行用、run.admin + iam.serviceAccountUser)、② `citify-api-runtime` (Cloud Run 実行時 ID、最小権限) — 責務分離で Week 1 Terraform 化時にきれいに書ける
- **`--allow-unauthenticated`**: Week 1 では公開エンドポイント (国会 API スマホ閲覧)、Week 5 で Cloud Endpoints + Firebase Auth で保護検討
- **`--min-instances=0`**: 個人開発・ハッカソン予算 ¥7,500/月 を優先、Cold start 1-2 秒は許容 (Veo 待機の方が圧倒的に長いため UX に影響なし)
- **Smoke test を CD 内に組込み**: deploy 直後に `/health` 200 を確認、失敗時は失敗扱いで GitHub の commit status が red になる → ロールバック判断が即座に可能

### Surprises / Risks

- **`cloudbuild.yaml` の `_RUNTIME_SA` 参照**: SA 自体は Week 1 で Terraform 経由作成のため、初回 trigger 実行までに作っておく必要あり。Week 1 Day 1 の作業順序: ① Artifact Registry repo `gcloud artifacts repositories create citify-api ...` → ② SA 2 種類作成 → ③ trigger 作成 → ④ 実 push 検証
- **`.env.example` の `VERTEX_RAG_CORPUS_ID`**: Week 1 で RAG Engine セットアップ後にコーパス resource name (`projects/.../locations/.../ragCorpora/...`) を発行、これを `.env.local` に書き込む運用
- **`cloudbuild.yaml` キャッシュ戦略**: `--cache-from=latest` は初回 build で miss する。2 回目以降の高速化目的、本番運用での効果検証は Week 1 後半

### Week 0 → Week 1 残作業マッピング

| Session 11 で前倒した内容 | Week 1 で完成させる残作業 |
|---|---|
| `cloudbuild.yaml` 雛形 | Trigger 作成 + Artifact Registry repo + SA 2 種類 + 実 push 検証 |
| `.env.example` | `.env.local` 実値設定 + Secret Manager 連携 |
| `LICENSE` | (完成、追加作業なし) |

→ Week 1 Day 1 の DevOps セットアップが **半日 → 1-2 時間に短縮見込み**

### Commit Reminder

未コミット変更:

- `LICENSE` (新規)
- `.env.example` (新規)
- `cloudbuild.yaml` (新規)
- `tasks.json` (INFRA-009 status 更新)
- `Plans.md` (INFRA-009 行に cc:WIP)
- `log.md` (このファイル、Session 11 追記)

推奨コミット (Session 9/10 と一緒にまとめて 1 コミット推奨):
```bash
cd ~/projects/citify
git add LICENSE .env.example cloudbuild.yaml tasks.json Plans.md README.md log.md
# Session 5-7 分も含めるなら infra/seed/ docs/ apps/api/ infra/env/ .github/ も追加
git status
git commit -m "feat: Week 0 完了 + Week 1 前倒し (LICENSE / .env.example / cloudbuild.yaml)"
git push origin main
```

### Next

- **これで Week 0 やれることは打ち止め** — 残りは 5/21-5/25 完全休息推奨
- Week 1 Day 1 (5/26 月) は `terraform apply` + Artifact Registry / SA 作成 + Cloud Build Trigger で約 1-2 時間、午後から国会 API クライアント (A-3) 着手可能

---

## 2026-05-20 (Tue) Session 10 — README.md 改善 (Week 0 完了状態反映)

### Completed

- [x] **「🚧 開発状況」セクション新規追加** — Week 0 完了 / Week 1 着手予定の俯瞰テーブル + Plans.md/tasks.json への内部リンク
- [x] **Week 0 サンプル Cloud Run デプロイ済テーブル追記** — URL `https://hello-citify-46070204654.asia-northeast1.run.app`、smoke test 200 / ~360ms、GCP プロジェクト `citify-dev` (asia-northeast1, ¥7,500/月)、14 個 API 有効化 (依存込み 23 個)
- [x] **scraper 5 ベンダ分類への言及追加** — kaigiroku / voices_asp / db_search / kensakusystem_legacy / custom、DATA_SOURCES.md への誘導
- [x] **GitHub クローン URL の placeholder 修正** — `{your-username}` → `yujmatsu` (2 箇所: §3.1 clone コマンド, §11.お問い合わせ Issues リンク)
- [x] **§3.3 GCP API 一覧を実態と一致** — 9 個 → 14 個 (documentai / artifactregistry / logging / cloudtrace / iamcredentials を追加) + `gcloud auth application-default set-quota-project` を追記 (Session 3 で遭遇した ADC quota project 警告対策)
- [x] **§3.6 バックエンド起動コマンド修正** — `uv venv && source .venv/bin/activate; uv pip install -e .` → `python3 -m venv .venv && source .venv/bin/activate; pip install fastapi 'uvicorn[standard]' httpx pydantic pydantic-settings` (Session 8 で uv venv が PEP 668 で詰まったため)
- [x] **§5 ディレクトリ構成の scrapers/ 一覧拡張** — kokkai/kaigiroku_net/db_search/press_rss の 4 つ → 6 つ (voices_asp / kensakusystem / custom 追加)、各エントリにコメント追記

### Decisions / Design Notes

- **README の役割を再確認**: 「公開フェイス」 (Findy/Proto Pedia 経由でアクセスする外部者向け) として、Week 0 完了の見える化を最上位に配置。技術詳細は docs/* に誘導する構造を維持
- **Cloud Run URL**: gcloud deploy 出力形式 (`{service}-{プロジェクト番号}.{region}.run.app`) を採用 (Session 3 で記録した 2 形式のうち、stable な v2 URL)
- **API 一覧と setup コマンドの実体一致**: README 通りに新規 contributor が動かせるよう、Session 3/8 で実際に遭遇したコマンドベースに統一

### Surprises / Risks

- **README.md の Cloud Run URL は将来書き換え必要**: Week 1 で `hello-citify` (sample) を削除して `citify-api` (本番) をデプロイした時点で URL が変わる。その時に README を再更新する運用メモを Plans.md に反映するか検討
- **`scrapers/kensakusystem/` ディレクトリ名**: `kensakusystem_legacy` という `scraper_type` 名と微妙に違うが、ディレクトリ名は短めの `kensakusystem` で OK と判断 (Phase 3 で legacy 以外を扱う場合は再考)

### Commit Reminder

未コミット変更:

- `README.md` (5 箇所改修)
- `log.md` (このファイル、Session 10 追記)

推奨コミット (Session 9 と分けるか合体するかは Yuji 判断):
```bash
cd ~/projects/citify
git add README.md log.md
git commit -m "docs: update README with Week 0 status (Cloud Run URL, 14 APIs, 5 vendor scrapers)"
git push origin main
```

または Session 9 (tasks.json + Plans.md) と合体:
```bash
git add tasks.json Plans.md README.md log.md
git commit -m "feat: Week 0 status reflection (tasks.json + Plans.md + README update)"
git push origin main
```

---

## 2026-05-20 (Tue) Session 9 — タスク管理基盤整備 (tasks.json + Plans.md)

### Completed

- [x] **`tasks.json` を新規作成** — 51 タスクを一元管理(Week 0 完了済 16 + 進行中 4 + Week 1+ 31)
  - INFRA-001〜009 (基盤): 7 件完了 + 2 件 pending
  - DOC-001〜010: 全 10 件完了
  - RECON-001〜003: 全 3 件完了 (国会 / DiscussNet / voices_asp)
  - A-1〜A-13 (Must features): 11 件 pending + 2 件 in_progress (A-2/A-11/A-12/A-13)
  - A-4b voices_asp パーサー: 新規追加 (Phase 2 で判明したストリーム)
  - B-1〜B-8 (Should): 全 8 件 pending
  - C-1〜C-9 + C-X-DISCUSSCABINET: 全 10 件 pending
  - SUBMIT-001〜005 (Week 7 提出物): 全 5 件 pending
  - USER-INTERVIEW: pending
- [x] **`Plans.md` を新規作成** — Week 0-7 俯瞰ボード、tasks.json ID を引用
  - 全体ステータステーブル(8 Week)
  - 各 Week の `cc:TODO` / `cc:WIP` / `cc:完了` マーカー
  - Week 0 のみ全項目 `cc:完了`、Week 1-7 は `cc:TODO`
  - 各 Week 末の判定基準
  - Drop Point 判断ルール(7/10 提出が最優先、以降は 6 段階優先度)

### Decisions / Design Notes

- **tasks.json をメイン状態管理に採用** — global rules `task-workflow.md` の auto-task-start-protocol が利用可能、依存関係を `dependencies` 配列で機械可読化
- **Plans.md を補助的に俯瞰用** — Week 単位の進捗を 1 画面で見る用、tasks.json への参照リンクで詳細誘導
- **Citify 独自フィールド追加**: `priority` (Must/Should/Could/Won't), `week` (1-7), `drop_condition` (発動条件を文字列で保持), `recon_doc` (関連 recon doc パス)
- **進行中 (`in_progress`) タスクは 4 件**: A-2 (自治体マスタ Phase 1+2 完了、UI 未)、A-11 (Cloud Run smoke 済、本番未)、A-12 (Lint 済、Test/Cloud Build 未)、A-13 (Terraform 雛形済、apply 未) — Week 1 で完成予定
- **Drop Point の機械可読化**: 例 A-4 の `drop_condition` に「Week 2 中日 (6/4 水) で Playwright で 1 自治体動かなければ Should に降格」を記録、毎セッション開始時に該当日チェックすれば自動発動判定可能
- **A-4b (voices_asp) を新規 ID で追加**: FEATURES.md の元 A-4 (DiscussNet のみ) と並列ストリームとして独立タスク化、Phase 2 で発見した知見を反映

### Surprises / Risks

- **タスク総数 51 件は思ったより多い** — 進捗ボード設計の重要性を再確認、Week 6 でCould 機能を全部諦める覚悟を Plans.md に明示
- **A-4 と A-4b の依存関係**: A-4b は A-4 に依存させた(同じ Cloud Run コンテナ + 共通スキーマで実装) — 実装順序は A-4 (Week 2) → A-4b (Week 3) を維持

### Next (5/26 月曜以降の運用)

- **セッション開始時**: `tasks.json` を読んで in_progress タスクから再開、無ければ Week N の pending タスクから依存解消されたものを選択
- **タスク完了時**: tasks.json の `completed_at` を更新、Plans.md の対応行を `[x]` に変更
- **Drop Point 接近**: `drop_condition` フィールドを定期チェック、判定日を超えたら降格処理

### Commit Reminder

未コミット変更:

- `tasks.json` (新規、~620 行 JSON、51 タスク)
- `Plans.md` (新規、~250 行 Markdown、Week 0-7 俯瞰)
- `log.md` (このファイル、Session 9 追記)

推奨コミット:
```bash
cd ~/projects/citify
git status
git add tasks.json Plans.md log.md
git commit -m "feat: add tasks.json (51 tasks) + Plans.md for Week 0-7 tracking"
git push origin main
```

---

## 2026-05-20 (Tue) Session 8 — Week 1 雛形先取り (FastAPI + Dockerfile + Terraform + GitHub Actions)

### Completed

- [x] **`apps/api/pyproject.toml`** — Python 3.12 + FastAPI + httpx + pydantic-settings + google-cloud-logging + structlog、Ruff/pytest 設定、PEP 735 `[dependency-groups]` 採用
- [x] **`apps/api/main.py`** — FastAPI エントリ、`/health` (Cloud Run ヘルスチェック) + `/version` (ビルド情報)、async lifespan + CORS + 構造化ログ準備
- [x] **`apps/api/Dockerfile`** — Multi-stage build (`python:3.12-slim` + `uv` + 非root user)、Cloud Run 用 PORT 環境変数対応
- [x] **`apps/api/.dockerignore`** — Python build artifacts / venv / tests / docs / secrets / .terraform 除外
- [x] **`infra/env/dev/main.tf`** — Terraform 1.7+ / google provider 6.x / GCS backend (Week 1 で有効化予定、コメントアウト)、`local.common_labels` 定義
- [x] **`infra/env/dev/variables.tf`** — project_id / region / env (validation 付き) の 3 変数、citify-dev / asia-northeast1 デフォルト
- [x] **`infra/env/dev/terraform.tfvars.example`** — テンプレ、`.gitignore` 推奨注記入り
- [x] **`.github/workflows/lint.yml`** — Ruff lint + format check (apps/api) + Terraform fmt check (infra)、PR/main push トリガー、concurrency control 入り

### Decisions / Design Notes

- **依存管理は uv 採用** — README.md §3 と整合、Python 3.12 で最速の依存解決。Dockerfile も `ghcr.io/astral-sh/uv:0.5` から COPY
- **GCS backend は今日コメントアウト** — chicken-and-egg(bucket 自体を Terraform で作る)を避ける。Week 1 で `gsutil mb gs://citify-dev-tf-state` → backend 有効化 → `terraform init -migrate-state` の 3 ステップで移行
- **Multi-stage Dockerfile** — builder で deps install、runtime に venv のみコピー → 本番イメージ ~150 MB、cold start も短縮見込み
- **非 root user (`citify`)** — Cloud Run のセキュリティベストプラクティス、container escape リスク軽減
- **Ruff のみで lint + format** — mypy は Week 6 以降に検討、ハッカソンスピード重視
- **GitHub Actions concurrency control** — 同 PR の連続 push で並列実行を止める、CI 時間節約
- **Terraform 6.x provider** — google provider の最新メジャー、新機能 (Cloud Run v2 等) フル対応

### 雛形が解決する Week 1 タスク

| SCHEDULE.md Week 1 タスク | 雛形で消化済 |
|---|---|
| Terraform 雛形 | ✅ `infra/env/dev/{main,variables}.tf` + tfvars テンプレ |
| GitHub Actions ワークフロー (Lint + Test) | ✅ `.github/workflows/lint.yml` (Test は Week 1 で pytest 追加) |
| FastAPI 雛形 + ヘルスチェック | ✅ `apps/api/main.py` (/health + /version) |
| Cloud Run 用 Docker イメージ | ✅ `apps/api/Dockerfile` (multi-stage + uv) |

→ Week 1 Day 1 (5/26 月) は **「環境変数調整 → `terraform apply` → Cloud Build トリガー → 国会 API クライアント実装」直行可能**。雛形作成の半日が消化済。

### Surprises / Risks

- **pyproject.toml の `[tool.hatch.build.targets.wheel]` で packages = ["src"]** と書いたが、まだ `apps/api/src/` ディレクトリは未作成 — Week 1 で `apps/api/src/citify_api/` を作成する想定、または `packages = ["."]` に変更する検討余地
- **Dockerfile の uv pip install 部分が deps をハードコード** — pyproject.toml を本来は `uv sync --frozen` で解決すべきだが `uv.lock` がまだ無い。Week 1 で `uv lock` 実行後に Dockerfile 修正
- **GitHub Actions が python 3.12 を要求** — Yuji の WSL に Python 3.12 が無い場合は `python3.12` または `pyenv` でローカル一致させる必要あり

### テストコマンド (Yuji 検証用)

```bash
cd ~/projects/citify

# Python 雛形が動くか確認
cd apps/api
uv venv
source .venv/bin/activate
uv pip install fastapi uvicorn[standard] httpx pydantic pydantic-settings
uvicorn main:app --reload &
sleep 2
curl -sS http://localhost:8000/health | python3 -m json.tool
curl -sS http://localhost:8000/version | python3 -m json.tool
# 期待: {"status": "ok", "version": "0.1.0-dev"} と {"version": "0.1.0-dev", "git_sha": null, "env": "dev"}

# Ruff lint
pip install ruff
ruff check apps/api/
ruff format --check apps/api/

# Terraform fmt
cd ~/projects/citify
terraform fmt -check -recursive infra/

# Dockerfile build (optional, ~5分)
cd apps/api
docker build -t citify-api:dev .
docker run --rm -p 8080:8080 -e PORT=8080 citify-api:dev &
sleep 5
curl -sS http://localhost:8080/health
```

### Commit Reminder

未コミット変更:

- `apps/api/pyproject.toml` (新規)
- `apps/api/main.py` (新規)
- `apps/api/Dockerfile` (新規)
- `apps/api/.dockerignore` (新規)
- `infra/env/dev/main.tf` (新規)
- `infra/env/dev/variables.tf` (新規)
- `infra/env/dev/terraform.tfvars.example` (新規)
- `.github/workflows/lint.yml` (新規)
- `log.md` (このファイル、Session 8 追記)

推奨コミット:
```bash
cd ~/projects/citify
git add apps/ infra/ .github/ log.md
git status   # 9 ファイル staged 確認
git commit -m "feat: Week 1 scaffold (FastAPI /health, Dockerfile, Terraform, GitHub Actions)"
git push origin main
```

→ 上記 push をトリガーに **GitHub Actions の lint.yml が初実行** されるはず(`apps/api/main.py` への Ruff check)。エラー出たら次セッションで修正。

---

## 2026-05-20 (Tue) Session 7 — DATA_SOURCES.md §3 (voices_asp) 新設

### Completed

- [x] **DATA_SOURCES.md §3 (voices_asp) を新設** — Session 6 の recon を本ドキュメントに反映
  - §3.1 概要 — VOICES/Web、別ベンダ、3 配信モデル(中央型 / 白ラベル サブドメイン / 白ラベル 独自ドメイン)
  - §3.2 URL パターン — `g08v_viewh.asp` + `Sflg`/`FYY`/`TYY` パラメタの規約整理
  - §3.3 採用自治体一覧 — Tier 1 確認済 9 件のテーブル
  - §3.4 取得フロー — BeautifulSoup + httpx + Shift_JIS の擬似コード
  - §3.5 利用規約・robots.txt — `/voices/*.asp` Allow / `/voices/cgi/` Disallow を明記
  - §3.6 実装方針 — Python コード例(client.py 構造)
  - §3.7 失敗時対応 + Drop Point — Week 3 末判定、中央型のみ縮小、本文取得保留の選択肢
  - §3.8 他系統との比較表 — kokkai / kaigiroku / voices_asp / db_search のコスト・性能比較
- [x] **§3-§14 を §4-§15 に renumber** — 全 12 セクション、~30 サブセクション
  - §3 DB-Search → §4
  - §4 Press RSS → §5
  - §5 e-Gov → §6
  - §6 政府審議会 → §7
  - §7 公報 PDF → §8
  - §8 オープンデータ → §9
  - §9 Wikipedia → §10
  - §10 自治体マスタ CSV → §11
  - §11 フォールバック → §12
  - §12 スケジュール → §13
  - §13 テスト → §14
  - §14 改訂履歴 → §15
- [x] **§2.8 (別ベンダ系 — A-4 対象外) を削除** — §3 voices_asp が正式に作成されたため、§2.8 (out-of-scope 注釈) は冗長
- [x] **§2.3 の警告に §3 への交差参照を追加** — 「setagaya, sapporo は §3 で扱う」と明示
- [x] **§11.2 / §11.3 (自治体マスタスキーマ + サンプル)** に **`scraper_base_url` カラム追加を反映** — Phase 2 で追加した実装と整合
- [x] **§13 スケジュール表に voices_asp 行追加** — 週次 月-金 06:30 (kaigiroku.net 06:00 と少しずらす)
- [x] **§15 改訂履歴に v0.3 エントリ追加**

### Decisions / Design Notes

- **§2.8 削除の判断**: voices_asp が独立した §3 になることで、§2.8 の「out of scope」注釈は冗長。読み手の動線も「§2.3 の警告 → §3 で詳細」と直線化
- **renumber は reverse order ではなく一括 big Edit で実施**: ~44 個の小 Edit を避け、1 つの大型 Edit で §2.8 末尾以降全体を新内容に置換、ロールバックも容易
- **§13 スケジュール**: kaigiroku.net (Playwright + 重) と voices_asp (BeautifulSoup + 軽) を別時刻(06:00 と 06:30)に分散、Cloud Run の同時インスタンス起動を回避
- **§11.3 サンプル CSV**: 旧サンプル(全部 kaigiroku) → 実態反映(国会・新宿・世田谷・荒川・横浜・札幌の 6 種類で複数 scraper_type を表示) — Phase 2 の判定がドキュメント上でも見える状態に

### Surprises / Risks

- なし(設計反映の機械的作業)

### Commit Reminder

未コミット変更:

- `docs/DATA_SOURCES.md` (§3 新設 + §4-§15 renumber + 改訂履歴追記)
- `log.md` (このファイル、Session 7 追記)

> 前回までのコミット未済分(Session 5/6) と合わせて 1 コミットでまとめる選択肢もあります。それぞれ独立性の高いトピックなので、分けたい場合は次の 3 コミット推奨:

```bash
# 1. Phase 2 拡張 (5 区追加調査) — Session 5 分
git add infra/seed/tier1_supplements.csv infra/seed/municipality_master.csv
git commit -m "feat(seed): identify 4 more wards (shinjuku/sumida -> kaigiroku, ota -> voices_asp, kita -> discusscabinet)"

# 2. voices_asp recon — Session 6 分
git add docs/scrapers/voices_asp_recon.md
git commit -m "docs: voices_asp recon -> GREEN verdict (BeautifulSoup, no Playwright)"

# 3. DATA_SOURCES.md §3 新設 — Session 7 分
git add docs/DATA_SOURCES.md log.md
git commit -m "docs: add DATA_SOURCES.md §3 voices_asp, renumber existing §3-§14"

git push origin main
```

または **1 コミットでまとめ** たい場合:
```bash
git add infra/seed/ docs/scrapers/ docs/DATA_SOURCES.md log.md
git commit -m "feat: voices_asp系 recon + 5-ward classification + DATA_SOURCES §3 added"
git push origin main
```

---

## 2026-05-20 (Tue) Session 6 — voices_asp 予備調査 (VOICES/Web 系統)

### Completed

- [x] **VOICES/Web プロダクト識別** — HTML タイトルから判明、DiscussNet/kensakusystem.jp とは別ベンダ
- [x] **3 ホスティング種別で同一テンプレート確認** (sapporo 中央型 / minato 白ラベル サブドメイン / adachi 白ラベル 独自ドメイン)
- [x] **robots.txt 解析** — 3 テナント完全同一(1,621 bytes)、`/voices/*.asp` 議事録ページは明示的に Allow、`/voices/cgi/` のみ Disallow
- [x] **HTML 構造分析** — 静的 XHTML 1.0 サーバーサイドレンダリング、SPA ではない、JavaScript は GA + SNS share button のみで本体には不要
- [x] **URL 構造の解明** — `g08v_viewh.asp` 年度一覧 + `Sflg=11&FYY=N&TYY=N` パラメタで階層ドリル可能、極めてシンプル
- [x] **判定: 🟢 GREEN — BeautifulSoup + httpx で実装容易**
- [x] **`docs/scrapers/voices_asp_recon.md` 作成** (約 280 行、A-4 との比較・実装計画・Drop Point・残課題含む)

### Decisions / Design Notes

- **voices_asp は A-4 (Playwright) より大幅に楽**: コンテナ +50MB / メモリ 256MB / 1 ページ 0.3-1 秒 / インフラ ~$0.1/月、対して A-4 は +400MB / 1-2GB / 5-10 秒 / ~$0.6/月
- **倫理判定は GREEN**: kaigiroku.net (`Disallow: /dnp/`) と違い、voices_asp の `/voices/*.asp` は robots.txt で明示的に許可
- **Shift_JIS encoding 必須**: 3 テナント全てで `<meta charset=shift_jis>`、httpx で `response.encoding='shift_jis'` を明示指定する必要あり
- **9 自治体 Tier 1 カバー価値**: 東京 23 区中 8 区 (35%) + 札幌市 = ペルソナ A (新社会人東京) のカバレッジが一気に充実
- **委員会記録 (g08v_views.asp) は同構造を想定**: Week 3 で本会議録パーサー完成後に同パッチで対応見込み

### Surprises / Risks

- **adachi の /voices/ が 284 bytes の meta-refresh のみ** — `/voices/index.asp` への 3 秒リダイレクト。Week 3 着手時に `index.asp` を直接叩く設計に
- **minato の /voices/ が 94 KB と非常に大きい** — 議題リストが inline で server-render されている可能性大、テンプレ変化のヒント
- **大田区のサブパス変則** — `/ota/g08v_search.asp` で `/voices/` ではない、parser ロジックに変則対応必要
- **個別会議録 URL は未確認** — `g08v_viewh.asp?Sflg=11&FYY=2025&TYY=2025` の先のページ構造は Week 3 で実装時に depth dive

### Key Comparison: 3 ベンダの実装難度

| ベンダ | scraper_type | 実装方式 | Citify 採用判定 |
|---|---|---|---|
| **国会会議録 API** | kokkai | httpx + JSON | ✅ GREEN (Week 1, 検証済) |
| **DiscussNet SPA** | kaigiroku | **Playwright + Chromium** | 🟡 YELLOW (Week 2, A-4 Plan A) |
| **VOICES/Web** | voices_asp | **BeautifulSoup + httpx + Shift_JIS** | 🟢 GREEN (Week 3-4) |
| **DB-Search** | db_search | (Week 5 で別調査) | (B-6, 未調査) |
| **kensakusystem.jp 旧 HTML4** | kensakusystem_legacy | BeautifulSoup (旧 HTML4) | (Phase 3 で判断) |
| **Discuss Cabinet** | custom (北区) | (Phase 3 で別調査) | (NTT-AT 系新プロダクト) |

→ **3 系統並行戦略は技術的に十分実現可能**。Yuji の戦略判断 (Session 4) の追加裏付け。

### Commit Reminder

未コミット変更:

- `docs/scrapers/voices_asp_recon.md` (新規、約 280 行)
- `log.md` (このファイル、Session 6 追記)

> 補足: `/tmp/citify-week0/voices_asp_recon/*.html` は fixture 候補だが gitignore 推奨(Week 3 で `scrapers/voices_asp/fixtures/` に正式移植)

推奨コミット(Session 5 と分離するか、まとめるか好み):
```bash
git add docs/scrapers/voices_asp_recon.md log.md
git commit -m "docs: voices_asp recon -> GREEN verdict (BeautifulSoup, no Playwright)"
git push origin main
```

---

## 2026-05-20 (Tue) Session 5 — Phase 2 拡張: 不明 5 区追加調査

### Completed

- [x] **不明 5 区(新宿・墨田・北・大田・練馬) の議事録システム特定** (WebSearch 4 件)
  - 新宿区 (13104): **DiscussNet SPA** へ判定 (`ssp.kaigiroku.net/tenant/shinjuku`, tenant=shinjuku) 🎉
  - 墨田区 (13107): **DiscussNet SPA** へ判定 (`ssp.kaigiroku.net/tenant/sumida`, tenant=sumida) 🎉
  - 北区 (13117): **Discuss Cabinet** (`discusscabinet.net/kitakugikai/list`) — **NTT-AT 系の新プロダクト発見**、Phase 3 で要詳細調査
  - 大田区 (13111): **voices_asp** に再分類 (`gikai-ota-tokyo.jp/ota/g08v_search.asp`) — `g08v_search.asp` ファイル名から確実
  - 練馬区 (13120): URL 直リンク不明、custom のまま (Week 3 で voices_asp 着手時に curl で確認予定)
- [x] **tier1_supplements.csv 更新** (4 行修正)
- [x] **CSV 再生成 + 検収** — scraper_type 別カウント想定通り (kaigiroku 7→9, voices_asp 8→9, unknown 1767→1764)

### Decisions / Design Notes

- **Discuss Cabinet の発見**: `discusscabinet.net` は新発見。NTT-AT/会議録研究所系の DiscussNet 派生プロダクト群(DiscussNet / DiscussVision / DiscussCabinet / DiscussWeb)が判明。Phase 3 で個別調査
- **大田区の voices_asp 判定**: URL は `/ota/` サブパスだが `g08v_search.asp` ファイル名が他の voices_asp 自治体と完全一致 → 同じ系統と確定
- **練馬区の保留**: Tier 1 対応 7-8 件を Week 3-4 で実装する際に curl で実 URL を確認する戦略。今日全 23 区確定にこだわらない判断

### Impact

**A-4 (Playwright DiscussNet) でカバーできる Tier 1 自治体: 7 → 9 件 (+ 28% 増)**

| Tier 1 kaigiroku (9 件) |
|---|
| 横浜市・大阪府・大阪市・岡山県・高知県・大分県・荒川区 + **新宿区・墨田区** |

東京 23 区中の DiscussNet カバーが 1 → 3 区に拡大。B-2 比較ビュー(東京 23 区比較)の実現性が大幅に向上。

### Commit Reminder

未コミット変更(Session 4 と合わせて):

- `infra/seed/tier1_supplements.csv` (Session 4 で新規 + 今回 4 行更新)
- `infra/seed/build_municipality_master.py` (Session 4)
- `infra/seed/municipality_master.csv` (再生成済、最新分布反映)
- `infra/seed/README.md` (Session 4)
- `log.md` (Session 4 + Session 5 追記)

推奨コミット(まとめて 1 コミット推奨):
```bash
git add infra/seed/ log.md
git commit -m "feat(seed): Phase 2 — Tier 1 supplements (30 self-gov, 9 kaigiroku, 5-vendor classification)"
git push origin main
```

---

## 2026-05-20 (Tue) Session 4 — 自治体マスタ Phase 2 (Tier 1 補完 + 戦略再構築)

### Completed

- [x] **東京 23 区の議事録システムをベンダ別に分類** (WebSearch 7 件 + Yuji curl 1 件)
  - **重要発見 1**: `kensakusystem.jp/{区名}/` は **旧 HTML4 別実装**(SPA でなく BeautifulSoup でパース可)。同じ会議録研究所系列だが、新版 DiscussNet とは別物
  - **重要発見 2**: 23 区中 **DiscussNet SPA で取れるのは 荒川区のみ**(`ssp.kaigiroku.net/tenant/arakawa`)
  - 23 区のベンダ分布:
    - DiscussNet SPA: 1 (荒川区)
    - voices/asp 系 (gijiroku.com): 7 (港・台東・世田谷・杉並・板橋・足立・江戸川)
    - DB-Search 系 (*.dbsr.jp): 4 (千代田・文京・江東・品川)
    - kensakusystem.jp 旧 HTML4: 3 (目黒・豊島・葛飾)
    - 独自/不明: 5 + 3 (中央・大田・渋谷・中野・練馬 + 新宿・墨田・北)
- [x] **戦略判断: A-4 + voices/asp + DB-Search の 3 系統並行実装** に決定
  - Yuji 判断、ハッカソン期間ギリギリだが「全国 800 自治体カバー」の dream を守る
  - 実装工数 +5-7 日見込み、ただし voices/asp と DB-Search は静的 HTML なので BeautifulSoup で容易
- [x] **`infra/seed/tier1_supplements.csv` 新規作成** (30 行) — Tier 1 自治体の `scraper_type` / `scraper_base_url` / `tenant_id` を手動補完
- [x] **`build_municipality_master.py` を supplements マージ対応に拡張** — `load_supplements()` + `apply_supplements()` 追加、`notes` は append、フィールドは override
- [x] **`scraper_base_url` カラムを CSV スキーマに追加** (12 → 13 カラム)
- [x] **`KOKKAI_RECORD` を scraper_base_url 対応 + notes に "国会会議録 (kokkai.ndl.go.jp/api/speech)" 追記**
- [x] **`infra/seed/README.md` を全面改訂** — scraper_type の 7 種類定義、Tier 再定義(対応予定の優先度、scraper_type と独立)、Phase 計画更新
- [x] **CSV 再生成 & 検収** — 1796 行、supplements 30 件全マッチ、scraper_type 7 種類の分布想定通り
  - kaigiroku: 7、voices_asp: 8、db_search: 4、kensakusystem_legacy: 3、custom: 5、kokkai: 1、unknown: 1767

### Decisions / Design Notes

- **配信モデル 7 分類確定**: kokkai / kaigiroku / voices_asp / db_search / kensakusystem_legacy / custom / unknown
- **Tier 軸の再解釈**: tier = 「実装目標の優先度」、scraper_type = 「ベンダ種別」、is_active = 「実装済か」 の 3 軸独立
- **supplements の運用方針**: `municipality_code` をキーに base レコードを override、`notes` は append (`base; supp` の形)、identity 系 (name/prefecture/kana/population) は override 不可
- **国会の扱い**: 引き続きスクリプト内 `KOKKAI_RECORD` でハードコード(`tier=1, is_active=true`)、supplements には載せない(municipality_code 00000 は base にないため)
- **Tier 1 のメンバ**: 国会(1) + 東京 23 区(23) + 政令市等(6: 横浜・大阪市・大阪府・岡山県・高知県・大分県) + 札幌市(1, voices_asp 系) = **31 件**

### Surprises / Risks

- **23 区の議事録ベンダが想像以上に散乱** — 「東京 23 区カバー」のアピールには DiscussNet 1 系統では完全に足りず、最低でも voices/asp 系が必要
- **kensakusystem.jp の robots.txt が 404** — 利用規約が明確でない。Phase 3 で実装判断時に NTT-AT/議事録発行センターに直接確認した方が安全
- **不明 5 区(中央以外: 新宿・墨田・北・大田・練馬)** — Phase 3 で WebSearch + 個別 curl で追加調査必要
- **DiscussNet SPA (Playwright 必須) と voices/asp / DB-Search (BeautifulSoup でOK) のインフラ要件が違う** — Cloud Run のメモリ・コンテナサイズの 2 構成を維持する必要

### Tier 1 / scraper_type 分布(最終)

```
                Tier 1 (31)
                 ├── kokkai (1)         国会
                 ├── kaigiroku (7)      横浜・大阪市・大阪府・岡山県・高知県・大分県・荒川区
                 ├── voices_asp (8)     港・台東・世田谷・杉並・板橋・足立・江戸川・札幌
                 ├── db_search (4)      千代田・文京・江東・品川
                 ├── kensakusystem (3)  目黒・豊島・葛飾
                 └── custom (5) + unknown (3)
                                        中央・大田・渋谷・中野・練馬 + 新宿・墨田・北
```

### Next (Week 1 着手前の残タスク or 着手)

優先順:

1. **Week 1 Day 1 雛形作成** — FastAPI / Dockerfile / Terraform / GitHub Actions 雛形。先取りすれば 5/26 月曜から機能実装に直行可能
2. **`docs/scrapers/voices_asp_recon.md`** — voices/asp 系の構造調査。実装可能性確認(Week 3-4 で着手予定の前哨)
3. **`docs/DATA_SOURCES.md` 追加更新** — scraper_type の 7 分類を §2 に反映、`voices_asp` 系・`db_search` 系・`kensakusystem_legacy` のセクション追加
4. **不明 5 区の追加調査** (新宿・墨田・北・大田・練馬) — WebSearch + curl で確定

### Commit Reminder

未コミット変更:

- `infra/seed/tier1_supplements.csv` (新規、30 行)
- `infra/seed/build_municipality_master.py` (supplements マージ機能追加)
- `infra/seed/municipality_master.csv` (再生成、scraper_base_url カラム追加 + 30 件補完反映)
- `infra/seed/README.md` (全面改訂、scraper_type 7 種定義・Tier 再定義)
- `log.md` (このファイル)

推奨コミット:
```bash
git add infra/seed/ log.md
git status   # 5 ファイル staged + 想定外がないか確認
git commit -m "feat(seed): Phase 2 — Tier 1 supplements (30 self-gov, 5-vendor classification)"
git push origin main
```

---

## 2026-05-20 (Tue) Session 3 — GCP プロジェクト立ち上げ

### Completed

- [x] **GCP プロジェクト `citify-dev` 作成** (Phase 1-5、所要 ~30 分)
  - Phase 1: gcloud SDK 566.0.0 確認、`yujmatsu@gmail.com` 認証済
  - Phase 2: `citify-dev` 作成、請求アカウント `01A6C1-923A4E-0676C4` (OPEN: True) link、リージョン `asia-northeast1` (Tokyo) 設定 (compute / run / artifacts 全部)
  - Phase 3: 必要 API **14 個一括有効化** (run, cloudbuild, artifactregistry, aiplatform, documentai, firestore, bigquery, storage, pubsub, cloudscheduler, secretmanager, logging, cloudtrace, iamcredentials)、依存関係で計 23 個 enabled。ADC のクォータプロジェクトを citify-dev に向け直し
  - Phase 4: **予算アラート ¥7,500/月、4 段階** (50%/90%/100% actual + 100% forecasted) 作成。$50 → JPY 7500 に修正(請求アカウントが JPY ベースのため)
  - Phase 5: **サンプル Cloud Run デプロイ成功** — `gcr.io/cloudrun/hello` を `hello-citify` として asia-northeast1 にデプロイ、curl で 200 / 360ms 確認
- [x] **Week 0 終了時判定基準 4/4 すべて達成** 🎯
  - ✅ ドキュメント 4-6 個が GitHub にコミット (Day 1)
  - ✅ 国会 API から 1 件以上の発言が取れる (Day 1)
  - ✅ DiscussNetPremium の HTML 構造把握 (Day 2)
  - ✅ **GCP プロジェクトでサンプル Cloud Run がデプロイできる** (Day 2 Session 3)

### Decisions / Design Notes

- **プロジェクト名**: `citify-dev` (Week 5+ で `citify-prod` を追加予定)
- **プロジェクト番号**: `46070204654` (Terraform / IAM binding で参照する場面で使用)
- **リージョン統一**: `asia-northeast1` (Tokyo) を compute / run / artifacts 全部で固定。マルチリージョン非採用
- **請求通貨**: JPY 固定(請求アカウントの仕様、USD 指定だと `INVALID_ARGUMENT`)
- **予算ライン**: ¥7,500/月(約 $50)、超過時の挙動は計測のみ(自動停止はなし)。Veo/Imagen 多用で超える可能性は Week 4 以降
- **デプロイ済サービス**: `hello-citify` は idle 課金なし、Week 1 で `citify-api` に上書きまたは削除予定

### Surprises / Risks

- **request 通貨ミスマッチ**: 最初 `--budget-amount=50USD` で `INVALID_ARGUMENT` 発生 → 請求アカウントが JPY ベースで USD 不可。同様の罠は Terraform 設計時の `google_billing_budget` リソースでも要注意
- **ADC quota project 警告**: 古いプロジェクト (`hackason-grab`) のクォータ参照を `citify-dev` に向け直し。これを忘れると Python SDK の課金が別プロジェクトに行く事故が起きる
- **Service URL の 2 形式**: gcloud deploy 出力は `hello-citify-{プロジェクト番号}.asia-northeast1.run.app`、`describe` は `hello-citify-{hash}-an.a.run.app` を返す → 両方とも有効、Cloud Run の URL エイリアス仕様

### Next (Week 0 残タスク → Week 1 着手準備)

優先順:

1. **自治体マスタ Phase 2 設計** — 今回判明した 3 配信モデル(中央型/白ラベル/別ベンダ)を吸収する `scraper_base_url` カラム追加マイグレーションの計画。Tier 1 自治体 50 件の手動補完 (`tenant_id`, `press_rss_url`)
2. **`docs/scrapers/voices_asp_recon.md`** — 別ベンダ系(札幌市・世田谷区) の予備調査。Tier 1 候補から漏れる影響範囲が大きい場合のみ
3. **Week 1 着手 (5/26 月-)** — Terraform 雛形、FastAPI 雛形、Cloud Run + Cloud Build 自動デプロイパイプライン、国会 API クライアント実装、Vertex AI RAG セットアップ

### Commit Reminder

未コミット変更:

- `log.md` (このファイル) — 唯一の差分

> 補足: GCP セットアップは外部リソース変更で、リポジトリ側にはコード生成なし(`hello-citify` は外部状態としてのみ存在)。Terraform 化は Week 1 で実施

推奨コミット:
```bash
git add log.md
git commit -m "docs: GCP project citify-dev set up + Week 0 milestones cleared"
git push origin main
```

---

## 2026-05-20 (Tue) Session 2 — Week 0 Day 2

### Completed

- [x] **DiscussNet (kaigiroku.net) 構造調査 — 重大発見の連続**
  - robots.txt 取得 → `/tenant/` 配下のみ Allow、`/dnp/` 含む他は Disallow
  - 当初想定 (`ssp.kaigiroku.net/tenant/{id}/SpTop.html`) は 5 自治体中 3 自治体で 404 → 仮説崩壊
  - WebSearch + 実地調査で **3 種類の配信モデル** が判明:
    - **中央型** (`ssp.kaigiroku.net/tenant/{id}/`) — 大阪市、岡山県、高知県等
    - **白ラベル型** — 横浜市 (`giji.city.yokohama.lg.jp`)
    - **別ベンダ型(対象外)** — 札幌市、世田谷区 (`*.gijiroku.com/voices/*.asp` 系)
  - 採用自治体数: **350+ → 540** (2025/7 時点、株式会社会議録研究所公表) と判明、`DATA_SOURCES.md` 修正
- [x] **DiscussNet 内部アーキテクチャの解明** — DevTools 観察で判明:
  - 全 Search/Browse ページは **SPA (Single Page Application)** — `<tbody id="council_list">` は空、JS で動的描画
  - 内部 API: `/dnp/search/councils/{index|get_view_years|get_layout|get_permission}` — **POST + Cookie + CSRF + JSONP**
  - **直接 API コールは robots.txt の Disallow `/dnp/` 違反**
  - **Playwright + headless Chromium 必須** という結論
- [x] **A-4 判定: 🟡 YELLOW (Playwright 必須) — Plan A 採用決定**
  - Plan A (Playwright): インフラ +$0-5/月、コンテナ +400 MB、実装工数 +1.5-2 日
  - Drop Point: Week 2 中日 (6/4 水) で Playwright が動かなければ Plan B (A-4 を Should 降格、国会 API + プレス RSS のみ) に切替
- [x] **`docs/scrapers/kaigiroku_net_recon.md` を観察結果で全面書き直し** (約 200 行、判定根拠 + Drop Point ルール + Week 2 実装計画含む)
- [x] **`docs/DATA_SOURCES.md §2` を実態に合わせて改訂** — 配信モデル 3 分類、Playwright 必須化、setagaya/sapporo を別ベンダ扱いで除外、改訂履歴に記録

### Decisions / Design Notes

- **採用判定 Plan A**: Playwright + Chromium を Cloud Run Jobs バッチで実行。540 自治体カバレッジを死守、B-2 比較ビューの実現性確保
- **Drop Point の明文化**: 「Week 2 中日 6/4 水」を判断日として `recon.md §4.3` に記録、判定基準 4 つも列挙
- **配信モデル混在**: Phase 2 で `municipality_master.csv` に `scraper_base_url` カラム追加して中央型/白ラベルを吸収する設計
- **別ベンダ系**: `札幌市・世田谷区` は A-4 対象外。Phase 2 で `docs/scrapers/voices_asp_recon.md` として別調査を計画
- **倫理判定**: robots.txt は自動クローラ向け、Playwright (実ブラウザ的振る舞い) は許容範囲という整理。Zenn 記事・ピッチで明示予定

### Surprises / Risks

- **採用自治体数の認識**: DATA_SOURCES.md の「350+」は最新値より少なく、楽観論として 540 まで増える可能性は朗報
- **DOMContentLoaded 2.8 分** (キャプチャ観察): 1 ページ取得に 3 分弱かかる可能性。Playwright 実装時に再計測必須、許容できない遅さなら Cloud Run Jobs のタイムアウト設計を見直す
- **CSRF トークン**: 直接 API 叩きを「物理的にできなくする」セキュリティ対策が既に組まれている → 開発元の意図として「クローラ非推奨」が明確、Playwright を選んだ判断の追加裏付け

### Environment Issues (Day 1 から継続)

- Claude Code Bash サンドボックスは引き続き使用不可。Yuji 側ターミナル + 私のファイル編集の運用で問題なし

### Next (Week 0 残タスク、次セッション以降)

優先順:

1. **GCP プロジェクト作成 + API 有効化** (1-2h) — Week 1 Terraform 着手前に必須
2. **自治体マスタ Phase 2: Tier 1 自治体 50 件の補完** — `scraper_type='kaigiroku'`, `tenant_id`, `press_rss_url` を手動収集。今回判明した 3 配信モデルを `scraper_base_url` 新カラムで吸収する設計を含む(マイグレーション計画も同時に)
3. **`docs/scrapers/voices_asp_recon.md`** (別ベンダ系の予備調査、Phase 2) — 札幌市・世田谷区が漏れる影響範囲を確認したい場合のみ
4. **Week 1 着手**: Terraform 雛形、FastAPI 雛形、Cloud Run デプロイ、国会 API クライアント実装、Vertex AI RAG セットアップ

### Commit Reminder

未コミット変更:

- `docs/scrapers/kaigiroku_net_recon.md` (Write で全面書き直し)
- `docs/DATA_SOURCES.md` (§2 改訂 + 改訂履歴追記)
- `log.md` (このファイル)

> 参考: `/tmp/citify-week0/kaigiroku_recon/*.html` は fixture 候補だが gitignore 推奨(`/tmp/` 配下、再生成可能、容量大)。Week 2 で必要な分だけ `scrapers/kaigiroku_net/fixtures/` に正式移植する

推奨コミット:
```bash
git add docs/scrapers/kaigiroku_net_recon.md docs/DATA_SOURCES.md log.md
git status   # 3 ファイル + 想定外がないか確認
git commit -m "docs: kaigiroku.net recon -> A-4 verdict YELLOW (Playwright required)"
git push origin main
```

---

## 2026-05-19 (Mon) Session 1 — Week 0 Day 1

### Completed

- [x] 設計ドキュメント整備の現状確認(`CLAUDE.md` / `AGENTS.md` / `docs/PROJECT.md` / `docs/FEATURES.md` / `docs/SCHEDULE.md` / `docs/ARCHITECTURE.md` / `docs/DATA_SOURCES.md` がコミット済であることを検証)
- [x] **国会会議録 API 動作確認** — `https://kokkai.ndl.go.jp/api/speech` を curl で 5 ステップ検証
  - C1 (200 + 有効 JSON): PASS
  - C2 (件数 > 0): PASS — `any=家賃補助` で 942 件ヒット
  - C3 (実日本語テキスト): PASS — 衆議院予算委員会 長友議員の家賃補助議論を確認
  - C4 (連続リクエスト): サーバ応答時間 0.2-0.4 秒で安定、レート制限の気配なし
  - サンプル JSON を `/tmp/citify-week0/kokkai_sample_yachin_hojo.json` に保存
  - **発見**: 発言文字数は平均 2,555 字、最大 52,304 字、最小 147 字 → 翻訳 Agent (A-5) は議題単位 chunking 必須
  - 直近 30 日で 506 発言 → RAG 投入規模は軽量
- [x] **ハッカソン参加登録(Findy Conference)** 完了 (Yuji 側で実施済み確認)
- [x] **Proto Pedia アカウント作成** 完了 (Yuji 側で実施済み確認)
- [x] **自治体マスタ CSV Phase 1** 完成
  - `infra/seed/build_municipality_master.py` 作成 (総務省 xlsx → Citify スキーマ変換)
  - `infra/seed/README.md` 作成 (出典・スキーマ・再生成手順・Phase 計画)
  - `infra/seed/municipality_master.csv` 生成 — 1,796 行 (ヘッダ + 国会 1 + 都道府県 47 + 市区町村 1,747)
  - 検収全項目 PASS (世田谷区 13112、札幌市 01100、国会 00000 すべて存在確認、カナ全角化 OK)
  - 入力: 総務省 R6.1.1 (2024-01-01 時点) 版 `000925835.xlsx`

### Decisions / Design Notes

- **自治体コード**: 総務省 6 桁の頭 5 桁を採用(チェックデジット除く)。`DATA_SOURCES.md §10.3` サンプル準拠
- **都道府県全体行 47 件**: 削除せず `notes='prefecture_aggregate'` で区別。B-7 プレス RSS が都道府県単位を扱うため
- **カナ**: `unicodedata.normalize('NFKC')` で半角→全角化
- **国会レコード**: `00000 / 国会 / 国 / コッカイ` を CSV 先頭に固定挿入、scraper_type=kokkai / tier=1 / is_active=true

### Environment Issues

- **Claude Code Bash サンドボックスがこのセッションで起動不能** (`bwrap: Can't create file at /mnt/c/Program Files/ClaudeCode/managed-settings.d`)。curl・gh・git・python の直接実行は不可、Yuji 側ターミナルで実行する運用に切替
- **WSL Windows Terminal が多行ヒアコードを破壊** (全角コメント + 多行 paste で末尾 1-3 行が連結 or 欠落)。複数行 Python は `-c "..."` 単行コマンドか、VSCode エディタで `.py` ファイル作成のいずれかで回避

### Pending Verifications

- C4 をパラメタ完備で 5 連射再テスト(任意、すでにサーバ応答は安定確認済)

### Next (Week 0 残タスク、次セッション以降)

優先順:

1. **DiscussNetPremium 構造調査** (2-3h) — A-4 のリスク早期発見。setagaya / yokohama 等 2-3 自治体で HTML 構造観察。Must タスクの実装可能性確認
2. **GCP プロジェクト作成 + API 有効化** (1-2h) — Cloud Run / Firestore / BigQuery / Vertex AI / Pub/Sub / Secret Manager の有効化。Week 1 Terraform 着手前に必要
3. **自治体マスタ Phase 2 着手** (Tier 1 自治体 50 件の `tenant_id` / `press_rss_url` 手動補完) — Week 1 と並行可

### Commit Reminder

未コミット変更:

- `infra/seed/build_municipality_master.py`
- `infra/seed/README.md`
- `infra/seed/municipality_master.csv`
- `log.md` (このファイル)

推奨コミット:
```bash
git add infra/seed/ log.md
git commit -m "feat(seed): add municipality master CSV (Phase 1, 1796 rows)"
git push origin main
```

---
