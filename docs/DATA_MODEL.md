# DATA_MODEL.md — データモデル仕様書

> Citify のデータ層 (Firestore / BigQuery / Cloud Storage / Vector Search) のスキーマ定義書。
>
> Coding Agent はデータ操作実装時、必ず該当スキーマを参照してください。

> **⚠️ 実装との整合について (2026-07 追記)**
> 本書は初期設計時のスキーマ像であり、**実装が乖離している箇所がある**。実装を正とする:
> - **BigQuery が実際のバックボーン**。フィードは `citify_curated.scored_speeches_latest`
>   (view、`speech_id`×`user_id` で最新採点を抽出)、街統計は `municipality_stats` が本体。
>   本書にこれらの記述が薄い/無い場合は実テーブル (`infra/env/dev/main.tf` の DDL) を正とする。
> - **Firestore の実コレクションは `reactions` / `reaction_counts` (絵文字値 👍🤔😢🔥) と
>   `concierge_history` / `user_watchlist` / `watcher_agent_runs` / `watcher_analyses`**。
>   本書が描く `users/{uid}` / `topics/{topicId}` / `userFeeds` や reaction enum
>   (`interesting`/`not_relevant`) は現行実装には存在しない。
> - 本書に登場する `firestore.rules` は**リポジトリに存在しない** (未実装)。
> - TTL/uid 破棄などの保持ポリシーは現状**未実装** (提出後対応)。
> コード (main.py / agents/*/schema.py / infra の DDL) と本書が食い違う場合は**コードを信じること**。

---

## 0. データストア戦略

| ストア | 用途 | 理由 |
|---|---|---|
| **Firestore** | アプリ運用データ (ユーザー、議題メタ、フィード) | リアルタイム、セキュリティルール、低レイテンシ |
| **BigQuery** | 議事録・プレス生データ、分析、ユーザー行動ログ | 時系列分析、集計、Vertex AI連携 |
| **Cloud Storage** | 動画、画像、PDF | コスト・容量、CDN配信 |
| **Vertex AI Vector Search (RAG)** | 議事録セマンティック検索 | エージェントから検索可能 |
| **Secret Manager** | API キー、外部サービス credentials | セキュリティ |

---

## 1. Firestore スキーマ

### 1.1 コレクション一覧

```
firestore-root/
├── users/{uid}                          # ユーザープロファイル
│   └── reactions/{topicId}              # ユーザーごとのリアクション
├── municipalities/{municipalityCode}    # 自治体マスタ
├── topics/{topicId}                     # 議題 (UI 表示用)
│   ├── translations/{lang}              # 翻訳版 (将来用、現在は ja)
│   └── reactionAggregations/{ageGroup}  # 集計値
├── userFeeds/{uid}                      # ユーザーごとのフィード
├── comparisons/{compId}                 # 比較ビュー結果キャッシュ
├── systemConfig/{configId}              # システム設定 (機能フラグ等)
└── promptVersions/{agentName}           # プロンプトバージョン管理
```

### 1.2 `users/{uid}` — ユーザープロファイル

```typescript
type UserDoc = {
  uid: string;                         // Firebase Auth UID
  displayName: string;
  email?: string;                      // 任意

  // 居住地情報
  postalCode: string;                  // 例: "154-0024"
  primaryMunicipalityCode: string;     // 例: "13112" 世田谷区
  registeredMunicipalities: string[];  // 最大5自治体

  // ペルソナ
  ageGroup: "18-24" | "25-29" | "30-34" | "35+";

  // 関心軸 (FEATURES.md A-1)
  interests: Array<
    | "housing" | "employment" | "marriage" | "childcare" | "tax"
    | "startup" | "disaster" | "medical" | "education" | "migration"
    | "environment" | "transport" | "elderly" | "youth"
    | "gender" | "digital"
  >;

  // 通知設定
  notifications: {
    enabled: boolean;
    weeklyDigest: { day: "mon" | "tue" | ...; time: string };  // "09:00"
    push: boolean;
  };

  // ペルソナプリセット (FEATURES.md B-8)
  personaPreset?: "freshman" | "uturn" | "migration" | "custom";

  // メタ
  onboardingCompletedAt?: Timestamp;
  lastActiveAt: Timestamp;
  createdAt: Timestamp;
  updatedAt: Timestamp;
  schemaVersion: number;               // 将来のマイグレーション対応
};
```

### 1.3 `users/{uid}/reactions/{topicId}` — ユーザーリアクション

```typescript
type ReactionDoc = {
  topicId: string;
  reaction: "interesting" | "not_relevant";   // 「気になる」or「関係なさそう」
  createdAt: Timestamp;
};
```

### 1.4 `municipalities/{municipalityCode}` — 自治体マスタ

```typescript
type MunicipalityDoc = {
  code: string;                       // "13112"
  name: string;                       // "世田谷区"
  prefecture: string;                 // "東京都"
  kana: string;
  population?: number;
  category: "prefecture" | "ordinance_designated_city" | "core_city" | "city" | "town" | "village" | "special_ward" | "national";

  // スクレイピング設定
  scraperType?: "kokkai" | "kaigiroku" | "dbsearch" | "sophia" | "none";
  scraperConfig?: {
    tenantId?: string;                // kaigiroku.net 用
    customerName?: string;            // DB-Search 用
    pressRssUrl?: string;
    openDataUrl?: string;
  };

  // 対応Tier (FEATURES.md A-2)
  tier: 1 | 2 | 3;
  isActive: boolean;

  // メタ
  createdAt: Timestamp;
  updatedAt: Timestamp;
};
```

### 1.5 `topics/{topicId}` — 議題

```typescript
type TopicDoc = {
  topicId: string;                    // 例: "tp_2026051501"
  source: "kokkai" | "kaigiroku" | "press" | "egov" | "shingikai";
  sourceId: string;                   // 元データのID (例: kokkai の speechID)
  sourceUrl: string;                  // 原典URL (必須)

  // 自治体情報
  municipalityCode: string;
  municipalityName: string;

  // 議題情報
  title: string;                      // 翻訳後のタイトル (30字以内)
  originalTitle?: string;             // 役所表記の正式タイトル
  date: string;                       // YYYY-MM-DD (議事録の日付)
  speaker?: string;                   // 発言者 (議事録の場合)
  speakerGroup?: string;              // 政党・所属

  // 分類 Agent の出力
  tags: string[];                     // ["housing", "youth"]
  primaryTag: string;
  categorySummary: string;
  audienceAge: Array<"18-24" | "25-29" | "30-34" | "35+">;

  // 翻訳 Agent の出力
  translated: {
    summary: string[];                // 3行
    glossary: Array<{term: string; definition: string}>;
    tone: "casual" | "neutral" | "formal";
  };

  // ストーリー Agent の出力 (生成済みなら)
  media?: {
    veoUrl?: string;                  // gs://citify-videos/...
    veoSignedUrl?: string;            // CDN 配信用 (24h有効)
    veoDuration?: number;
    imagenUrl?: string;
    imagenSignedUrl?: string;
  };

  // リアクション集計 (簡易版)
  aggregations?: {
    totalInteresting: number;
    totalNotRelevant: number;
    byAgeGroup: {
      "18-24": { interesting: number; notRelevant: number };
      "25-29": { interesting: number; notRelevant: number };
      "30-34": { interesting: number; notRelevant: number };
      "35+":   { interesting: number; notRelevant: number };
    };
    lastAggregatedAt: Timestamp;
  };

  // メタ
  publishedAt: Timestamp;             // フィードに掲載開始した日時
  createdAt: Timestamp;
  updatedAt: Timestamp;
  schemaVersion: number;

  // 公開フラグ
  isPublished: boolean;
  safetyChecked: boolean;             // 倫理ガード通過確認
};
```

### 1.6 `userFeeds/{uid}` — ユーザーごとのフィード

```typescript
type UserFeedDoc = {
  uid: string;
  feed: Array<{
    rank: number;                     // 1-10
    topicId: string;
    score: number;
    rationale: string;
    addedAt: Timestamp;
    shown: boolean;                   // ユーザーが既に見たか
  }>;
  generatedAt: Timestamp;
  algorithmVersion: string;           // 例: "v1.0"
};
```

### 1.7 `comparisons/{compId}` — 比較ビューキャッシュ

```typescript
type ComparisonDoc = {
  compId: string;                     // hash(municipalities + theme)
  theme: string;
  municipalityCodes: string[];        // 比較対象 (2-3個)
  result: {                            // Comparator Agent の出力
    theme: string;
    municipalities: Array<...>;
    comparison_table: Array<...>;
    neutral_observation: string;
  };
  generatedAt: Timestamp;
  expiresAt: Timestamp;               // 7日でキャッシュ無効化
};
```

### 1.8 `topics/{topicId}/reactionAggregations/{ageGroup}` — リアクション集計 (詳細版)

ホットスポット回避のため、年代別サブドキュメントに分離 (大量更新時の競合回避):

```typescript
type AggregationDoc = {
  ageGroup: "18-24" | "25-29" | "30-34" | "35+";
  interesting: number;
  notRelevant: number;
  lastUpdatedAt: Timestamp;
};
```

### 1.9 `promptVersions/{agentName}` — プロンプト管理

```typescript
type PromptVersionDoc = {
  agentName: "classifier" | "relevance" | "translator" | "comparator" | "storyteller" | "distributor";
  production: string;                 // 例: "system_v1.0.txt"
  candidate?: string;                 // A/Bテスト中
  abTest?: {
    enabled: boolean;
    splitRatio: { production: number; candidate: number };
  };
  lastUpdatedAt: Timestamp;
};
```

### 1.10 セキュリティルール

```javascript
// firestore.rules
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // users: 本人のみ読み書き可能
    match /users/{uid} {
      allow read, write: if request.auth != null && request.auth.uid == uid;

      match /reactions/{topicId} {
        allow read, write: if request.auth != null && request.auth.uid == uid;
      }
    }

    // municipalities: 全ユーザー読み取り可、書き込み不可 (管理者のみ)
    match /municipalities/{municipalityCode} {
      allow read: if request.auth != null;
      allow write: if false;  // バックエンドのみ
    }

    // topics: 全ユーザー読み取り可、書き込み不可
    match /topics/{topicId} {
      allow read: if request.auth != null && resource.data.isPublished == true;
      allow write: if false;

      match /reactionAggregations/{ageGroup} {
        allow read: if request.auth != null;
        allow write: if false;
      }
    }

    // userFeeds: 本人のみ読み取り可
    match /userFeeds/{uid} {
      allow read: if request.auth != null && request.auth.uid == uid;
      allow write: if false;
    }

    // comparisons: 全ユーザー読み取り可
    match /comparisons/{compId} {
      allow read: if request.auth != null;
      allow write: if false;
    }
  }
}
```

### 1.11 インデックス

```javascript
// firestore.indexes.json
{
  "indexes": [
    {
      "collectionGroup": "topics",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "municipalityCode", "order": "ASCENDING"},
        {"fieldPath": "publishedAt", "order": "DESCENDING"}
      ]
    },
    {
      "collectionGroup": "topics",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "tags", "arrayConfig": "CONTAINS"},
        {"fieldPath": "publishedAt", "order": "DESCENDING"}
      ]
    },
    {
      "collectionGroup": "topics",
      "queryScope": "COLLECTION",
      "fields": [
        {"fieldPath": "isPublished", "order": "ASCENDING"},
        {"fieldPath": "publishedAt", "order": "DESCENDING"}
      ]
    }
  ]
}
```

---

## 2. BigQuery スキーマ

### 2.1 データセット構成

```
citify_analytics/
├── speeches              # 国会・自治体議事録の発言単位
├── press_releases        # 自治体プレスリリース
├── topics_extracted      # 議題化されたもの (Firestore topics の同期)
├── user_events           # ユーザー行動ログ (リアクション、閲覧)
├── agent_logs            # エージェント実行ログ (LLMOps 用)
├── scraper_runs          # スクレイピング実行履歴
└── municipalities        # 自治体マスタ (Firestore からの同期)
```

### 2.2 `speeches`

```sql
CREATE TABLE citify_analytics.speeches (
  speech_id STRING NOT NULL,
  source STRING NOT NULL,                  -- 'kokkai' | 'kaigiroku' | 'dbsearch'
  municipality_code STRING NOT NULL,       -- 国会は '00000'
  meeting_id STRING,
  meeting_name STRING,
  meeting_url STRING,
  date DATE NOT NULL,
  speaker STRING,
  speaker_kana STRING,
  speaker_group STRING,
  speaker_position STRING,
  content_text STRING NOT NULL,
  word_count INT64,
  raw_json STRING,                          -- 取得時のオリジナルJSON
  fetched_at TIMESTAMP NOT NULL,
  -- 派生 (分類 Agent 後に更新)
  tags ARRAY<STRING>,
  primary_tag STRING,
  is_processed BOOL,
  processed_at TIMESTAMP
)
PARTITION BY date
CLUSTER BY municipality_code, source;
```

### 2.3 `press_releases`

```sql
CREATE TABLE citify_analytics.press_releases (
  press_id STRING NOT NULL,
  municipality_code STRING NOT NULL,
  title STRING NOT NULL,
  description STRING,
  link_url STRING NOT NULL,
  published_at TIMESTAMP NOT NULL,
  category STRING,
  raw_xml STRING,
  fetched_at TIMESTAMP NOT NULL,
  -- 派生
  tags ARRAY<STRING>,
  primary_tag STRING,
  is_processed BOOL,
  processed_at TIMESTAMP
)
PARTITION BY DATE(published_at)
CLUSTER BY municipality_code;
```

### 2.4 `topics_extracted`

Firestore の `topics` と同期。BigQuery では分析用に冗長化保持。

```sql
CREATE TABLE citify_analytics.topics_extracted (
  topic_id STRING NOT NULL,
  source STRING NOT NULL,
  municipality_code STRING NOT NULL,
  title STRING NOT NULL,
  date DATE NOT NULL,
  tags ARRAY<STRING>,
  primary_tag STRING,
  audience_age ARRAY<STRING>,
  summary_lines ARRAY<STRING>,
  has_video BOOL,
  has_image BOOL,
  is_published BOOL,
  published_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY date
CLUSTER BY municipality_code;
```

### 2.5 `user_events`

```sql
CREATE TABLE citify_analytics.user_events (
  event_id STRING NOT NULL,
  uid STRING NOT NULL,
  event_type STRING NOT NULL,              -- 'view' | 'reaction' | 'share' | 'click'
  topic_id STRING,
  reaction_value STRING,                   -- 'interesting' | 'not_relevant'
  age_group STRING,
  municipality_code STRING,
  client_meta STRUCT<
    user_agent STRING,
    locale STRING
  >,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY uid, event_type
OPTIONS (
  partition_expiration_days = 30           -- 30日でTTL (個人情報最小化)
);
```

### 2.6 `agent_logs`

```sql
CREATE TABLE citify_analytics.agent_logs (
  log_id STRING NOT NULL,
  request_id STRING NOT NULL,
  agent_name STRING NOT NULL,
  model_name STRING,
  prompt_version STRING,
  input_summary STRING,
  output_summary STRING,
  latency_ms INT64,
  token_input INT64,
  token_output INT64,
  status STRING,                           -- 'success' | 'error' | 'safety_violation'
  error_message STRING,
  created_at TIMESTAMP NOT NULL
)
PARTITION BY DATE(created_at)
CLUSTER BY agent_name, status;
```

### 2.7 `scraper_runs`

```sql
CREATE TABLE citify_analytics.scraper_runs (
  run_id STRING NOT NULL,
  source STRING NOT NULL,
  municipality_code STRING,
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  status STRING,                           -- 'success' | 'failed' | 'partial'
  records_fetched INT64,
  errors ARRAY<STRING>
)
PARTITION BY DATE(started_at)
CLUSTER BY source, municipality_code;
```

---

## 3. Cloud Storage バケット設計

### 3.1 バケット一覧

| バケット名 | 用途 | リージョン | ライフサイクル |
|---|---|---|---|
| `citify-videos` | Veo 生成動画 | asia-northeast1 | 90日で Coldline |
| `citify-images` | Imagen 生成画像 | asia-northeast1 | 永続 |
| `citify-raw-pdfs` | 自治体公報 PDF | asia-northeast1 | 永続 |
| `citify-html-fixtures` | スクレイピングテスト用 HTML | asia-northeast1 | 永続 |
| `citify-backups` | Firestore export | asia-northeast1 | 30日 |
| `citify-prompts` | Prompt versions (Storage 管理) | asia-northeast1 | 永続 |

### 3.2 パス規約

```
citify-videos/
└── topics/{topicId}/
    ├── veo_v1.mp4
    └── veo_v1.thumbnail.jpg

citify-images/
├── topics/{topicId}/
│   ├── thumbnail_1x1.png
│   └── thumbnail_16x9.png
└── stock/                            # ストック画像 (C-1 用)
    ├── housing/
    ├── youth/
    └── ...

citify-raw-pdfs/
└── {municipalityCode}/{year}/{month}/{koho_name}.pdf

citify-prompts/
├── manifest.json
├── classifier/
│   ├── system_v1.0.txt
│   └── system_v1.1.txt
└── ...
```

### 3.3 アクセス制御

- 全バケット **Uniform bucket-level access** 有効
- ユーザー向け配信は **Signed URL** (有効期限24h)
- バックエンドは IAM サービスアカウント経由
- 動画・画像にはアクセスログ ON

---

## 4. Vertex AI Vector Search (RAG)

### 4.1 インデックス

- **Index 名**: `citify-meetings`
- **次元数**: 768 (gemini-embedding-001)
- **距離メトリック**: `DOT_PRODUCT`
- **更新方式**: STREAM (ストリーミング更新可)

### 4.2 各ベクトルのメタデータ

```json
{
  "id": "speech-{speechId}",
  "embedding": [0.123, -0.456, ...],
  "metadata": {
    "source": "kaigiroku",
    "municipality_code": "13112",
    "meeting_url": "https://...",
    "date": "2026-05-15",
    "speaker": "○○議員",
    "speaker_group": "○○党",
    "primary_tag": "housing",
    "tags": ["housing", "youth"]
  }
}
```

### 4.3 検索クエリ例

```python
from google.cloud import aiplatform

def search_meetings(query_text: str, municipality_code: str | None = None, top_k: int = 5):
    embedding = generate_embedding(query_text)
    response = aiplatform.MatchingEngineIndexEndpoint.find_neighbors(
        deployed_index_id="citify-meetings-deployed",
        queries=[embedding],
        num_neighbors=top_k,
        filter=[
            {"namespace": "municipality_code", "allow_list": [municipality_code]}
        ] if municipality_code else [],
    )
    return response
```

---

## 5. データフロー (横断ビュー)

```
[外部データソース]
       │
       ▼
[Collector Agent (Python)]
       │
       ├─→ BigQuery: speeches / press_releases (生データ)
       │
       └─→ Pub/Sub: "new-content"
              │
              ▼
       [Classifier Agent]
              │
              ├─→ BigQuery: speeches / press_releases (tags 更新)
              │
              └─→ Pub/Sub: "classified"
                     │
                     ▼
              [Relevance Agent]
                     │
                     └─→ Firestore: topics/{topicId}
                            │
                            ▼
                     [Translator Agent]
                            │
                            └─→ Firestore: topics/{topicId}.translated
                                   │
                                   ▼
                            [Storyteller Agent]
                                   │
                                   ├─→ Cloud Storage: citify-videos / citify-images
                                   │
                                   └─→ Firestore: topics/{topicId}.media

[毎日 5:30 / ユーザー要求時]
              │
              ▼
       [Distributor Agent]
              │
              └─→ Firestore: userFeeds/{uid}

[BigQuery → Vector Search]
       │
       └─→ Embedding 生成バッチ (日次)
              │
              └─→ citify-meetings インデックス
```

---

## 6. データライフサイクル

| データ | 保管期間 | 削除タイミング |
|---|---|---|
| `speeches` (BigQuery) | 永続 | — |
| `press_releases` (BigQuery) | 永続 | — |
| `user_events` (BigQuery) | 30日 | TTL自動 |
| `topics` (Firestore) | 永続 | — |
| `userFeeds` (Firestore) | 30日 | TTL or 日次クリーン |
| `comparisons` (Firestore) | 7日 | TTL |
| `agent_logs` (BigQuery) | 90日 | TTL |
| `scraper_runs` (BigQuery) | 90日 | TTL |
| Veo videos | 90日 → Coldline | 自動 |
| Imagen images | 永続 | — |
| Firestore exports (バックアップ) | 30日 | 自動 |

---

## 7. シードデータ (開発・テスト用)

### 7.1 自治体マスタ CSV

`infra/seed/municipality_master.csv` (DATA_SOURCES.md 参照)

### 7.2 デモ用ユーザー

```typescript
// infra/seed/demo_users.ts
export const DEMO_USERS = [
  {
    uid: "demo-aoki-22",
    displayName: "デモ青木 (22歳)",
    postalCode: "154-0024",
    primaryMunicipalityCode: "13112",
    registeredMunicipalities: ["13112", "13104"],
    ageGroup: "18-24",
    interests: ["housing", "employment", "startup"],
  },
  {
    uid: "demo-tanaka-26",
    displayName: "デモ田中 (26歳)",
    postalCode: "150-0011",
    primaryMunicipalityCode: "13113",
    registeredMunicipalities: ["13113", "27100"],  // 自分の街+実家
    ageGroup: "25-29",
    interests: ["childcare", "elderly", "tax"],
  },
  {
    uid: "demo-yamada-29",
    displayName: "デモ山田 (29歳)",
    postalCode: "100-0004",
    primaryMunicipalityCode: "13101",
    registeredMunicipalities: ["13101", "01100", "47201"],  // 引越し検討
    ageGroup: "25-29",
    interests: ["migration", "startup", "environment"],
    personaPreset: "migration",
  },
];
```

### 7.3 シード用議題 (フォールバック)

スクレイピング前にUIの動作確認できるよう、20件程度の議題サンプルを `infra/seed/sample_topics.json` に保持。

---

## 8. プライバシー実装

### 8.1 ユーザー削除フロー

```python
# apps/api/services/user_deletion.py

async def delete_user(uid: str) -> None:
    # 1. Firestore: users/{uid} とサブコレクションを再帰削除
    await firestore_recursive_delete(f"users/{uid}")

    # 2. Firestore: userFeeds/{uid} 削除
    await firestore.collection("userFeeds").document(uid).delete()

    # 3. BigQuery: user_events から削除 (パーティション内検索)
    await bq.query(f"DELETE FROM citify_analytics.user_events WHERE uid = '{uid}'")

    # 4. Firebase Auth: ユーザー削除
    await firebase_auth.delete_user(uid)

    # 5. 監査ログ
    logger.info("user.deleted", extra={"uid": uid})
```

### 8.2 PII 最小化

- 住所は **郵便番号レベル** まで (番地不要)
- リアクションは **匿名集計後 uid 廃棄** (1時間ごと)
- ログは **30日でTTL自動削除**

---

## 9. データバックアップ戦略

- **Firestore**: Managed Export を **毎日 02:00** に Cloud Storage `citify-backups` へ
- **BigQuery**: Time Travel (7日デフォルト) + 重要テーブルは月次スナップショット
- **Cloud Storage**: バージョニング有効化 (citify-prompts のみ)

---

## 10. データモデル変更時の方針

- すべての Firestore ドキュメントに `schemaVersion: number` を持たせる
- スキーマ変更時は **マイグレーション Cloud Run Job** で対応
- BigQuery テーブルはバージョン付きで新規作成し、徐々に移行

---

## 11. 改訂履歴

- 2026-05-19 v0.1 初版作成
