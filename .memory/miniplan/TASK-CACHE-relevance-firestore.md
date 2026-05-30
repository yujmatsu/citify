# ミニプラン: Relevance Score Caching (Firestore)

## 概要

- **タスク ID**: TASK-CACHE
- **目的**: 同じ `(speech_id, user_id)` の組合せに対する relevance スコアを Firestore にキャッシュし、再 publish-all 時 + persona 追加時 + cron 実行時の **Vertex AI Gemini quota 節約** + **コスト削減**。今回の 429 RESOURCE_EXHAUSTED 再発防止の保険。
- **完了条件**:
  - `agents/relevance/cache.py` 新規:`RelevanceCacheRepository` クラス
  - Firestore collection: `relevance_score_cache`、doc ID: `{speech_id}__{user_id}`
  - Worker 統合:`agents/relevance/worker.py` の handler で cache lookup → miss なら LLM call → 結果 save
  - Partial hit 対応: 3 persona 中 2 hit / 1 miss なら missing persona のみ score_multi (token 削減)
  - Cache failure は graceful (book-keeping のみ、publish 自体は影響なし)
  - TTL: 7 日 (Firestore TTL policy で自動削除)
  - 8+ unit/integration test、既存 438 件と合わせて全 pass
  - docs/AGENT_PROMPTS.md §0.4 影響度 Agent に caching 節追加
- **想定工数**: 2-2.5h

---

## 設計

### Cache Repository

```python
# agents/relevance/cache.py

FIRESTORE_COLLECTION_CACHE = "relevance_score_cache"
DEFAULT_TTL_DAYS = 7
PROMPT_VERSION = "v1.0"  # 将来 prompt 変更時に invalidate 可能

@dataclass
class RelevanceCacheEntry:
    speech_id: str
    user_id: str
    output: PersonaRelevanceOutput
    cached_at: datetime
    expires_at: datetime  # Firestore TTL field
    prompt_version: str = PROMPT_VERSION

class RelevanceCacheRepository:
    def __init__(self, firestore_client=None, ttl_days=DEFAULT_TTL_DAYS):
        ...

    def _make_doc_id(self, speech_id: str, user_id: str) -> str:
        # Firestore doc ID は `/` 禁止、`:` は許可だが安全側で escape
        safe_speech = speech_id.replace(":", "_").replace("/", "_")
        return f"{safe_speech}__{user_id}"

    def get_cached(self, speech_id: str, user_id: str) -> PersonaRelevanceOutput | None:
        """1 件 lookup。miss は None。Firestore 失敗時も graceful (None)。

        Reviewer Medium 反映: doc の `prompt_version` が現行 PROMPT_VERSION と
        不一致なら **miss 扱い** (古い prompt の score を配信しないため)。
        """

    def batch_get(
        self, speech_id: str, user_ids: list[str]
    ) -> dict[str, PersonaRelevanceOutput]:
        """N persona 一括 lookup。返り値は hit したものだけの dict。

        Reviewer Medium 反映: client.get_all([doc_ref, ...]) で 1 往復取得し N+1 を回避。
        prompt_version 不一致の doc は dict に含めない (= miss 扱い)。
        """

    def save(self, speech_id: str, user_id: str, output: PersonaRelevanceOutput) -> bool:
        """書き込み。failure は graceful (False return、例外は raise しない)。"""

    def batch_save(
        self, speech_id: str, persona_outputs: list[tuple[str, PersonaRelevanceOutput]]
    ) -> int:
        """N persona 一括書き込み。成功件数を返す。Firestore batch write 使用。"""
```

### Worker 統合 (agents/relevance/worker.py)

**Reviewer Critical 反映**: 既存 signature `make_handler(agent, publisher, output_topic, personas)` を維持し末尾に `cache` 追加。

```python
def make_handler(
    agent: RelevanceAgent,
    publisher: PubSubPublisher,
    output_topic: str,
    personas: list[UserPersona],
    cache: RelevanceCacheRepository | None = None,  # 新規 (末尾追加、後方互換)
) -> Callable:
    def handler(envelope: MessageEnvelope) -> None:
        ...
        speech_id = envelope.speech_id

        # Phase 1: Cache lookup (cache が設定済の場合のみ)
        cached_outputs: dict[str, PersonaRelevanceOutput] = {}
        if cache is not None:
            cached_outputs = cache.batch_get(
                speech_id, [p.user_id for p in personas]
            )
            logger.info(
                "relevance.cache.lookup speech_id=%s hit=%d/%d",
                speech_id, len(cached_outputs), len(personas),
            )

        # Phase 2: Cache miss の persona だけ LLM call
        missing_personas = [p for p in personas if p.user_id not in cached_outputs]

        if missing_personas:
            rel_input = _envelope_to_relevance_input(envelope, missing_personas[0])
            new_outputs = agent.score_multi(rel_input, missing_personas)

            # Cache に save (fire-and-forget、failure は log のみ)
            if cache is not None:
                cache.batch_save(
                    speech_id,
                    [(p.user_id, out) for p, out in zip(missing_personas, new_outputs)],
                )

            for p, out in zip(missing_personas, new_outputs):
                cached_outputs[p.user_id] = out

        # Phase 3: Persona 順に並び替えて publish
        for persona in personas:
            p_out = cached_outputs[persona.user_id]
            score = p_out.to_relevance_output()
            ...  # 既存の publish ロジック
```

### Pydantic schema (Firestore I/O)

cache entry を doc に保存する時の field:

```json
{
  "speech_id": "衆議院:221:第4号:60",
  "user_id": "demo-25-29",
  "relevance_output": {
    "relevance_score": 80,
    "score_topic": 25,
    "score_age": 20,
    "score_geographic": 15,
    "score_urgency": 20,
    "matched_interests": ["住居", "税"],
    "reasoning": "...",
    "tone": "casual"
  },
  "cached_at": "2026-05-30T14:00:00Z",
  "expires_at": "2026-06-06T14:00:00Z",
  "prompt_version": "v1.0"
}
```

Firestore TTL: `expires_at` field を TTL policy 対象に設定 (Terraform or gcloud で別途設定、本タスクは scope 外)

### Cache disable 戦略

- `cache: RelevanceCacheRepository | None = None` で **optional**
- Worker entry point (`__main__.py`) で env var `RELEVANCE_CACHE_ENABLED=true` の時のみ初期化
- 既存テストは cache=None で従来通り動作 (regression 防止)

### Idempotency / Race condition

- 同じ (speech_id, user_id) を複数 worker task が同時処理する場合: 両方 cache miss → 両方 LLM call → 後勝ち save (problem なし、final state は最後の save)
- Cache key (`speech_id_user_id`) は deterministic、衝突なし

---

## 作業ステップ

### Phase 1 (60 分): cache.py 実装

1. [ ] `agents/relevance/cache.py` 新規
2. [ ] `RelevanceCacheEntry` dataclass + `RelevanceCacheRepository` class
3. [ ] `get_cached` / `batch_get` / `save` / `batch_save` メソッド
4. [ ] Firestore client lazy init (テスト用 DI)
5. [ ] `_make_doc_id` でエスケープ

### Phase 2 (45 分): worker.py 統合

6. [ ] `make_handler` に `cache` parameter 追加 (default None)
7. [ ] handler 内で cache lookup → partial hit → LLM call → save の 3 phase 実装
8. [ ] `__main__.py` で env var `RELEVANCE_CACHE_ENABLED` チェック + cache 初期化

### Phase 3 (60 分): tests

9. [ ] `agents/relevance/tests/test_cache.py` 新規 (6 test):
   - cache hit / miss
   - batch_get partial result (get_all mock)
   - save graceful failure (Firestore down) + get_cached graceful failure
   - doc_id エスケープ (`:` → `_`、`/` → `_`、`__` 含む speech_id でも衝突しない)
   - TTL field が `expires_at` に正しく設定される
   - **prompt_version 不一致は miss 扱い** (Reviewer Medium)
10. [ ] `agents/relevance/tests/test_worker.py` 追加 (2 test):
   - cache 全 hit で score_multi が **呼ばれない** (assert_not_called、Reviewer High)
   - cache partial hit で missing_personas のみ score_multi (呼び出し persona 数を検証)

### Phase 4 (15 分): docs + final check

11. [ ] `docs/AGENT_PROMPTS.md` §0.4 (影響度 Agent) に caching 節追加
12. [ ] `ruff format/check` + 全 backend regression (438 + 新規 8+ = 446+)
13. [ ] 推奨 commit 提示

---

## 成果物

- [ ] `agents/relevance/cache.py` (新規、~250 lines)
- [ ] `agents/relevance/worker.py` 修正 (handler 拡張)
- [ ] `agents/relevance/__main__.py` 修正 (env-based cache 初期化)
- [ ] `agents/relevance/tests/test_cache.py` (新規、8+ test)
- [ ] `agents/relevance/tests/test_worker.py` 追記 (2+ test)
- [ ] `docs/AGENT_PROMPTS.md` 更新

## リスク・懸念点

| リスク | 影響 | 対策 |
|---|---|---|
| Firestore TTL 設定が手動 | 古い cache が残る | docs に Terraform / gcloud 設定例を記載 (本タスク scope 外だが指示明記) |
| Prompt 変更時に古い cache が hit | 古い score 配信 | `prompt_version` field で invalidate 可能、変更時は手動 collection flush |
| Cache 障害で全 worker 死亡 | publish 停止 | 全 method を graceful (False/None return、例外は logger.warning) |
| Firestore quota 超過 | cache 機能停止 | graceful 動作 + Firestore は relevance より cost 桁低 (read/write daily 50K free tier 内) |
| 既存 557 test が壊れる | regression | cache=None default で後方互換、既存 worker test は cache 無効で動作 |
| 同一 (speech_id,user_id) 並行 worker で重複 LLM call + 重複 write | quota 微増 | deterministic key で後勝ち save、final state は一貫。重複 write は Firestore free tier 内で許容 (Reviewer Medium) |

---

## Out of Scope

- Firestore TTL policy の Terraform 設定 (docs のみ、別 task で実装)
- Cache hit rate モニタリング (Cloud Monitoring metrics、production 化時)
- Translator / Distributor の caching (Relevance だけ実装、他は cost 低)
- Cache invalidate API (collection flush は手動 gcloud で OK)
