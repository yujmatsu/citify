# RAG_RUNBOOK.md — 地方議事録 RAG の live 化手順 (② 差別化の核)

> 現状の RAG「根拠 (関連議題)」は **国会議事録コーパスのみ**。自治体プロダクトなのに
> 看板機能が地方で機能しない、が②最大の実体ギャップ。本 runbook は地方議事録を
> RAG に載せて `/related` を地方でも機能させる手順。
>
> **判明した前提 (重要)**: 地方議事録 (kaigiroku_net) の全文は現状 **どこにも永続化されて
> いない** — Pub/Sub を流れるだけで BQ にも GCS にも残らない (7日で消える)。したがって
> 「インデックスするテキストを永続化する」ステップが live 化の前提になる。

---

## 実装済み (コード・テスト済み、実 GCP 操作不要で検証済み)

- `apps/api/rag/export.py`: 多ソース対応。`SpeechExportRow` に `source`/`municipality_code`、
  RAG doc header に `Source:`/`Municipality:` を埋め込み。`export_speeches_to_gcs(...,
  source_label=, municipality_code=)` で source 列を持たないテーブルも定数上書きで export 可能。
- `apps/api/main.py` `/related`: `_parse_rag_source_uri()` で `gs://.../{source}/{id}.txt` を
  `(speech_id, source)` に分解し、`RelatedContext.speech_id`/`source` として返す
  → フロントが出所バッジ (国会/地方) 表示 + `/feed/{speech_id}` リンク化できる。
- テスト: `apps/api/rag/tests/test_rag.py` (source/municipality header, source_label 上書き) /
  `apps/api/tests/test_related_resolution.py` (source_uri 解決)。

## 未実装 (live 化に必要な残り) — ①永続化 が本丸

### 1. 地方議事録テキストの永続化 (BQ テーブル + 取り込み)
現状 `citify_raw` に地方議事録の raw テーブルが無い。以下のいずれか:
- (推奨) `citify_curated.speech_texts(speech_id, source, municipality_code, content_text,
  meeting_date, name_of_meeting, speaker*, detail_url, ingested_at)` を Terraform で作成し、
  `citify-speech-translated` トピック (content_text をまだ保持) を購読する bq_sink を1つ追加
  (`pkg/bq_sink.py` の converter を1つ足す形。既存 scored_speeches sink と同型)。
  → 国会・地方の両方の全文が speech_id 付きで貯まる。
- (代替) `scrapers/kaigiroku_net/` に kokkai と同型の `bq_loader.py` を追加し raw 保存。

### 2. コーパスへ import (実 Vertex 操作・コスト)
```bash
# 国会 (既存、speech_id 命名で再 import すると /related リンクが解決する)
python -m apps.api.rag setup --project citify-dev --bucket citify-dev-rag-staging \
  --bq-source citify-dev.citify_raw.kokkai_speeches --display-name citify-kokkai-speeches
# 地方 (speech_texts から、source_label 付きで export → 同一 or 別コーパスへ import)
python -m apps.api.rag setup --project citify-dev --bucket citify-dev-rag-staging \
  --bq-source citify-dev.citify_curated.speech_texts --prefix municipal \
  --display-name citify-municipal-speeches
```
※ `export.py` は `source_label`/`municipality_code` 引数を持つが、CLI (`__main__.py`) には
まだ渡し口が無いので、CLI に `--source-label`/`--municipality` を足すか、export を直接呼ぶ。

### 3. /related を地方コーパスにも向ける
`RAG_CORPUS_NAME` / `RAG_CORPUS_DISPLAY_NAME` を地方コーパスに切替、または複数コーパスを
横断検索する (retrieval_query を corpus ごとに呼んで距離でマージ)。ファイル名を
**app の複合 speech_id** で命名して import すれば、`_parse_rag_source_uri` が返す speech_id が
`/feed/{speech_id}` に解決する (現在の国会コーパスは raw id 命名なので要再 import)。

### 4. スモーク検証
- 地方議題の詳細で `/related` が同一自治体/近縁テーマの地方発言を返す。
- 返却 item の `source` バッジ (国会/地方) と `speech_id` リンクが正しい。

---

## 段階の考え方 (なぜ分割したか)
`/related` の出所ラベル・解決コードと export のメタデータ化は **実 GCP 操作なしで検証できる**
ため先行実装した。テキスト永続化とコーパス import は **課金を伴う実 Vertex/BQ 操作** で、
サンドボックスでは検証できないため人間作業として runbook 化した (BQ MERGE / Firebase 認証と
同じ「検証可能コードは先行、live 操作は人間」方針)。
