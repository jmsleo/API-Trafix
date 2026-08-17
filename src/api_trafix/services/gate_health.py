"""Per-gate health monitoring — replaces the per-gate status panel from
the Parkways Monitoring desktop app.

The ``GateHealth`` singleton is updated by the ``Orchestrator`` when it
receives ``METHOD_STATUS`` (heartbeat) and ``METHOD_INPUT`` (sensor) events
from the MQTT bus or TCP gateway.  Routes read snapshots via
:meth:`get_all` / :meth:`get_one`.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_HEARTBEAT_TIMEOUT_SECONDS = 120.0  # gate considered offline if no heartbeat for 2 min


@dataclass
class GateHealthEntry:
    """Runtime health state for a single gate controller."""

    gate_code: str
    last_heartbeat_at: float | None = None
    last_input_at: float | None = None
    connection_type: str = "mqtt"  # "mqtt" | "tcp" | "both"
    is_online: bool = False
    sensor_states: dict = field(default_factory=dict)
    relay_states: dict = field(default_factory=dict)
    firmware_version: str | None = None
    total_heartbeats: int = 0
    total_inputs: int = 0


class GateHealth:
    """In-memory per-gate health store."""

    def __init__(self) -> None:
        self._gates: dict[str, GateHealthEntry] = {}

    def register(self, gate_code: str, connection_type: str = "mqtt") -> None:
        """Register a gate at startup or when its config is loaded."""
        if gate_code not in self._gates:
            self._gates[gate_code] = GateHealthEntry(
                gate_code=gate_code,
                connection_type=connection_type,
            )

    def on_heartbeat(self, gate_code: str, data: dict | None = None) -> None:
        entry = self._get_or_create(gate_code)
        entry.last_heartbeat_at = time.monotonic()
        entry.total_heartbeats += 1
        entry.is_online = True
        if data is not None:
            self._apply_status(entry, data)
        logger.debug("gate_health: heartbeat from %s", gate_code)

    def on_input(self, gate_code: str, data: dict | None = None) -> None:
        entry = self._get_or_create(gate_code)
        entry.last_input_at = time.monotonic()
        entry.total_inputs += 1
        if data is not None:
            self._apply_inputs(entry, data)

    def on_tcp_input(self, gate_code: str, data: dict) -> None:
        """Update from a TCP input frame (different field names)."""
        entry = self._get_or_create(gate_code)
        entry.last_input_at = time.monotonic()
        entry.total_inputs += 1
        entry.connection_type = "tcp"
        for key in ("input1", "input2", "input3", "input4", "pos1", "pos2", "pos3"):
            if key in data:
                entry.sensor_states[key] = bool(data[key])
        logger.debug("gate_health: TCP input from %s", gate_code)

    # -- query --------------------------------------------------------------

    def get_all(self) -> list[dict]:
        self._refresh_online_status()
        return [self._to_dict(e) for e in self._gates.values()]

    def get_one(self, gate_code: str) -> dict | None:
        self._refresh_online_status()
        entry = self._gates.get(gate_code)
        if entry is None:
            return None
        return self._to_dict(entry)

    # -- internal -----------------------------------------------------------

    def _get_or_create(self, gate_code: str) -> GateHealthEntry:
        if gate_code not in self._gates:
            self._gates[gate_code] = GateHealthEntry(gate_code=gate_code)
        return self._gates[gate_code]

    def _refresh_online_status(self) -> None:
        now = time.monotonic()
        for entry in self._gates.values():
            if entry.last_heartbeat_at is not None:
                entry.is_online = (now - entry.last_heartbeat_at) < _HEARTBEAT_TIMEOUT_SECONDS

    def _apply_status(self, entry: GateHealthEntry, data: dict) -> None:
        for key in ("input1", "input2", "input3", "input4"):
            if key in data:
                entry.sensor_states[key] = bool(data[key])
        for key in ("relay1", "relay2", "relay3"):
            if key in data:
                entry.relay_states[key] = bool(data[key])
        if "beep" in data:
            entry.relay_states["beep"] = bool(data["beep"])

    def _apply_inputs(self, entry: GateHealthEntry, data: dict) -> None:
        for key in ("input1", "input2", "input3", "input4"):
            if key in data:
                entry.sensor_states[key] = bool(data[key])

    def _to_dict(self, entry: GateHealthEntry) -> dict:
        return {
            "gate_code": entry.gate_code,
            "is_online": entry.is_online,
            "connection_type": entry.connection_type,
            "last_heartbeat_at": entry.last_heartbeat_at,
            "last_input_at": entry.last_input_at,
            "sensor_states": dict(entry.sensor_states),
            "relay_states": dict(entry.relay_states),
            "firmware_version": entry.firmware_version,
            "total_heartbeats": entry.total_heartbeats,
            "total_inputs": entry.total_inputs,
        }
