# CLAUDE.md — Claude Code 専用 リポジトリ起動ガイド

> このファイルは、**Claude Code（Anthropic 公式 CLI）が Citify プロジェクトで作業する際に最初に読むファイル** です。Claude Code は起動時に自動でこのファイルを読み込みます。
>
> ※ 他のコーディングエージェント（Cursor, Gemini CLI, GitHub Copilot 等）は `AGENTS.md` を参照してください。

---

## 0. Citify とは

「自分の街、自分の世代の話を、60 秒で。」をビジョンに、自治体の議事録・プレスリリースを若者向けに翻訳して TikTok 風 For You フィードで届ける **マルチエージェント AI プロダクト**。

- ハッカソン: **Findy DevOps × AI Agent Hackathon 2026**
- 提出締切: **2026/7/10 23:59**
- 個人開発、Vibe Coding 前提
- **開発環境: Windows 11 + WSL2 (Ubuntu 24.04) + VSCode Remote**
  - シェルコマンドは bash 前提で書く
  - パスは Linux パス (`~/projects/citify/...`) を使う
  - PowerShell 用のコマンドは生成しない

---

## 1. 最初に必ず読むべきドキュメント (順序通り)

新しいタスクを受けたら、以下を**この順番で**読んでください：

1. **`docs/PROJECT.md`** — 北極星（ビジョン、倫理制約）
2. **`AGENTS.md`** — Coding Agent 共通ルール（技術スタック、コーディング規約）
3. **`docs/FEATURES.md`** — 該当機能の仕様（Must/Should/Could/Won't）
4. **`docs/SCHEDULE.md`** — 該当週のタスクと Drop Points
5. **タスクに応じて以下のいずれか**:
   - 設計時: `docs/ARCHITECTURE.md`
   - データ収集時: `docs/DATA_SOURCES.md`
   - エージェント実装時: `docs/AGENT_PROMPTS.md`
   - DB操作時: `docs/DATA_MODEL.md`
   - UI実装時: `docs/UI_WIREFRAMES.md`
   - インフラ時: `docs/TERRAFORM_GUIDE.md`
   - プロンプト改善時: `docs/PROMPT_VERSIONS.md`

---

## 2. Claude Code 専用ルール

### 2.1 タスク開始時のチェックリスト

新しい指示を受けたら、以下を行ってから着手：

- [ ] **docs/PROJECT.md の倫理制約**を確認した
- [ ] **docs/FEATURES.md** で該当機能の優先度と受け入れ条件を確認した
- [ ] **既存のコード**を Glob/Grep/Read で確認した（重複実装を避ける）
- [ ] **必要な依存パッケージ**は既に `pyproject.toml`/`package.json` にあるか確認した
- [ ] 不明な仕様があれば**人間に質問**する

### 2.2 Claude Code のツール使い分け

| ツール | 使うとき |
|---|---|
| **Glob** | ファイル探索: `agents/**/*.py`, `apps/web/src/**/*.tsx` |
| **Grep** | 関数・クラス・文字列の横断検索: `class TranslatorAgent`, `getUserFeed` |
| **Read** | 設計仕様の参照、既存実装の読み込み |
| **Edit** | 既存ファイルの編集（**Read 必須**） |
| **Write** | 新規ファイルの作成 |
| **Bash** | `pnpm test`, `pytest`, `terraform plan`, `gcloud ...` |
| **Agent (subagent)** | 大規模な調査（複数ファイル横断、外部リサーチ） |
| **TaskCreate/TaskUpdate** | 3 ステップ以上の複雑タスクの進捗管理 |

### 2.3 Read より先に Edit を呼ばない

`Edit` は **同一セッション内で同じファイルを Read 済み** であることが必須。新しいセッションで Edit する前に必ず Read。

### 2.4 並列実行を活用

独立したタスクは並列で：
- 複数の独立した Read
- フロント・バック・インフラの独立した実装
- 複数の Grep
- 複数の Bash（独立コマンド）

依存があるタスクは順次実行。

---

## 3. プロジェクト固有の重要ルール

### 3.1 倫理制約（最優先・絶対遵守）

```
🟥 違反したら即座にユーザーに警告し、コード生成を停止する
- 特定政党・候補者を推奨するコード/プロンプト/UIの生成禁止
- 実在政治家の顔・声・名前を含む Veo/Imagen プロンプト生成禁止
- 議事録の全文転載コード生成禁止 (要約のみ)
- AI生成コンテンツに SynthID とラベルを必ず保持
- 出力に「処方」「投票推奨」等の禁止語が含まれる場合は再生成
```

### 3.2 技術スタック (変更厳禁)

`AGENTS.md` で定義された技術スタックを変更しない。変更が必要と思ったら、必ず人間に相談する。

特に：
- Python は **3.12**、フレームワークは **FastAPI**
- フロントエンドは **Next.js 16 App Router + TypeScript**
- AI Agent は **ADK** (Agent Development Kit)
- LLM は **Gemini 2.5 Pro/Flash**

### 3.3 ファイル配置のルール

新規ファイルは必ず以下に従って配置：

| 種類 | 配置先 |
|---|---|
| エージェントロジック | `agents/{name}/main.py`, `agents/{name}/prompts/system.py` |
| スクレイパー | `scrapers/{source}/parser.py`, `scrapers/{source}/client.py` |
| FastAPI ルート | `apps/api/routes/{resource}.py` |
| Next.js ページ | `apps/web/src/app/{path}/page.tsx` |
| React コンポーネント | `apps/web/src/components/{domain}/{Component}.tsx` |
| Terraform モジュール | `infra/modules/{name}/` |
| 共有型定義 | `packages/types/` (Python は pydantic, TS は zod) |

### 3.4 既存パターンの尊重

新しいパターンを勝手に導入しない。同じ責務のコードが既に存在する場合は、それを再利用または拡張する。

---

## 4. Vibe Coding ワークフロー

### 4.1 典型的なタスクフロー

```
ユーザー: 「翻訳 Agent を実装してください」
        ↓
Claude Code:
1. docs/PROJECT.md 倫理制約を Read
2. docs/FEATURES.md で A-5 翻訳 Agent の仕様を Read
3. docs/AGENT_PROMPTS.md の "4. 翻訳 Agent" セクションを Read
4. docs/DATA_MODEL.md で TopicDoc.translated の型を Read
5. agents/translator/ の既存ファイルを Glob/Read
6. agents/translator/main.py と prompts/system.py を実装
7. pytest agents/translator/test_translator.py で動作確認
8. ユーザーに結果報告 + TaskUpdate
```

### 4.2 進捗管理

3ステップ以上のタスクは必ず TaskCreate で見える化。

```python
TaskCreate("agents/translator 実装", "翻訳エージェントの完全実装", "実装中")
TaskUpdate(taskId, "完了")
```

### 4.3 サブエージェント活用

以下の場合は subagent (`Agent` tool) を使う：
- **複数ファイル横断の大規模調査** (例: "全エージェントの Pub/Sub 連携を理解したい")
- **独立した深掘り** (例: "kaigiroku.net の HTML 構造を 5 自治体分調査")
- **長い処理に分けて context を節約したい時**

サブエージェントには PROJECT.md と AGENTS.md を必ず読ませる指示を付ける。

---

## 5. 困ったときの判断ガイド

### 5.1 仕様が曖昧

```
1. docs/FEATURES.md の該当機能の「受け入れ条件」を再読
2. docs/PROJECT.md の倫理制約を確認
3. それでも不明 → 人間に質問する (推測しない)
```

### 5.2 技術選定で迷う

```
1. AGENTS.md の「変更禁止の技術スタック」を確認
2. 既存コードに同じパターンがないか Grep
3. それでも不明 → 人間に確認
```

### 5.3 スコープが膨らみそう

```
1. docs/SCHEDULE.md の Drop Points を確認
2. 該当機能の優先度 (Must/Should/Could/Won't) を確認
3. Could/Won't なら諦める提案をユーザーに伝える
```

### 5.4 倫理的に怪しい

```
1. 即座に作業を停止
2. docs/PROJECT.md の倫理セクションを引用
3. ユーザーに承認を求める
```

---

## 6. コーディング・スタイル

### 6.1 Python

```python
# ✅ 良い例
from __future__ import annotations  # 型ヒント前方参照

import logging
from typing import Literal

logger = logging.getLogger(__name__)

class TranslatorAgent:
    """役所言葉を若者向けに平易化する Agent。

    Args:
        gemini_client: Vertex AI Gemini クライアント
        prompt_version: 使用するプロンプトバージョン (例: "v1.0")
    """

    def __init__(self, gemini_client: GeminiClient, prompt_version: str = "v1.0"):
        self.gemini = gemini_client
        self.prompt_version = prompt_version

    async def translate(self, content: TranslateInput) -> TranslatorOutput:
        # 早期 return
        if not content.content_text:
            return TranslatorOutput.empty(reason="no_content")

        # ログは必ず構造化
        logger.info("translator.start", extra={
            "request_id": content.request_id,
            "speaker": content.speaker,
        })

        # ... 処理 ...

        return result
```

### 6.2 TypeScript

```typescript
// ✅ 良い例
import { z } from 'zod';

export const TranslatedSummarySchema = z.object({
  title: z.string().max(40),
  summary: z.array(z.string().max(60)).length(3),
  tone: z.enum(['casual', 'neutral', 'formal']),
});

export type TranslatedSummary = z.infer<typeof TranslatedSummarySchema>;

/**
 * 議題の翻訳サマリを取得
 * @throws ApiError 認証エラー / ネットワークエラー
 */
export async function fetchTranslation(topicId: string): Promise<TranslatedSummary> {
  const res = await api.get(`/topics/${topicId}/translation`);
  return TranslatedSummarySchema.parse(res.data);
}
```

### 6.3 禁止事項

```
❌ ハードコード
api_key = "AIza..."   # ✗ Secret Manager 経由にする

❌ except Exception:
try:
    ...
except Exception:  # ✗ 具体的な例外で受ける
    pass

❌ print
print("debug")  # ✗ logger.info() を使う

❌ any 型
const data: any = ...  # ✗ unknown + 型ガードで絞り込む
```

---

## 7. テスト戦略

### 7.1 何を必ずテストするか

- **エージェントの入出力**: 正常系と異常系を最低 3 ケース
- **スクレイパー**: HTML fixture から構造抽出
- **API エンドポイント**: smoke test (200 が返るか)

### 7.2 何を省略してよいか

- UI コンポーネントの細かい挙動 (時間あれば Playwright E2E)
- カバレッジ 100% を目指さない (60% 目安)

### 7.3 テストの書き方

```python
# pytest を使う
@pytest.mark.asyncio
async def test_translator_housing_topic():
    # Arrange
    agent = TranslatorAgent(mock_gemini())

    # Act
    out = await agent.translate(TranslateInput(content_text="...", age_group="18-24"))

    # Assert
    assert len(out.summary) == 3
    assert all(len(s) <= 60 for s in out.summary)
```

---

## 8. デプロイの判断

### 8.1 自動デプロイ条件

- `main` ブランチへのマージ → 自動 (GitHub Actions + Cloud Build)
- PR では Lint + Test のみ実行

### 8.2 デプロイ前に Claude Code が確認すること

- [ ] テストがすべて green
- [ ] Lint が pass
- [ ] 倫理制約に違反していない (FORBIDDEN_PATTERNS チェック)
- [ ] 環境変数・シークレットがハードコードされていない
- [ ] 大規模リファクタを断りなく行っていない

### 8.3 デプロイ後

- Cloud Logging でエラーを確認
- 主要エンドポイントの smoke test (curl で 200 確認)
- 失敗していたら即 Revert

---

## 9. コミュニケーション

### 9.1 ユーザーへの報告フォーマット

```
✅ 完了: agents/translator の実装

実装内容:
- agents/translator/main.py (50 LOC)
- agents/translator/prompts/system.py (docs/AGENT_PROMPTS.md v0.1 ベース)
- agents/translator/test_translator.py (5 ケース、全 pass)

確認したこと:
- docs/PROJECT.md 倫理制約: 政治家名 blocklist 適用
- docs/FEATURES.md A-5 受け入れ条件: すべて満たした
- pytest agents/translator/ → 5 passed

次の候補タスク:
- agents/relevance の実装 (docs/FEATURES.md A-6)
- 影響度 Agent のテストデータ準備
```

### 9.2 不明点の質問フォーマット

```
🤔 質問: 影響度スコアの閾値について

docs/FEATURES.md A-6 では「スコア 50 以上の議題のみフィードに表示」とあります。
ただし docs/AGENT_PROMPTS.md 3.2 では「30-49 は弱い関連」とあり、
50 がカットオフの根拠を確認したいです。

選択肢:
A. 50 を維持 (FEATURES.md 通り)
B. 40 に下げる (記事の多様性向上)
C. ユーザー設定で可変

どれを採用しますか？
```

---

## 10. 進捗チェック

毎週金曜日、ユーザーから進捗確認を求められたら、以下を報告：

```
## 今週の進捗 (Week X)

### 完了
- ✅ FEATURES.md A-X を実装
- ✅ ...

### 進行中
- 🔄 FEATURES.md B-Y を実装中 (50%)

### 詰まっている
- ⚠️ Z で問題発生、Drop Points 該当しないか SCHEDULE.md 要確認

### 次週の計画
- [ ] ...
```

---

## 11. 緊急対応

### 11.1 本番障害

```
1. Cloud Run のリビジョンを 1 つ前にロールバック
   gcloud run services update-traffic citify-api --to-revisions=PREV=100
2. Cloud Logging で原因調査
3. 修正 → PR → マージ → 自動再デプロイ
```

### 11.2 倫理違反の発見

```
1. 即座に該当機能を offline (FEATURE_FLAGS で false に)
2. ユーザー (Yuji) に通知 — docs/PROJECT.md 倫理セクションを引用
3. 原因調査・修正・再デプロイ
```

---

## 12. 最後に

> このプロジェクトのゴールは「完璧な Citify を作る」ことではなく **「ハッカソンで受賞する Citify を 7/10 までに提出する」** こと。

判断に迷ったらこの一文に立ち返ってください。スコープ縮小の提案は躊躇なく行ってOKです。

頑張りましょう。

---

## 改訂履歴

- 2026-05-19 v0.1 初版作成
