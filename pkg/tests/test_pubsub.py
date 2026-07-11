"""pkg.pubsub のテスト (Pub/Sub クライアントは mock)。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from pydantic import BaseModel

from pkg.pubsub import (
    SCHEMA_VERSION,
    MessageEnvelope,
    PubSubPublisher,
    PubSubSubscriber,
)

# ============================================================================
# MessageEnvelope
# ============================================================================


class _DummyModel(BaseModel):
    id: str
    text: str
    score: int = 0


def test_envelope_wrap_from_pydantic():
    m = _DummyModel(id="x", text="hello", score=10)
    env = MessageEnvelope.wrap("kaigiroku_net", m)
    assert env.schema_version == SCHEMA_VERSION
    assert env.source == "kaigiroku_net"
    assert env.payload_type == "_DummyModel"
    assert env.payload == {"id": "x", "text": "hello", "score": 10}


def test_envelope_round_trip_bytes():
    env = MessageEnvelope(
        schema_version=SCHEMA_VERSION,
        source="test",
        payload_type="X",
        payload={"a": 1, "b": "日本語"},
    )
    data = env.to_bytes()
    assert isinstance(data, bytes)
    parsed = MessageEnvelope.from_bytes(data)
    assert parsed == env


def test_envelope_to_bytes_handles_dates():
    """date / datetime を default=str で ISO 文字列にできる。"""
    from datetime import date

    env = MessageEnvelope(
        schema_version="v1",
        source="test",
        payload_type="X",
        payload={"d": date(2026, 5, 21)},
    )
    data = env.to_bytes()
    obj = json.loads(data.decode("utf-8"))
    assert obj["payload"]["d"] == "2026-05-21"


# ============================================================================
# PubSubPublisher
# ============================================================================


def _make_mock_publisher_client(msg_id: str = "msg-001") -> MagicMock:
    client = MagicMock()
    client.topic_path.side_effect = lambda p, t: f"projects/{p}/topics/{t}"
    future = MagicMock()
    future.result.return_value = msg_id
    client.publish.return_value = future
    return client


def test_publisher_publishes_envelope_with_attributes():
    client = _make_mock_publisher_client("msg-42")
    pub = PubSubPublisher(project_id="citify-dev", client=client)

    env = MessageEnvelope.wrap("kaigiroku_net", _DummyModel(id="x", text="t"))
    msg_id = pub.publish_envelope("citify-speech-translate", env)

    assert msg_id == "msg-42"
    client.topic_path.assert_called_once_with("citify-dev", "citify-speech-translate")

    # publish 引数の検証
    args, kwargs = client.publish.call_args
    assert args[0] == "projects/citify-dev/topics/citify-speech-translate"
    assert isinstance(args[1], bytes)
    # attributes (publish の kwargs)
    assert kwargs["source"] == "kaigiroku_net"
    assert kwargs["payload_type"] == "_DummyModel"
    assert kwargs["schema_version"] == SCHEMA_VERSION


def test_publisher_publish_many_sequential():
    client = _make_mock_publisher_client()
    pub = PubSubPublisher(project_id="citify-dev", client=client)

    envelopes = [MessageEnvelope.wrap("test", _DummyModel(id=str(i), text="t")) for i in range(3)]
    ids = pub.publish_many("topic", envelopes)

    assert len(ids) == 3
    assert client.publish.call_count == 3


def test_publisher_custom_attributes_merge():
    """attributes 引数が envelope 属性とマージされる。"""
    client = _make_mock_publisher_client()
    pub = PubSubPublisher(project_id="citify-dev", client=client)

    env = MessageEnvelope.wrap("test", _DummyModel(id="x", text="t"))
    pub.publish_envelope("topic", env, attributes={"municipality_code": "13000"})

    _, kwargs = client.publish.call_args
    assert kwargs["municipality_code"] == "13000"
    assert kwargs["source"] == "test"  # envelope 由来は維持


# ============================================================================
# PubSubSubscriber.process_message
# ============================================================================


@dataclass
class _FakeMessage:
    """Pub/Sub message の test double。"""

    data: bytes
    message_id: str = "msg-001"
    ack_called: bool = False
    nack_called: bool = False

    def ack(self) -> None:
        self.ack_called = True

    def nack(self) -> None:
        self.nack_called = True


def test_subscriber_process_message_ack_on_success():
    sub = PubSubSubscriber(project_id="citify-dev")
    env = MessageEnvelope.wrap("test", _DummyModel(id="x", text="t"))
    msg = _FakeMessage(data=env.to_bytes())

    received: list[MessageEnvelope] = []

    def handler(e: MessageEnvelope) -> None:
        received.append(e)

    sub.process_message(msg, handler)

    assert msg.ack_called
    assert not msg.nack_called
    assert len(received) == 1
    assert received[0].source == "test"


def test_subscriber_process_message_nack_on_handler_error():
    sub = PubSubSubscriber(project_id="citify-dev")
    env = MessageEnvelope.wrap("test", _DummyModel(id="x", text="t"))
    msg = _FakeMessage(data=env.to_bytes())

    def handler(_e: MessageEnvelope) -> None:
        raise ValueError("simulated failure")

    sub.process_message(msg, handler)

    assert msg.nack_called
    assert not msg.ack_called


def test_subscriber_process_message_acks_on_permanent_error():
    """M1: handler が PermanentMessageError を投げたら nack せず ack-drop (無限再送防止)。"""
    from pkg.pubsub import PermanentMessageError

    sub = PubSubSubscriber(project_id="citify-dev")
    env = MessageEnvelope.wrap("test", _DummyModel(id="x", text="t"))
    msg = _FakeMessage(data=env.to_bytes())

    def handler(_e: MessageEnvelope) -> None:
        raise PermanentMessageError("poison pill: missing required keys")

    sub.process_message(msg, handler)

    assert msg.ack_called
    assert not msg.nack_called


def test_subscriber_process_message_ack_on_parse_failure():
    """JSON parse 失敗は DLQ 行き目的で ack (再送しない)。"""
    sub = PubSubSubscriber(project_id="citify-dev")
    msg = _FakeMessage(data=b"not valid json{{{")

    called: list[Any] = []

    def handler(e: MessageEnvelope) -> None:
        called.append(e)

    sub.process_message(msg, handler)

    assert msg.ack_called
    assert not msg.nack_called
    assert called == []  # handler は呼ばれない


# ============================================================================
# PubSubSubscriber.run (subscribe + 一定時間で停止)
# ============================================================================


def test_subscriber_run_invokes_subscribe_with_path():
    """run() の中で client.subscribe が正しいパスで呼ばれる。"""
    client = MagicMock()
    client.subscription_path.side_effect = lambda p, s: f"projects/{p}/subscriptions/{s}"
    future = MagicMock()
    # timeout で TimeoutError を即発生させて run() がクリーン停止
    future.result.side_effect = TimeoutError()
    client.subscribe.return_value = future

    sub = PubSubSubscriber(project_id="citify-dev", client=client)
    sub.run(subscription="my-sub", handler=lambda e: None, timeout_sec=0.01)

    client.subscription_path.assert_called_once_with("citify-dev", "my-sub")
    client.subscribe.assert_called_once()
    args, _ = client.subscribe.call_args
    assert args[0] == "projects/citify-dev/subscriptions/my-sub"
    future.cancel.assert_called_once()
