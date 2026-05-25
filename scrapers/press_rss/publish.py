"""プレス RSS → Pub/Sub citify-speech-translate publish (B-7)。

`PressRssClient.fetch_feed()` で取得した PressItem を、kokkai と同じ Speech
envelope に詰めて translator → relevance → bq_sink パイプラインに流す。

設計:
    - source 名は "press_rss" 固定
    - payload_type は "Speech" (kaigiroku/kokkai 互換、translator worker が処理可)
    - tenant_id に 5 桁 municipality_code を直接設定 (pkg.municipality_map の規約)
    - speech_id は 'press:{municipality_code}:{press_item_id}' で衝突回避
    - press 固有メタ (category, rss_feed_url, pub_date) は extra="allow" で payload に保持
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from pkg.pubsub import MessageEnvelope, PubSubPublisher

from .client import PressRssClient

if TYPE_CHECKING:
    from .schema import PressItem

logger = logging.getLogger(__name__)

SOURCE = "press_rss"


def press_item_to_speech_payload(item: PressItem) -> dict[str, Any]:
    """PressItem → Speech-style dict (translator が読める形式)。

    Args:
        item: PressRssClient.fetch_feed() の出力 1 件
    """
    pub_date = item.pub_date
    meeting_date_str = pub_date.date().isoformat() if pub_date else None
    speech_id = f"press:{item.municipality_code}:{item.id}"

    # 翻訳対象テキスト: title + description (HTML タグ簡易除去は client 側に任せ、
    # ここでは生 description を流す → translator が要約)
    description = item.description or ""
    content_text = f"{item.title}\n\n{description}".strip()

    return {
        # Speech (kaigiroku 互換) フィールド
        "speech_id": speech_id,
        "tenant_id": item.municipality_code,  # 5 桁コード直接 (pkg.municipality_map で resolve)
        "council_id": "press",
        "schedule_id": meeting_date_str,
        "meeting_date": meeting_date_str,
        "name_of_meeting": item.category or "プレスリリース",
        "speech_order": 0,
        "speech_type": None,
        "speaker": "(プレス担当)",
        "speaker_position": "プレス担当",
        "content_text": content_text,
        "detail_url": item.link,
        # press_rss 固有メタ (extra="allow" で保持、translator は無視)
        "press_id": item.id,
        "press_title": item.title,
        "press_category": item.category,
        "press_pub_date": pub_date.isoformat() if pub_date else None,
        "press_rss_url": item.source_url,
        "press_municipality_code": item.municipality_code,
    }


def publish_press_items(
    project_id: str,
    topic: str,
    items: list[PressItem],
    publisher: PubSubPublisher | None = None,
) -> list[str]:
    """PressItem のリストを Speech envelope として publish。"""
    if not items:
        logger.info("press_rss.publish.skip n=0")
        return []

    pub = publisher or PubSubPublisher(project_id=project_id)
    msg_ids: list[str] = []

    for item in items:
        payload = press_item_to_speech_payload(item)
        envelope = MessageEnvelope(
            schema_version="v1",
            source=SOURCE,
            payload_type="Speech",
            payload=payload,
        )
        attrs = {
            "tenant_id": payload["tenant_id"],
            "council_id": payload["council_id"],
            "schedule_id": payload["schedule_id"] or "",
        }
        msg_id = pub.publish_envelope(topic, envelope, attributes=attrs)
        msg_ids.append(msg_id)

    logger.info(
        "press_rss.publish.done topic=%s n=%d (sample municipality_code=%r)",
        topic,
        len(msg_ids),
        items[0].municipality_code if items else None,
    )
    return msg_ids


async def fetch_and_publish_rss(
    project_id: str,
    topic: str,
    rss_url: str,
    municipality_code: str,
    max_items: int | None = 3,
    rate_limit_sec: float = 1.0,
    timeout_sec: float = 30.0,
    publisher: PubSubPublisher | None = None,
) -> list[str]:
    """単一 RSS URL を取得 → Speech envelope として publish。

    Args:
        municipality_code: 5 桁自治体コード (例: '13000' = 東京都)
        max_items: 取得上限 (default 3、None で全件)
    """
    async with PressRssClient(timeout_sec=timeout_sec, rate_limit_sec=rate_limit_sec) as client:
        items = await client.fetch_feed(
            rss_url=rss_url,
            municipality_code=municipality_code,
            max_items=max_items,
        )
    return publish_press_items(project_id, topic, items, publisher=publisher)


async def publish_all_prefectures(
    project_id: str,
    topic: str,
    prefecture_feeds: list[tuple[str, str]],
    max_items_per_feed: int = 3,
    rate_limit_sec: float = 1.0,
    timeout_sec: float = 30.0,
    publisher: PubSubPublisher | None = None,
) -> dict[str, int]:
    """全自治体の RSS を順次 fetch + publish。

    Args:
        prefecture_feeds: [(municipality_code, rss_url), ...] のリスト
        max_items_per_feed: 各 RSS から取得する上限件数

    Returns:
        municipality_code → publish 成功件数 (失敗 RSS は -1)
    """
    pub = publisher or PubSubPublisher(project_id=project_id)
    results: dict[str, int] = {}

    async with PressRssClient(timeout_sec=timeout_sec, rate_limit_sec=rate_limit_sec) as client:
        for muni_code, rss_url in prefecture_feeds:
            try:
                items = await client.fetch_feed(
                    rss_url=rss_url,
                    municipality_code=muni_code,
                    max_items=max_items_per_feed,
                )
                msg_ids = publish_press_items(project_id, topic, items, publisher=pub)
                results[muni_code] = len(msg_ids)
                logger.info(
                    "press_rss.publish_all.ok muni=%s n=%d url=%s",
                    muni_code,
                    len(msg_ids),
                    rss_url,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "press_rss.publish_all.fail muni=%s url=%s err=%s",
                    muni_code,
                    rss_url,
                    exc,
                )
                results[muni_code] = -1
            # rate-limit は client 側に任せず、自治体間でもクッション
            await asyncio.sleep(rate_limit_sec)

    ok = sum(1 for n in results.values() if n > 0)
    failed = sum(1 for n in results.values() if n == -1)
    logger.info(
        "press_rss.publish_all.done total=%d ok=%d failed=%d empty=%d",
        len(results),
        ok,
        failed,
        len(results) - ok - failed,
    )
    return results
