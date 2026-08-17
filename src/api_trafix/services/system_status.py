"""In-memory system health tracking — replaces the observability plane
that the Parkways Monitoring desktop app provided.

The ``SystemStatus`` singleton lives on ``app.state`` and is updated by
callbacks from the MQTT bus and the TCP gateway.  All state is transient — a
restart resets counters, which is acceptable for an operational dashboard.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class SystemStatus:
    """Lightweight, in-memory system health tracker.

    Callbacks are registered by passing instances to the ``MqttBus`` and
    ``TcpGateway`` constructors; the routes read snapshots via
    :meth:`get_mqtt_status` / :meth:`get_system_health`.
    """

    def __init__(self) -> None:
        # -- MQTT --
        self.mqtt_connected: bool = False
        self.mqtt_host: str = ""
        self.mqtt_port: int = 0
        self.mqtt_last_connect_at: float | None = None
        self.mqtt_last_disconnect_at: float | None = None
        self.mqtt_reconnect_count: int = 0
        self.mqtt_disconnect_count: int = 0

        # -- TCP --
        self.tcp_connected_count: int = 0
        self.tcp_total_gate_count: int = 0

        # -- General --
        self.started_at: float = time.monotonic()
        self.last_activity_at: float = time.monotonic()

    # -- callbacks called by MqttBus ----------------------------------------

    def on_mqtt_connect(self, host: str, port: int) -> None:
        self.mqtt_connected = True
        self.mqtt_host = host
        self.mqtt_port = port
        self.mqtt_last_connect_at = time.monotonic()
        if self.mqtt_disconnect_count > 0:
            self.mqtt_reconnect_count += 1
        logger.info("system_status: MQTT connected to %s:%s", host, port)

    def on_mqtt_disconnect(self) -> None:
        self.mqtt_connected = False
        self.mqtt_last_disconnect_at = time.monotonic()
        self.mqtt_disconnect_count += 1
        logger.info("system_status: MQTT disconnected")

    # -- callbacks called by TcpGateway -------------------------------------

    def set_tcp_counts(self, connected: int, total: int) -> None:
        self.tcp_connected_count = connected
        self.tcp_total_gate_count = total

    # -- general activity heartbeat -----------------------------------------

    def touch_activity(self) -> None:
        self.last_activity_at = time.monotonic()

    # -- snapshot getters ---------------------------------------------------

    def get_mqtt_status(self) -> dict:
        uptime = None
        if self.mqtt_last_connect_at is not None:
            uptime = round(time.monotonic() - self.mqtt_last_connect_at, 1)
        return {
            "connected": self.mqtt_connected,
            "host": self.mqtt_host,
            "port": self.mqtt_port,
            "uptime_seconds": uptime,
            "reconnect_count": self.mqtt_reconnect_count,
            "disconnect_count": self.mqtt_disconnect_count,
            "last_connect_at": self.mqtt_last_connect_at,
            "last_disconnect_at": self.mqtt_last_disconnect_at,
        }

    def get_tcp_status(self) -> dict:
        return {
            "connected_gates": self.tcp_connected_count,
            "total_gates": self.tcp_total_gate_count,
        }

    def get_system_health(self) -> dict:
        return {
            "status": "healthy",
            "uptime_seconds": round(time.monotonic() - self.started_at, 1),
            "mqtt": self.get_mqtt_status(),
            "tcp": self.get_tcp_status(),
        }
