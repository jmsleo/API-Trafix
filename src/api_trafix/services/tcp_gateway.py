"""TCP gateway — manages persistent connections to TCP-speaking gate
controllers.  Mirrors the Rust ``TcpFacade`` (``src/application/services/
tcp_facade.rs``) and the asyncio ``GatewayTcpManager`` from the Flutter app.

Each gate with ``connection_type`` in ``("tcp", "both")`` gets a persistent
TCP connection managed by :class:`TcpGateway`.  The reader loop (see
:mod:`tcp_reader`) runs as a background task and dispatches incoming frames
to the gate health store and the orchestrator callback.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from api_trafix.services.tcp_protocol import (
    build_heartbeat,
    build_output_ctrl,
    build_trig,
    decode_frames,
    parse_response,
    parse_trig_ack,
    parse_input_frame,
)

logger = logging.getLogger(__name__)

# Type for the callback invoked when a TCP frame arrives from a gate.
TcpFrameCallback = Callable[[str, dict], Awaitable[None]]


@dataclass
class TcpConnection:
    """Runtime state for one TCP gate connection."""

    gate_code: str
    host: str
    port: int
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    connected: bool = False
    last_rx_at: float = 0.0
    last_tx_at: float = 0.0
    heartbeat_fail_streak: int = 0
    pending_trigs: dict[str, int] = field(default_factory=dict)
    reader_task: asyncio.Task | None = None


class TcpGateway:
    """Async TCP client for gate controllers.

    Usage::

        gw = TcpGateway(gate_health=gate_health)
        gw.register_gate("1", "192.168.1.10", 5000)
        await gw.start()
        # ... later ...
        await gw.send_trig("1")
        await gw.stop()
    """

    def __init__(
        self,
        *,
        gate_health: Any = None,
        frame_callback: TcpFrameCallback | None = None,
        heartbeat_interval: float = 30.0,
        reconnect_interval: float = 5.0,
        max_reconnect_retries: int = 3,
    ) -> None:
        self.gate_health = gate_health
        self.frame_callback = frame_callback
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_retries = max_reconnect_retries

        self._connections: dict[str, TcpConnection] = {}
        self._heartbeat_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Connect to all registered gates and start the heartbeat loop."""
        self._stop_event.clear()
        for gate_code, conn in self._connections.items():
            asyncio.create_task(self._connect_gate(gate_code))
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("tcp_gateway: started with %d gates", len(self._connections))

    async def stop(self) -> None:
        """Disconnect all gates and cancel background tasks."""
        self._stop_event.set()
        for gate_code in list(self._connections):
            await self._disconnect_gate(gate_code)
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        logger.info("tcp_gateway: stopped")

    # -- registration -------------------------------------------------------

    def register_gate(
        self, gate_code: str, host: str, port: int = 5000
    ) -> None:
        """Register a gate for TCP connection (called at startup)."""
        self._connections[gate_code] = TcpConnection(
            gate_code=gate_code, host=host, port=port
        )
        logger.info("tcp_gateway: registered gate %s at %s:%s", gate_code, host, port)

    # -- query --------------------------------------------------------------

    def is_connected(self, gate_code: str) -> bool:
        conn = self._connections.get(gate_code)
        return conn is not None and conn.connected

    def get_health_all(self) -> list[dict]:
        return [
            {
                "gate_code": conn.gate_code,
                "host": conn.host,
                "port": conn.port,
                "connected": conn.connected,
                "last_rx_at": conn.last_rx_at,
                "heartbeat_fail_streak": conn.heartbeat_fail_streak,
            }
            for conn in self._connections.values()
        ]

    def get_connected_count(self) -> int:
        return sum(1 for c in self._connections.values() if c.connected)

    def get_total_count(self) -> int:
        return len(self._connections)

    # -- commands -----------------------------------------------------------

    async def send_trig(self, gate_code: str, output_id: str | None = None) -> bool:
        conn = self._connections.get(gate_code)
        if conn is None or not conn.connected or conn.writer is None:
            logger.warning("tcp_gateway: cannot TRIG %s — not connected", gate_code)
            return False
        frame = build_trig(output_id=output_id)
        try:
            conn.writer.write(frame)
            await conn.writer.drain()
            conn.last_tx_at = time.monotonic()
            return True
        except (OSError, asyncio.CancelledError) as exc:
            logger.error("tcp_gateway: TRIG %s failed: %s", gate_code, exc)
            conn.connected = False
            return False

    async def send_output_ctrl(
        self, gate_code: str, output_id: str, pulse_ms: int = 1000
    ) -> bool:
        conn = self._connections.get(gate_code)
        if conn is None or not conn.connected or conn.writer is None:
            logger.warning(
                "tcp_gateway: cannot outputCtrl %s — not connected", gate_code
            )
            return False
        frame = build_output_ctrl(output_id=output_id, pulse_ms=pulse_ms)
        try:
            conn.writer.write(frame)
            await conn.writer.drain()
            conn.last_tx_at = time.monotonic()
            return True
        except (OSError, asyncio.CancelledError) as exc:
            logger.error("tcp_gateway: outputCtrl %s failed: %s", gate_code, exc)
            conn.connected = False
            return False

    async def send_heartbeat(self, gate_code: str) -> bool:
        conn = self._connections.get(gate_code)
        if conn is None or not conn.connected or conn.writer is None:
            return False
        frame = build_heartbeat()
        try:
            conn.writer.write(frame)
            await conn.writer.drain()
            conn.last_tx_at = time.monotonic()
            return True
        except (OSError, asyncio.CancelledError):
            conn.connected = False
            return False

    # -- internal -----------------------------------------------------------

    async def _connect_gate(self, gate_code: str) -> None:
        conn = self._connections.get(gate_code)
        if conn is None:
            return

        retries = 0
        while not self._stop_event.is_set() and retries < self.max_reconnect_retries:
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(conn.host, conn.port),
                    timeout=10.0,
                )
                conn.reader = reader
                conn.writer = writer
                conn.connected = True
                conn.heartbeat_fail_streak = 0
                conn.last_rx_at = time.monotonic()
                logger.info(
                    "tcp_gateway: connected to gate %s at %s:%s",
                    gate_code,
                    conn.host,
                    conn.port,
                )
                # Start reader loop for this connection
                conn.reader_task = asyncio.create_task(
                    self._reader_loop(gate_code, conn)
                )
                return
            except (OSError, asyncio.TimeoutError) as exc:
                retries += 1
                logger.warning(
                    "tcp_gateway: connect to %s failed (attempt %s/%s): %s",
                    gate_code,
                    retries,
                    self.max_reconnect_retries,
                    exc,
                )
                await asyncio.sleep(self.reconnect_interval)

        logger.error(
            "tcp_gateway: giving up connecting to gate %s after %s attempts",
            gate_code,
            retries,
        )

    async def _disconnect_gate(self, gate_code: str) -> None:
        conn = self._connections.get(gate_code)
        if conn is None:
            return
        if conn.reader_task is not None:
            conn.reader_task.cancel()
            try:
                await conn.reader_task
            except asyncio.CancelledError:
                pass
        if conn.writer is not None:
            try:
                conn.writer.close()
                await conn.writer.wait_closed()
            except (OSError, asyncio.CancelledError):
                pass
        conn.connected = False
        conn.reader = None
        conn.writer = None
        logger.info("tcp_gateway: disconnected gate %s", gate_code)

    async def _reader_loop(self, gate_code: str, conn: TcpConnection) -> None:
        """Read frames from a TCP connection and dispatch them."""
        buffer = b""
        try:
            while conn.connected and conn.reader is not None:
                data = await conn.reader.read(4096)
                if not data:
                    logger.info("tcp_gateway: gate %s disconnected (EOF)", gate_code)
                    break
                buffer += data
                frames, buffer = decode_frames(buffer)
                for raw_frame in frames:
                    conn.last_rx_at = time.monotonic()
                    response = parse_response(raw_frame)
                    await self._dispatch_frame(gate_code, response)
        except (OSError, asyncio.CancelledError) as exc:
            if not isinstance(exc, asyncio.CancelledError):
                logger.warning("tcp_gateway: reader %s error: %s", gate_code, exc)
        finally:
            conn.connected = False
            if self.gate_health is not None:
                self.gate_health.on_tcp_input(gate_code, {"connected": False})

    async def _dispatch_frame(self, gate_code: str, data: dict) -> None:
        """Route a parsed TCP frame to the appropriate handler."""
        cmd = data.get("cmd", "")

        if cmd == "trig_ack":
            parsed = parse_trig_ack(data)
            logger.debug("tcp_gateway: %s TRIG ACK %s", gate_code, parsed)
            if self.frame_callback is not None:
                await self.frame_callback(gate_code, parsed)

        elif cmd in ("input", "inputFrame"):
            parsed = parse_input_frame(data)
            if self.gate_health is not None:
                self.gate_health.on_tcp_input(gate_code, parsed)
            logger.debug("tcp_gateway: %s input %s", gate_code, parsed)
            if self.frame_callback is not None:
                await self.frame_callback(gate_code, parsed)

        elif cmd == "heartbeat":
            if self.gate_health is not None:
                self.gate_health.on_heartbeat(gate_code, data)
            conn = self._connections.get(gate_code)
            if conn is not None:
                conn.heartbeat_fail_streak = 0
            logger.debug("tcp_gateway: %s heartbeat", gate_code)

        elif cmd == "status":
            if self.gate_health is not None:
                self.gate_health.on_heartbeat(gate_code, data)

        else:
            logger.debug("tcp_gateway: %s unknown frame: %s", gate_code, data)
            if self.frame_callback is not None:
                await self.frame_callback(gate_code, data)

    async def _heartbeat_loop(self) -> None:
        """Periodically send heartbeat to all connected gates."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self.heartbeat_interval)
            except asyncio.CancelledError:
                break
            for gate_code, conn in self._connections.items():
                if not conn.connected:
                    continue
                ok = await self.send_heartbeat(gate_code)
                if not ok:
                    conn.heartbeat_fail_streak += 1
                    if conn.heartbeat_fail_streak >= 3:
                        logger.warning(
                            "tcp_gateway: gate %s missed %s heartbeats, "
                            "marking disconnected",
                            gate_code,
                            conn.heartbeat_fail_streak,
                        )
                        conn.connected = False
                        if self.gate_health is not None:
                            self.gate_health.on_tcp_input(
                                gate_code, {"connected": False}
                            )
