"""国会会議録 検索 API クライアント (scrapers/kokkai/)。

国立国会図書館が公開する API (https://kokkai.ndl.go.jp/api/speech) から
発言レコードを取得する。認証不要、レート制限明示なし (推奨 1 秒間隔)。

使用例:
    from datetime import date
    from scrapers.kokkai import KokkaiClient

    async with KokkaiClient() as client:
        async for speech in client.fetch_speeches(
            from_date=date(2026, 5, 1),
            until_date=date(2026, 5, 21),
            keyword="少子化",
            max_total=10,
        ):
            print(speech.speaker, speech.speech[:80])

CLI 起動 (プロジェクトルートから):
    python -m scrapers.kokkai --query "少子化" --days 30 --max 5
"""

from .client import KokkaiClient
from .schema import SearchResponse, SpeechRecord

__all__ = ["KokkaiClient", "SearchResponse", "SpeechRecord"]
