"""DiscussNet (kaigiroku.net) SPA スクレイパー (A-4)。

設計方針 (docs/scrapers/kaigiroku_net_recon.md 準拠):
    - SPA + JS rendering 必須 → Playwright + headless Chromium
    - 配信モデル: 中央型 (ssp.kaigiroku.net/tenant/X/) + 白ラベル (giji.city.X.lg.jp/tenant/X/)
    - robots.txt: /tenant/ Allow, /dnp/ Disallow → 直 API 不可、SPA 経由のみ
    - レート制限: 自治体ごとに 5 秒以上推奨 (sites の負担考慮)

Tier 1 対応自治体 (Phase 2 で判明):
    - 中央型: arakawa, shinjuku, sumida, tosa, prefokayama, cityosaka
    - 白ラベル: yokohama (giji.city.yokohama.lg.jp)
"""

from .client import KaigirokuNetClient
from .schema import MeetingSummary, Speech

__all__ = ["KaigirokuNetClient", "MeetingSummary", "Speech"]
