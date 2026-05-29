# ミニプラン: L + LL - 会話履歴 + Story Recall

## 概要

- **タスクID**: TASK-L-LL (バランス版 #3 / パーソナライゼーション主役)
- **目的**:
  Concierge との対話履歴を保存し、次回会話時に「3 ヶ月前のあなたの関心、今週の議題と関連がある」を能動提示する仕組み。**ペルソナ B (実家気にする層) には威力**、ハッカソン公式 RAG 技術カバーも兼ねる。

  L = 短期記憶 (今までの相談内容を覚えている)
  LL = 長期記憶 (過去関心 × 新規議題のクロスリファレンス)

- **完了条件**:
  1. `POST /v1/concierge` で受信した会話を Firestore + Vertex AI Embedding で永続化
  2. 会話保存時に user_id + timestamp + message + reply + embedding[768] を保持
  3. 新規 tool 2 つ実装 (Concierge から呼べる)
     - `recall_past_conversations(query, limit)` - 過去対話の類似検索 (L)
     - `recall_related_past_interests(limit)` - 過去関心 × 新着 scored_speeches のクロスリファレンス (LL)
  4. Concierge system prompt に過去履歴セクション (空配列なら省略) を追加、prepend する pattern
  5. `GET /v1/concierge/history/{user_id}` endpoint で UI 表示用に履歴取得
  6. Frontend: chat UI に「過去の相談履歴」ボタン追加、modal で履歴一覧表示
  7. 新規 tests ~25 + 全 170 = 195 tests pass、regression なし
  8. demo: `python -m agents.demo_concierge --persona 2` 2 回実行で 2 回目に過去履歴が context として効くことを確認

## 設計方針

### Firestore + Vertex AI Embedding hybrid

```
ConciergeAgent.respond()
   ↓ 保存 (post-process)
Firestore concierge_history collection
   doc_id: {user_id}__{timestamp_iso}
   fields:
     - user_id (string)
     - timestamp (ISO datetime)
     - message (string, user input)
     - reply (string, agent output、短縮版 max 500 chars)
     - candidates_codes (array[string])
     - matched_interests (array[string], 履歴の関心軸抽出)
     - embedding (array[float] len=768、message+reply の Vertex AI embed)
```

### 採用しない選択肢

- ❌ **Concierge 履歴専用の Vertex AI RAG Engine corpus**: corpus 作成 + import は async 30 min、demo 流動性に欠ける。**ただしハッカソン審査②「RAG 技術カバー」は既存議事録 corpus (`apps/api/rag/corpus.py`、`citify-kokkai-speeches`) で訴求済**。本タスクの会話履歴は hot storage (Firestore) で頻繁更新、議事録 RAG とは責務分離。Optional として Phase 5 で「夜間 batch で Concierge 履歴を RAG corpus へ import」追加検討
- ❌ **会話を毎回 LLM で要約してから保存**: コスト 2 倍、demo speed 落ちる
- ❌ **session 全体を保存**: token 爆発、persona ごと 1 turn = 1 doc で十分

### Story Recall (LL) のロジック

```
過去対話の matched_interests (例: ["住居", "子育て"])
   ∩
新着 scored_speeches (今日の) の matched_interests
   →
hit した interest 軸で、過去対話に絡む新規議題を提示
   "3 ヶ月前の家賃補助の相談、今週議論されました: <title>"
```

## ファイル配置

```
agents/concierge/
├── memory.py                ← 新規: Firestore + embedding I/O
├── tools.py                 ← 既存に recall_past_conversations + recall_related_past_interests を追加
├── adk_agent.py             ← tools に 2 個追加
├── runner.py                ← system prompt に履歴 context inject
├── prompts/system.py        ← 過去履歴セクション追加
└── tests/
    ├── test_memory.py       ← 新規 (~15 tests)
    └── test_tools.py        ← 既存に recall_* tests 追加 (~10 tests)

apps/api/main.py             ← /v1/concierge で auto-save 追加 + GET /v1/concierge/history/{user_id}
apps/web/src/app/concierge/
└── page.tsx                 ← 履歴 modal + 履歴ボタン追加 (Phase 4)

agents/demo_concierge.py     ← 同 user_id で 2 回呼んで履歴の効きを確認
```

## 作業ステップ (時系列)

### Phase 0: 🔴 Critical Pre-flight — 依存 + image 確認 (~1.5h)

**Plan E Phase 0 と同型問題**: Firestore + Vertex AI Embedding API を使うので、`apps/api/Dockerfile` の image にこれら client が含まれているか事前確認必須。

1. [ ] `apps/api/pyproject.toml` で `google-cloud-firestore` と `google-cloud-aiplatform` が dependency にあるか確認 (両方 reactions / RAG で既存利用、含まれているはず)
2. [ ] `apps/api/.venv/bin/python -c "from google.cloud import firestore; from vertexai.language_models import TextEmbeddingModel; print('OK')"` で local import smoke
3. [ ] Phase E の Dockerfile (build context = repo root) で `agents/concierge/memory.py` (新規) が COPY されるか確認 (agents/ は既に COPY されている → OK のはず)
4. [ ] 既存 endpoint regression check (curl /v1/cities/13104 等で /v1/concierge 経路を壊していないこと)

### Phase 1: Firestore memory layer (~4h)
5. [ ] Firestore コレクション `concierge_history` の document schema 設計確定
   - **matched_interests 抽出主体**: rule-based (固定辞書 `{"住居":["家賃","マンション","アパート"], "子育て":["保育園","待機児童","幼稚園"], ...}`) で fallback、LLM 経由はしない (Reviewer 指摘 #5)
   - **short_summary フィールド**: `reply[:100]` の先頭 100 char (純 truncate、LLM なし)
6. [ ] `agents/concierge/memory.py`: ConversationMemory class
   - `save_turn(user_id, message, reply, candidates, matched_interests)` -> doc_id
   - `recall_similar(user_id, query, limit)` -> list[HistoryRecord]
     - **直近 50 turn まで scan 制限** (Reviewer 指摘 #3、Firestore where + order_by + limit(50))
   - `recall_recent(user_id, limit)` -> list[HistoryRecord] (時系列)
   - Vertex AI text-multilingual-embedding-002 で embedding 計算
   - cosine similarity in-memory で score
7. [ ] `agents/concierge/tests/test_memory.py`: 15 tests (Firestore mock + embedding mock)
8. [ ] ruff + pytest pass

### Phase 2: Concierge 統合 (~3h)
5. [ ] `agents/concierge/tools.py` に recall 関数 2 つ追加:
   - `recall_past_conversations(args, memory=None) -> list[HistoryRecord]`
   - `recall_related_past_interests(args, memory=None, bq_client=None) -> list[CrossRefMatch]`
6. [ ] `agents/concierge/adk_agent.py` の tools list に 2 つ追加 (合計 6 tools)
7. [ ] `agents/concierge/runner.py` で recall tools の execute 分岐追加
8. [ ] `agents/concierge/prompts/system.py` に過去履歴セクション (条件付き) 追加
9. [ ] `agents/concierge/main.py` で `respond()` の post-process で memory.save_turn() を呼ぶ
10. [ ] 既存 schema (ConciergeResponse) に optional `recalled_history` フィールド追加
11. [ ] ruff + pytest pass (新規 ~10 tests in test_tools.py)

### Phase 3: API endpoint (~2h)
17. [ ] `POST /v1/concierge` で auto-save (memory.save_turn の呼び出し)
18. [ ] `GET /v1/concierge/history/{user_id}` 新規 endpoint (最新 N 件返却)
    - **認可: `x-user-id` header と path の user_id 一致チェック** (Reviewer 指摘 #4、demo 環境簡易認可)
    - 不一致なら 403 を返す。production では IAM 認証に置換予定 (今回 scope 外)
    - `?limit=20` query param (default 20、max 100)、cursor-based pagination は将来検討
19. [ ] tests in test_concierge_endpoint.py に history endpoint tests 追加 (~5 tests、認可 OK / NG 含む)
20. [ ] ローカル uvicorn smoke test

### Phase 4: Frontend (~4h)
16. [ ] `apps/web/src/lib/api.ts` に `fetchConciergeHistory()` 関数 + HistorySchema 追加
17. [ ] `apps/web/src/app/concierge/page.tsx` に 「履歴」ボタン + modal 追加
18. [ ] modal 内で過去の相談 list 表示 (timestamp + message + candidates summary)
19. [ ] 履歴の 1 件をクリックで「この話の続き」として現在の入力欄に prefill
20. [ ] Chrome 動作確認

### Phase 5: demo + commit (~2h)
21. [ ] `agents/demo_concierge.py` に history 確認モード追加 (同 user_id で 2 回 invoke)
22. [ ] 全 195 tests pass の最終確認
23. [ ] `docs/ARCHITECTURE.md` + `docs/AGENT_PROMPTS.md` 更新 (L+LL セクション追加)
24. [ ] `docs/FEATURES.md` に A-15 / A-16 追加
25. [ ] **5 commits** で push:
    - `feat(plan-l): Firestore + embedding ベース ConversationMemory`
    - `feat(plan-l): Concierge に recall_* tools 追加 + auto-save`
    - `feat(plan-l): GET /v1/concierge/history/{user_id} endpoint`
    - `feat(plan-l): Frontend に履歴 modal 追加`
    - `docs(plan-l): L+LL ドキュメント更新 + demo`

## リスク・懸念点

| # | リスク | 緩和策 |
|---|---|---|
| 1 | Vertex AI Embedding API のレイテンシ (~200ms/call) で Concierge 応答が遅くなる | save は fire-and-forget (async)、recall 時のみ block。recall は 1 call で完結 |
| 2 | Firestore document サイズ上限 (1 MB) で embedding[768] が圧迫 | float64 × 768 = 6KB、余裕。reply は 500 char に truncate |
| 3 | 過去履歴が長くなって prompt token 圧迫 | system prompt に inject する履歴は top-3 まで、各 100 chars 要約 |
| 4 | embedding 計算でコスト爆発 (大量保存時) | text-multilingual-embedding-002 は $0.00002/1k chars、月 1000 conversations で ~$0.01 |
| 5 | LL の cross-reference が常に空 | scored_speeches の matched_interests と過去会話の interests に共通要素があれば hit、demo 用に既存 BQ data で動作確認 |
| 6 | Firestore 認証 in dev | 既存の reactions エンドポイントで実績あり、同じ client を流用 |
| 7 | Cloud Run image rebuild 必要 + 依存欠落リスク | **Phase 0 で google-cloud-firestore + vertexai TextEmbeddingModel の local import smoke test** を必須化 (Plan E Phase 0 教訓) |
| 8 | `/v1/concierge/history/{user_id}` の認可欠落で他人の履歴漏洩 | Phase 3 #18 で **x-user-id header 一致チェック** 実装、不一致時 403 |
| 9 | RAG 訴求が Firestore-only と読まれて審査②減点 | ミニプラン冒頭で「議事録 RAG corpus は別途存在 (apps/api/rag/corpus.py、citify-kokkai-speeches)、L+LL は hot storage layer」と明記 |
| 10 | matched_interests 抽出が LLM 経由で save latency 増 | Phase 1 #5 で rule-based 固定辞書を default、fallback、LLM call なし |

## 工数見積もり

| Phase | 想定時間 |
|---|---|
| Phase 0 (🔴 依存 + image 確認) | 1.5 時間 |
| Phase 1 (Memory layer) | 4 時間 |
| Phase 2 (Concierge 統合) | 3 時間 |
| Phase 3 (API endpoint + 認可) | 2 時間 |
| Phase 4 (Frontend) | 4 時間 |
| Phase 5 (demo + docs + commits) | 2 時間 |
| **合計** | **16.5 時間 ≈ 2-3 営業日** |

ミニプラン 5 日想定の半分程度。Plan E でしっかり基盤ができているので効率化。

## レビュー依頼観点 (subagent 用)

1. **Vertex AI RAG Engine vs Firestore+embedding の選定**: RAG Engine の方が公式技術カバー強いが、setup コスト大。Firestore+embedding でハッカソン審査の RAG 訴求は十分か
2. **Story Recall (LL) のロジック**: matched_interests の単純交差で「過去 × 新規」を出すのは妥当か。LLM 経由で context 統合の方が良いか
3. **Concierge prompt への履歴 inject の単純さ**: 履歴 top-3 + 100 chars 要約だけで足りるか、もっと構造化すべきか
4. **API endpoint 設計**: `GET /v1/concierge/history/{user_id}` で良いか、pagination 等必要か
5. **Frontend 履歴 modal**: chat UI 内に modal を出すのと別 page に分けるのとどちらが UX 良いか
6. **コスト見積もり**: Embedding + Firestore の月コストが想定範囲か
7. **テストカバレッジ**: 25 tests で memory layer + tools + endpoint をどこまで保証できるか
