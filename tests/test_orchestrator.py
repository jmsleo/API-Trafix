"""Unit tests for the MQTT orchestrator's handler logic.

These exercise the MQTT event dispatcher directly, so no broker or API is
needed: ``start()`` is never called and all outbound effects are recorded by a
fake bus. Port of ``trafix-api-mock/tests/test_orchestrator.py``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api_trafix.services.device_registry import GateController
from api_trafix.services.orchestrator import MEMBER_REFUSED, LaneState, Orchestrator
from api_trafix.services.protocol import input_info, read_card


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.subscribed: list[str] = []

    def subscribe(self, topic: str, handler) -> None:
        self.subscribed.append(topic)

    def subscribe_raw(self, topic: str, handler) -> None:
        self.subscribed.append(topic)

    def publish(self, topic: str, message, *, retain: bool = False) -> None:
        self.publish_raw(topic, message.to_json(), retain=retain)

    def publish_raw(self, topic: str, payload: str, *, retain: bool = False, qos: int = 1) -> None:
        self.published.append((topic, payload))

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class StubRegistry:
    def __init__(self) -> None:
        self._controllers = {
            "1": GateController("entry", "1", "10.0.0.1", "441D6491AF17", "gate_in"),
            "2": GateController("exit", "2", "10.0.0.2", "", "gate_out"),
        }

    def controllers(self) -> dict[str, GateController]:
        return dict(self._controllers)

    def lpr_items(self) -> dict:
        return {}

    def entry_gate_codes(self) -> set[str]:
        return {"1"}

    def controller_for(self, gate_code: str) -> GateController:
        return self._controllers[str(gate_code)]

    def lpr_for(self, gate_code: str):
        raise KeyError(gate_code)


def _settings(**overrides) -> SimpleNamespace:
    base = {
        "api_base_url": "http://api.invalid",
        "lpr_timeout_seconds": 5.0,
        "lpr_retries": 1,
        "button_debounce_seconds": 5.0,
        "barrier_pulse_ms": 1000,
        "barrier_beep_ms": 100,
        "card_fallback_to_ticket": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def orche():
    def build(*, rfid_only: bool = False):
        bus = FakeBus()
        orchestrator = Orchestrator(
            settings=_settings(),
            bus=bus,
            registry=StubRegistry(),
            rfid_only=rfid_only,
        )
        # ``start()`` is never called in these tests, so seed the per-lane state
        # exactly as ``start()`` would.
        orchestrator.lanes["1"] = LaneState()
        orchestrator._locks["1"] = asyncio.Lock()
        handler = orchestrator._make_event_handler("1")
        return orchestrator, handler, bus

    return build


async def test_rfid_only_ignores_arrival(orche):
    _, handler, bus = orche(rfid_only=True)
    await handler("g/event/1", input_info("441D6491AF17", input3=1))
    assert bus.published == []


async def test_rfid_only_ignores_ticket_button(orche):
    _, handler, bus = orche(rfid_only=True)
    await handler("g/event/1", input_info("441D6491AF17", input2=1))
    assert bus.published == []


async def test_full_mode_still_reacts_to_arrival(orche):
    _, handler, bus = orche(rfid_only=False)
    await handler("g/event/1", input_info("441D6491AF17", input3=1))
    assert len(bus.published) == 1
    topic, payload = bus.published[0]
    assert topic.endswith("/status")
    assert '"welcome"' in payload


async def test_rfid_only_still_delivers_read_card(orche, monkeypatch):
    orchestrator, handler, _bus = orche(rfid_only=True)
    seen = []
    fallback = []

    async def fake_member(gate, card_no, serial_no):
        seen.append((gate, card_no))

    async def fake_button(gate, message):
        fallback.append((gate, message.method))

    monkeypatch.setattr(orchestrator, "_request_member_entry", fake_member)
    monkeypatch.setattr(orchestrator, "_handle_button", fake_button)
    await handler("g/event/1", read_card("441D6491AF17", "006343040"))
    assert seen == [("1", "006343040")]
    assert fallback == [("1", "readCard")]


async def test_unregistered_card_falls_back_to_a_paper_ticket(orche, monkeypatch):
    """A card that is not a member must not strand the driver: issue a ticket."""
    orchestrator, handler, _bus = orche(rfid_only=False)

    async def fake_member(gate, card_no, serial_no):
        return None

    fallback = []

    async def fake_button(gate, message):
        fallback.append(gate)

    monkeypatch.setattr(orchestrator, "_request_member_entry", fake_member)
    monkeypatch.setattr(orchestrator, "_handle_button", fake_button)
    await handler("g/event/1", read_card("441D6491AF17", "006343040"))
    assert fallback == ["1"]


async def test_registered_but_refused_member_gets_no_ticket(orche, monkeypatch):
    """A registered member (expired / vehicle mismatch) never prints a ticket."""
    orchestrator, handler, bus = orche(rfid_only=False)
    fallback = []

    async def fake_member(gate, card_no, serial_no):
        return MEMBER_REFUSED

    async def fake_button(gate, message):
        fallback.append(gate)

    monkeypatch.setattr(orchestrator, "_request_member_entry", fake_member)
    monkeypatch.setattr(orchestrator, "_handle_button", fake_button)
    await handler("g/event/1", read_card("441D6491AF17", "006343040"))
    assert fallback == []
    payloads = " ".join(p for _, p in bus.published)
    assert "txUartData" not in payloads  # no print commands
    assert any("/status" in topic for topic, _ in bus.published)  # "thanks"
    assert any("/GATE/IN/1" == topic for topic, _ in bus.published)  # barrier opens


async def test_refused_card_does_not_fall_back_when_disabled(orche, monkeypatch):
    orchestrator, handler, bus = orche(rfid_only=False)
    orchestrator.settings = _settings(card_fallback_to_ticket=False)

    async def fake_member(gate, card_no, serial_no):
        return None

    fallback = []

    async def fake_button(gate, message):
        fallback.append(gate)

    monkeypatch.setattr(orchestrator, "_request_member_entry", fake_member)
    monkeypatch.setattr(orchestrator, "_handle_button", fake_button)
    await handler("g/event/1", read_card("441D6491AF17", "006343040"))
    assert fallback == []
    assert bus.published == []


async def test_exit_read_settles_and_raises_the_barrier(orche, monkeypatch):
    """An exit LPR announcement drives the automated gateout path (§7.1)."""
    orchestrator, _handler, _bus = orche(rfid_only=False)
    exit_handler = orchestrator._make_exit_handler("2")
    released = []

    async def fake_settle(gate, plate, image_url):
        released.append((gate, plate))

    monkeypatch.setattr(orchestrator, "_settle_by_plate", fake_settle)
    await exit_handler(
        "gate/out/2/pos",
        '{"plate_num": "H488AI", "url_gambar": "http://lpr/img.jpg"}',
    )
    assert released == [("2", "H488AI")]


async def test_exit_read_without_a_plate_is_ignored(orche, monkeypatch):
    orchestrator, _handler, _bus = orche(rfid_only=False)
    exit_handler = orchestrator._make_exit_handler("2")
    released = []

    async def fake_settle(gate, plate, image_url):
        released.append((gate, plate))

    monkeypatch.setattr(orchestrator, "_settle_by_plate", fake_settle)
    await exit_handler("gate/out/2/pos", '{"plate_num": ""}')
    assert released == []


async def test_exit_read_with_undecodable_payload_is_ignored(orche, monkeypatch):
    orchestrator, _handler, _bus = orche(rfid_only=False)
    exit_handler = orchestrator._make_exit_handler("2")
    released = []

    async def fake_settle(gate, plate, image_url):
        released.append((gate, plate))

    monkeypatch.setattr(orchestrator, "_settle_by_plate", fake_settle)
    await exit_handler("gate/out/2/pos", "not json")
    assert released == []
