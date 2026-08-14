"""MQTT transport tests.

``test_mqtt_bus*`` run against a real (in-process, amqtt) broker, so they prove
the aiomqtt wiring — connect, subscribe, publish, and live re-subscribe —
rather than just the envelope parsing. The publisher tests use a fake bus and
assert the wire envelope, like ``trafix-api-mock/tests/test_service.py``.
"""

from __future__ import annotations

import asyncio
import socket

import pytest
from amqtt.broker import Broker

from api_trafix.services.device_registry import DeviceRegistry
from api_trafix.services.mqtt_bus import MqttBus
from api_trafix.services.protocol import (
    METHOD_OUTPUT_CTRL,
    METHOD_TX_UART_DATA,
    Envelope,
    gate_in_topic,
    gate_out_topic,
    input_info,
    parse,
)
from api_trafix.services.publisher import MqttPublisher


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def broker():
    port = _free_port()
    instance = Broker(
        {
            "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
            "auth": {"allow-anonymous": True},
        }
    )
    await instance.start()
    yield port
    await instance.shutdown()


async def test_bus_roundtrips_an_envelope(broker):
    bus = MqttBus(host="127.0.0.1", port=broker, client_id="test-bus")
    received = asyncio.Queue()

    async def handler(topic: str, envelope: Envelope) -> None:
        await received.put((topic, envelope))

    bus.subscribe("/GATE/event/1", handler)
    await bus.start()
    try:
        assert await bus.wait_connected(timeout=5)
        bus.publish_raw("/GATE/event/1", input_info("441D6491AF17", input3=1).to_json())
        topic, envelope = await asyncio.wait_for(received.get(), timeout=5)
        assert topic == "/GATE/event/1"
        assert envelope.method == "inputInfo"
        assert envelope.get("input3") == 1
        assert envelope.serial_no == "441D6491AF17"
    finally:
        await bus.stop()


async def test_bus_delivers_to_raw_handler(broker):
    bus = MqttBus(host="127.0.0.1", port=broker, client_id="test-bus")
    raw = asyncio.Queue()

    async def raw_handler(topic: str, payload: str) -> None:
        await raw.put((topic, payload))

    bus.subscribe_raw("/GATE/IN/1/status", raw_handler)
    await bus.start()
    try:
        assert await bus.wait_connected(timeout=5)
        bus.publish_raw("/GATE/IN/1/status", '{"status":"welcome"}')
        topic, payload = await asyncio.wait_for(raw.get(), timeout=5)
        assert topic == "/GATE/IN/1/status"
        assert '"welcome"' in payload
    finally:
        await bus.stop()


async def test_subscription_registered_while_connected_reaches_the_broker(broker):
    """The mock re-subscribes on connect only; a topic added later must still work."""
    bus = MqttBus(host="127.0.0.1", port=broker, client_id="test-bus")
    received = asyncio.Queue()

    async def handler(topic: str, envelope: Envelope) -> None:
        await received.put(envelope.method)

    await bus.start()
    try:
        assert await bus.wait_connected(timeout=5)
        bus.subscribe("/GATE/event/1", handler)
        bus.publish_raw("/GATE/event/1", input_info("S1", input3=1).to_json())
        assert await asyncio.wait_for(received.get(), timeout=5) == "inputInfo"
    finally:
        await bus.stop()


async def test_malformed_payload_does_not_kill_the_bus(broker):
    bus = MqttBus(host="127.0.0.1", port=broker, client_id="test-bus")
    received = asyncio.Queue()

    async def handler(topic: str, envelope: Envelope) -> None:
        await received.put(envelope.method)

    bus.subscribe("/GATE/event/1", handler)
    await bus.start()
    try:
        assert await bus.wait_connected(timeout=5)
        bus.publish_raw("/GATE/event/1", "not-json")
        bus.publish_raw("/GATE/event/1", input_info("S1", input3=1).to_json())
        # The malformed message is dropped; the next one still arrives.
        assert await asyncio.wait_for(received.get(), timeout=5) == "inputInfo"
    finally:
        await bus.stop()


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, topic: str, message: Envelope, *, retain: bool = False) -> None:
        self.published.append((topic, message.to_json()))

    def publish_raw(self, topic: str, payload: str, *, retain: bool = False, qos: int = 1) -> None:
        self.published.append((topic, payload))


class _FakeRegistry(DeviceRegistry):
    def __init__(self) -> None:
        super().__init__(lambda: None)
        self._controllers = {
            "1": type("C", (), {"serial_no": "441D6491AF17"})(),
            "2": type("C", (), {"serial_no": ""})(),
        }

    def controller_for(self, gate_code: str):
        try:
            return self._controllers[str(gate_code)]
        except KeyError:
            raise KeyError(gate_code)


async def test_publisher_prints_a_ticket():
    bus = _FakeBus()
    publisher = MqttPublisher(bus, _FakeRegistry(), pulse_ms=1500, beep_ms=200)
    blocks = [{"type": "text", "text": "HALF 1"}]
    await publisher.print_ticket("1", blocks, "abc123")
    (topic, payload), = bus.published
    assert topic == gate_in_topic("1")
    envelope = parse(payload)
    assert envelope.method == METHOD_TX_UART_DATA
    assert envelope.serial_no == "441D6491AF17"
    assert envelope.id == "abc123"


async def test_publisher_opens_the_entry_barrier():
    bus = _FakeBus()
    publisher = MqttPublisher(bus, _FakeRegistry(), pulse_ms=1500, beep_ms=200)
    await publisher.open_barrier("1")
    (topic, payload), = bus.published
    assert topic == gate_in_topic("1")
    envelope = parse(payload)
    assert envelope.method == METHOD_OUTPUT_CTRL
    assert envelope.get("relay1Out") == [1, 1500]
    assert envelope.get("beepOut") == [1, 200]


async def test_publisher_opens_the_exit_barrier():
    bus = _FakeBus()
    publisher = MqttPublisher(bus, _FakeRegistry())
    await publisher.open_barrier("2", exit_lane=True)
    (topic, _payload), = bus.published
    assert topic == gate_out_topic("2")


async def test_publisher_publishes_with_empty_serial_for_unknown_controller():
    """No exit controller is configured on site (§7.6) — publish anyway."""
    bus = _FakeBus()
    publisher = MqttPublisher(bus, _FakeRegistry())
    await publisher.open_barrier("2")
    (_topic, payload), = bus.published
    envelope = parse(payload)
    assert envelope.serial_no == ""
