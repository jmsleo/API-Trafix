"""Publishes gate commands over MQTT.

Implements the :class:`api_trafix.services.gate_cycle.Publisher` protocol, so
the business logic never imports a broker client. Port of
``trafix-api-mock/trafix/publisher.py``.
"""

from __future__ import annotations

import logging

from api_trafix.services.device_registry import DeviceRegistry, RegistryError
from api_trafix.services.mqtt_bus import MqttBus
from api_trafix.services.protocol import (
    gate_in_topic,
    gate_out_topic,
    open_barrier,
    print_ticket,
)

logger = logging.getLogger(__name__)


class MqttPublisher:
    """Publish tickets and barrier commands to a gate controller's topics."""

    def __init__(
        self,
        bus: MqttBus,
        registry: DeviceRegistry,
        *,
        pulse_ms: int = 1000,
        beep_ms: int = 100,
    ) -> None:
        self.bus = bus
        self.registry = registry
        self.pulse_ms = pulse_ms
        self.beep_ms = beep_ms

    def _serial_for(self, gate: str) -> str:
        try:
            return self.registry.controller_for(gate).serial_no
        except RegistryError:
            # An exit controller may not be configured — on site there is no
            # such device at all (flow.md §7.6). Publish anyway with an empty
            # serial so the message is visible to whoever is listening.
            logger.warning("no controller configured for gate %s", gate)
            return ""

    async def print_ticket(self, gate: str, blocks: list[dict], message_id: str) -> None:
        self.bus.publish(
            gate_in_topic(gate),
            print_ticket(self._serial_for(gate), blocks, message_id),
        )

    async def open_barrier(self, gate: str, *, exit_lane: bool = False) -> None:
        topic = gate_out_topic(gate) if exit_lane else gate_in_topic(gate)
        self.bus.publish(
            topic,
            open_barrier(
                self._serial_for(gate),
                pulse_ms=self.pulse_ms,
                beep_ms=self.beep_ms,
            ),
        )
        logger.info("barrier command sent to %s", topic)
