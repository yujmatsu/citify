"""voices_asp (VOICES/Web) DiscussNet スクレイパー (A-4b)。

製品: VOICES/Web (kaigiroku.net とは別ベンダ、独自プロダクト)
判定: 🟢 GREEN (BeautifulSoup + httpx で実装容易、Playwright 不要)

設計方針 (docs/scrapers/voices_asp_recon.md 準拠):
    - 静的 XHTML サーバーサイドレンダリング、JS 不要
    - Shift_JIS encoding (httpx で explicit に指定)
    - robots.txt: /voices/*.asp Allow、/voices/cgi/ Disallow
    - 3 ホスティング: 中央型 (gijiroku.com) / 白ラベル sub / 白ラベル 独自ドメイン

Tier 1 対応自治体 (9 件):
    sapporo (中央型) / minato (白ラベル sub) / taito / setagaya / suginami /
    itabashi / adachi (白ラベル 独自) / edogawa / ota (`/ota/` 変則)
"""

from .client import VoicesAspClient
from .schema import MeetingSummary, Speech

__all__ = ["MeetingSummary", "Speech", "VoicesAspClient"]
