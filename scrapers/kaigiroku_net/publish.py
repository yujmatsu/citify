"""kaigiroku_net で取得した Speech を Pub/Sub に publish するヘルパ。

Usage (Python):
    from scrapers.kaigiroku_net.client import KaigirokuNetClient
    from scrapers.kaigiroku_net.publish import publish_speeches

    async with KaigirokuNetClient(tenant_id="prefokayama") as client:
        speeches = await client.fetch_speeches("177", "1")
        msg_ids = publish_speeches(
            project_id="citify-dev",
            topic="citify-speech-translate",
            speeches=speeches,
        )

Usage (CLI):
    python -m scrapers.kaigiroku_net publish-speeches \\
        --tenant prefokayama --council-id 177 --schedule-id 1 \\
        --project-id citify-dev --topic citify-speech-translate
"""

from __future__ import annotations

import logging

from pkg.pubsub import MessageEnvelope, PubSubPublisher

from .schema import Speech

logger = logging.getLogger(__name__)

SOURCE = "kaigiroku_net"


def publish_speeches(
    project_id: str,
    topic: str,
    speeches: list[Speech],
    publisher: PubSubPublisher | None = None,
) -> list[str]:
    """speeches を 1 件ずつ Pub/Sub に publish。返り値は message_id list。

    Args:
        project_id: GCP project ID
        topic: 送信先 topic 名 (例: 'citify-speech-translate')
        speeches: kaigiroku scraper が返した Speech list
        publisher: テスト用の mock publisher (None なら自動生成)
    """
    if not speeches:
        logger.info("publish.skip n=0")
        return []

    pub = publisher or PubSubPublisher(project_id=project_id)

    envelopes = [MessageEnvelope.wrap(SOURCE, s) for s in speeches]
    # tenant_id / council_id / schedule_id を attributes に乗せると Pub/Sub filter で
    # 自治体別 subscription を作れる (将来の最適化)。第 1 件目から拾う:
    first = speeches[0]
    attrs = {
        "tenant_id": first.tenant_id,
        "council_id": first.council_id,
        "schedule_id": first.schedule_id or "",
    }
    msg_ids: list[str] = []
    for env in envelopes:
        msg_ids.append(pub.publish_envelope(topic, env, attributes=attrs))

    logger.info(
        "publish.done topic=%s tenant=%s council=%s schedule=%s n=%d",
        topic,
        first.tenant_id,
        first.council_id,
        first.schedule_id,
        len(msg_ids),
    )
    return msg_ids
