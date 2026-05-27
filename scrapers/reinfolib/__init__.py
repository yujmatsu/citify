"""Reinfolib (不動産情報ライブラリ) scraper (Phase F)。

国土交通省 reinfolib.mlit.go.jp の Web API を叩き、街ダッシュボード用の
客観統計を取得して BQ municipality_stats に投入する。

採用 API (Phase F v0.3.1):
    - XIT001  不動産取引価格情報
    - XPT002  地価公示・地価調査
    - XGT001  指定緊急避難場所
    - XKT013  将来推計人口 250m メッシュ
    - XKT015  駅別乗降客数
    - XKT007  保育園・幼稚園
    - XKT010  医療機関
    - XKT004  小学校区
    - XKT005  中学校区

仕様書: docs/PHASE_F_REINFOLIB_v0.3.1.md
"""

SOURCE_NAME = "reinfolib"
