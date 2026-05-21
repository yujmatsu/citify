"""自治体プレスリリース RSS スクレイパー (B-7、Week 2 で前倒し実装)。

設計方針:
    - 47 都道府県 + 政令市 + Tier 1 自治体の公式 RSS feed を取得
    - feedparser ライブラリで RSS 0.9-2.0 / Atom 0.3-1.0 を堅牢にパース
    - robots.txt 制約なし (RSS は公開・購読目的の standard 配信形式)
    - voices_asp で議事録 scrape できない自治体 (港・台東・世田谷 等 9 件) の
      カバレッジ救済の主目的 (recon doc voices_asp §11.7 参照)

利用フロー:
    1. municipality_master.csv の press_rss_url 列から自治体別 RSS URL 取得
    2. PressRssClient.fetch_feed(url) で RSS パース → list[PressItem]
    3. BQ citify_raw.press_items テーブル投入 (Week 5 で IaC 化)
"""

from .client import PressRssClient
from .schema import PressItem

__all__ = ["PressItem", "PressRssClient"]
