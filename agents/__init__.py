"""Citify AI Agents パッケージ (Vertex AI Agent Engine + Gemini 2.5)。

各 agent 別にサブパッケージ:
    - translator  : 役所言葉 → 若者向け 3 行サマリ (A-5)
    - relevance   : ユーザー × 議題マッチング + スコアリング (A-6)
    - distributor : 配信優先度ソート + フィード生成 (A-7)
    - storyteller : Veo/Imagen メディア生成統括 (B-3/B-4、Week 4)
    - comparator  : 自治体間比較生成 (B-2、Week 4)
    - classifier  : 議題テーマ分類 (Week 5)
    - collector   : スクレイパー駆動 (Week 5)

設計方針:
    - 各 agent は単一責務、Pub/Sub で疎結合に
    - Gemini 2.5 Flash (高速、低コスト) を default、Pro は重い分析時のみ
    - response_schema で構造化出力を強制、自由形式の text 出力は最小化
    - 倫理ガードレールは PROJECT.md §5 に準拠、prompt + post-validation 二重チェック
"""
