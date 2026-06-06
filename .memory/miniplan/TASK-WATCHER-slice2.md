# ミニプラン: マイ街エージェント Slice 2 (永続化 + ツール拡充)

## 概要
- **タスク ID**: TASK-WATCHER-S2
- **目的**: Slice 1 で証明した自律エージェントを本番化に近づける。発見・実行ログ・watch-list を
  Firestore に永続化し、cross-town 推論ツールを追加。①の透明性(agent_runs)も保存。
- **設計**: docs/plans/2026-06-06-machi-watch-agent-design.md (状態モデル §4)
- **完了条件**:
  - `agents/watcher/repo.py`: WatcherRepository (Firestore graceful、relevance/cache.py パターン)
    - user_watchlist (get/save) / discoveries (save batch / list) / agent_runs (save)
  - WatcherAgent.run が repo(任意注入)で discoveries + agent_runs を永続化(repo=None なら Slice1 動作維持)
  - **agent_runs に tool_calls + token_cost を記録**(①の自律証跡をデモで見せられる)
  - ツール追加: **compare_towns(codes[])**(watch街の横断比較=C軸価値)
  - watch街上限5 の enforcement
  - 12+ test 全 pass、ruff clean、既存 regression 不変
- **想定工数**: 2-2.5h

## スコープ
### IN
- repo.py: 3コレクションの graceful CRUD (mock 注入可、全 method 例外を投げず None/[]/False)
- WatcherAgent: repo 注入 → run 末尾で persist。token_cost は ADK event の usage_metadata から集計(取れなければ None)
- tools.py: compare_towns(codes) を追加(municipality_stats を複数 code 取得 → 主要指標を並べる。concierge compare 流用)
- schema: WatchInput に watched 上限5 の validator
- tests: repo CRUD / compare_towns / persist wiring / 上限5 / graceful

### OUT (後続 Slice)
- recall_user_memory / Learn ループ高度化 (後続)
- エージェントホーム UI (Slice 3) / Push Job (Slice 4)

## 設計詳細
### WatcherRepository (Firestore, relevance/cache.py 流用)
```python
FIRESTORE_WATCHLIST   = "user_watchlist"      # doc id = user_id
FIRESTORE_DISCOVERIES = "watcher_discoveries" # doc id = {user_id}__{run_id}__{idx}
FIRESTORE_RUNS        = "watcher_agent_runs"  # doc id = run_id

class WatcherRepository:
    def __init__(self, firestore_client=None): ...   # lazy client, mock 注入
    def get_watchlist(self, user_id) -> WatchInput | None
    def save_watchlist(self, w: WatchInput) -> bool
    def save_run(self, run: AgentRunLog, run_id: str) -> bool
    def save_discoveries(self, user_id, run_id, ds: list[Discovery]) -> int
    def list_discoveries(self, user_id, limit=20) -> list[Discovery]
```
全 method graceful (Firestore 障害でも例外を投げない)。

### WatcherAgent.run の persist
- `__init__(repo: WatcherRepository | None = None)`。repo=None なら永続化 skip (Slice1 互換)
- **run_id は AgentRunLog のフィールド (Reviewer High#2)**: `AgentRunLog.run_id: str` を追加、
  `_build_run_log` で uuid4 採番。これで logs↔discoveries を join 可能。doc id も run_id 一意化で衝突回避
- run 末尾: repo.save_run(run_log) → repo.save_discoveries(user_id, run_log.run_id, discoveries)
- **token_cost (Reviewer Medium#3)**: 単純加算は二重計上の恐れ → **最終 event の usage_metadata を採用**、
  取れなければ None。必須にしない (①の証跡は tool_calls で実証済)

### watch街上限 (Reviewer Medium#4: truncate、ValidationError にしない)
- graceful 思想で統一するため **all_codes() を先頭5件に truncate** (home含め5、docstring と一致)。
  ValidationError でエージェントを止めない。既存 smoke (watched 2件) は影響なし

### doc id 安全化 (Reviewer Low#5) + 並び順 (Low#6)
- repo に `_safe(s)` で user_id/run_id の `:` `/` をエスケープ
- discoveries doc に `created_at` を持たせ list_discoveries は `order_by(created_at DESC)`

### compare_towns ツール (Reviewer High#1: 新規実装、concierge流用は誤り)
```python
def compare_towns(municipality_codes: list[str]) -> list[dict]:
    \"\"\"複数の街の主要統計(人口/家賃/子育て/医療/人口増減)を並べて比較する。\"\"\"
    # watcher/tools.py に新規実装: municipality_stats を `code IN UNNEST(@codes)` で1クエリ
    # → population_total / used_apartment_median_price_man_yen / childcare_facility_count /
    #    medical_facility_count / population_change_pct を dict 配列で返す
    # codes は先頭5件に truncate。失敗は [] (graceful)。型は list[dict] (既存 watcher tool と統一)
```
※ concierge.compare_municipalities は scored_speeches per-code ループで噛み合わないため流用しない。
LLM が「気になる街同士を比べたい」時に自分で呼ぶ。

## 作業ステップ
1. [ ] repo.py: WatcherRepository (3コレクション graceful CRUD)
2. [ ] schema: WatchInput に watched 上限5 validator + run_id 用ヘルパ
3. [ ] tools.py: compare_towns 追加
4. [ ] main.py: repo 注入 + persist + token_cost 集計 + compare_towns を agent tools に追加
5. [ ] tests: repo (mock Firestore) / compare_towns (mock BQ) / persist 呼出 / 上限5 / graceful
6. [ ] ruff + 全 regression
7. [ ] smoke 再実行 (repo 注入で Firestore 保存まで確認、ユーザー)

## 成果物
- agents/watcher/repo.py + tests, tools.py / main.py / schema.py 拡張

## リスク・懸念点
| リスク | 対策 |
|---|---|
| Firestore 障害で agent 停止 | repo 全 method graceful (relevance/cache.py 同様)。persist 失敗でも discoveries は返す |
| token_cost が ADK event から取れない | 取れなければ None で記録 (必須にしない) |
| compare_towns で街数過大 | codes を上限 (例5) に truncate |
| watch上限 enforcement で既存 test 破壊 | validator は watched_codes のみ対象、home は別。既存 Slice1 test に影響なし確認 |

## Out of Scope
- recall_user_memory / Learn (後続) / ホームUI (Slice3) / Push Job (Slice4) / Veo (Phase2)
