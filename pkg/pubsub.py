"""Google Cloud Pub/Sub の薄いラッパ (Citify エージェントパイプライン用)。

設計方針:
    - google-cloud-pubsub への import を遅延化 (テストで mock 注入可能)
    - JSON envelope を強制: {"schema_version": "v1", "source": "...", "payload": {...}}
    - Publisher は async (asyncio.to_thread で同期 SDK をラップ)
    - Subscriber は callback ベース (Pub/Sub の streaming pull)
    - Topic / subscription 名は env / config から渡す (ハードコード禁止)

Trade-off:
    - google-cloud-pubsub の grpc client を完全に隠蔽はしない (Future, ack, nack 等)
    - エラーハンドリングは呼び出し側責務 (リトライ / DLQ は terraform で構成)

倫理:
    - 発言本文を含むメッセージなので 7 日 message_retention は terraform で設定
    - Pub/Sub message に PII (個人発言者氏名) を含む → 暗号化はデフォルト Google-managed key
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from concurrent.futures import Future

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "v1"


# ============================================================================
# Envelope
# ============================================================================


@dataclass(frozen=True)
class MessageEnvelope:
    """Pub/Sub メッセージの統一エンベロープ。

    Attributes:
        schema_version: スキーマバージョン (v1 系で破壊変更しない)
        source: メッセージ送信元 (例: 'kaigiroku_net', 'kokkai_api', 'translator')
        payload_type: payload の Pydantic スキーマ名 (例: 'Speech', 'TranslatorOutput')
        payload: 任意の dict (Pydantic.model_dump() を入れる)
    """

    schema_version: str
    source: str
    payload_type: str
    payload: dict[str, Any]

    def to_bytes(self) -> bytes:
        """Pub/Sub publish 用に UTF-8 JSON にシリアライズ。"""
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "source": self.source,
                "payload_type": self.payload_type,
                "payload": self.payload,
            },
            ensure_ascii=False,
            default=str,  # date / datetime を ISO 文字列に
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> MessageEnvelope:
        """受信した Pub/Sub message から復元。"""
        obj = json.loads(data.decode("utf-8"))
        return cls(
            schema_version=obj["schema_version"],
            source=obj["source"],
            payload_type=obj["payload_type"],
            payload=obj["payload"],
        )

    @classmethod
    def wrap(cls, source: str, model: BaseModel) -> MessageEnvelope:
        """Pydantic モデルを envelope にラップ。"""
        return cls(
            schema_version=SCHEMA_VERSION,
            source=source,
            payload_type=type(model).__name__,
            payload=model.model_dump(mode="json"),
        )


# ============================================================================
# Publisher
# ============================================================================


class _PublisherClientProto(Protocol):
    """google.cloud.pubsub_v1.PublisherClient の必要メソッドだけを抽出 (mock 用)。"""

    def topic_path(self, project: str, topic: str) -> str: ...
    def publish(self, topic_path: str, data: bytes, **attrs: str) -> Future: ...


class PubSubPublisher:
    """Pub/Sub への publish ラッパ。

    Usage:
        pub = PubSubPublisher(project_id="citify-dev")
        msg_id = pub.publish_envelope(
            topic="citify-speech-translate",
            envelope=MessageEnvelope.wrap("kaigiroku_net", speech),
        )

    Args:
        project_id: GCP project ID
        client: google.cloud.pubsub_v1.PublisherClient (None なら遅延生成)
        timeout_sec: publish 完了待ち秒数
    """

    def __init__(
        self,
        project_id: str,
        client: _PublisherClientProto | None = None,
        timeout_sec: float = 30.0,
    ) -> None:
        self.project_id = project_id
        self.timeout_sec = timeout_sec
        self._client = client

    def _ensure_client(self) -> _PublisherClientProto:
        if self._client is not None:
            return self._client
        # 遅延 import: テストで mock 時は google-cloud-pubsub 不要
        from google.cloud import pubsub_v1

        self._client = pubsub_v1.PublisherClient()
        return self._client

    def publish_envelope(
        self,
        topic: str,
        envelope: MessageEnvelope,
        attributes: dict[str, str] | None = None,
    ) -> str:
        """envelope を publish。返り値は Pub/Sub message_id (debug 用)。

        Args:
            topic: トピック名 (project_id プレフィックスなし、例: 'citify-speech-translate')
            envelope: 送信するエンベロープ
            attributes: Pub/Sub message attributes (filtering 用、optional)
        """
        client = self._ensure_client()
        topic_path = client.topic_path(self.project_id, topic)
        data = envelope.to_bytes()
        attrs = {
            "source": envelope.source,
            "payload_type": envelope.payload_type,
            "schema_version": envelope.schema_version,
            **(attributes or {}),
        }
        future = client.publish(topic_path, data, **attrs)
        msg_id = future.result(timeout=self.timeout_sec)
        logger.debug(
            "pubsub.publish topic=%s source=%s payload_type=%s msg_id=%s size=%d",
            topic,
            envelope.source,
            envelope.payload_type,
            msg_id,
            len(data),
        )
        return msg_id

    def publish_many(
        self,
        topic: str,
        envelopes: list[MessageEnvelope],
        attributes: dict[str, str] | None = None,
    ) -> list[str]:
        """複数 envelopes を順次 publish。失敗時は例外を伝播。

        Note:
            高スループット時は asyncio gather 化を検討。現状は順次でも十分。
        """
        ids: list[str] = []
        for env in envelopes:
            ids.append(self.publish_envelope(topic, env, attributes))
        logger.info("pubsub.publish_many topic=%s n=%d", topic, len(ids))
        return ids


# ============================================================================
# Subscriber
# ============================================================================


class _SubscriberClientProto(Protocol):
    """google.cloud.pubsub_v1.SubscriberClient の必要メソッドだけ (mock 用)。"""

    def subscription_path(self, project: str, subscription: str) -> str: ...
    def subscribe(self, subscription_path: str, callback: Callable[[Any], None]) -> Any: ...


EnvelopeHandler = Callable[[MessageEnvelope], None]


class PubSubSubscriber:
    """Pub/Sub からの subscribe ラッパ (streaming pull)。

    Usage:
        sub = PubSubSubscriber(project_id="citify-dev")
        sub.run(
            subscription="citify-speech-translate-sub",
            handler=process_envelope,
        )

    Args:
        project_id: GCP project ID
        client: google.cloud.pubsub_v1.SubscriberClient (None なら遅延生成)
    """

    def __init__(
        self,
        project_id: str,
        client: _SubscriberClientProto | None = None,
    ) -> None:
        self.project_id = project_id
        self._client = client

    def _ensure_client(self) -> _SubscriberClientProto:
        if self._client is not None:
            return self._client
        from google.cloud import pubsub_v1

        self._client = pubsub_v1.SubscriberClient()
        return self._client

    def process_message(self, message: Any, handler: EnvelopeHandler) -> None:
        """1 件の Pub/Sub message を処理 (ack / nack 含む)。

        - JSON parse 失敗 → nack (DLQ 行きになる、要 terraform 設定)
        - handler が例外送出 → nack
        - 成功 → ack

        public で公開しているのは、subscriber のテストから直接呼び出せるようにするため。
        """
        try:
            envelope = MessageEnvelope.from_bytes(message.data)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "pubsub.envelope_parse_failed msg_id=%s err=%s data_preview=%r",
                getattr(message, "message_id", "?"),
                exc,
                message.data[:200] if hasattr(message, "data") else "(no data)",
            )
            # parse 失敗は ack して DLQ 送信 (構造的に壊れたメッセージは再送しても無駄)
            message.ack()
            return

        try:
            handler(envelope)
            message.ack()
            logger.debug(
                "pubsub.handler_ok msg_id=%s source=%s payload_type=%s",
                getattr(message, "message_id", "?"),
                envelope.source,
                envelope.payload_type,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "pubsub.handler_failed msg_id=%s source=%s payload_type=%s err=%s",
                getattr(message, "message_id", "?"),
                envelope.source,
                envelope.payload_type,
                exc,
            )
            message.nack()

    def run(
        self,
        subscription: str,
        handler: EnvelopeHandler,
        timeout_sec: float | None = None,
    ) -> None:
        """subscribe を開始してブロック (Cloud Run Worker / ローカル CLI 想定)。

        Args:
            subscription: subscription 名 (例: 'citify-speech-translate-sub')
            handler: envelope 1 件を処理する callable
            timeout_sec: None で永続実行、指定で N 秒後に停止
        """
        client = self._ensure_client()
        sub_path = client.subscription_path(self.project_id, subscription)

        def _callback(message: Any) -> None:
            self.process_message(message, handler)

        future = client.subscribe(sub_path, _callback)
        logger.info("pubsub.subscribe_start subscription=%s", subscription)
        try:
            future.result(timeout=timeout_sec)
        except KeyboardInterrupt:
            logger.info("pubsub.subscribe_interrupted")
            future.cancel()
        except TimeoutError:
            logger.info("pubsub.subscribe_timeout (clean shutdown)")
            future.cancel()
