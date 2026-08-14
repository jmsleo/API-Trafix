"""MQTT transport for the gate hardware — the only module that imports aiomqtt.

Both the orchestrator and the publisher use this, so reconnection, auth and
envelope decoding are defined once. This is the API-Trafix port of
``trafix-api-mock/trafix/mqtt_bus.py``, moved from paho to aiomqtt.

The one thing the mock did that aiomqtt does not do for us is re-apply topic
handlers after a reconnect: paho's ``Client.on_message`` survives reconnects
because the subscription list lives on the client, while aiomqtt re-creates the
client on every (re)connect. The bus therefore owns the handler table and
re-subscribes everything registered whenever the connection comes back.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import aiomqtt
from aiomqtt.exceptions import MqttError

from api_trafix.services.protocol import Envelope, ProtocolError, parse

logger = logging.getLogger(__name__)

EnvelopeHandler = Callable[[str, Envelope], Awaitable[Any]]
RawHandler = Callable[[str, str], Awaitable[Any]]


class MqttBusError(Exception):
    """Raised when the bus is stopped or not running."""


class MqttBus:
    """Maintain a single MQTT connection and dispatch messages to handlers.

    Handlers are registered with :meth:`subscribe` (envelope-parsed) or
    :meth:`subscribe_raw` (plain text) and are re-subscribed on every reconnect,
    so a broker restart does not silently deafen a device. Handlers run
    sequentially in registration order, mirroring the mock's single-threaded
    paho loop; a failing handler is logged and the connection survives.

    Publishing is non-blocking: ``publish`` / ``publish_raw`` put the message on
    an outbound queue drained by the connected client. If the broker is down the
    message is dropped with a warning — a ticket print is never retried, because
    by the time the broker returns the driver already has the ticket.
    """

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        client_id: str = "api-trafix",
        keepalive: int = 60,
        reconnect_seconds: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self._username = username
        self._password = password
        self._client_id = client_id
        self._keepalive = keepalive
        self._reconnect_seconds = reconnect_seconds

        self._envelope_handlers: dict[str, list[EnvelopeHandler]] = {}
        self._raw_handlers: dict[str, list[RawHandler]] = {}
        self._commands: asyncio.Queue[tuple[Any, ...]] = asyncio.Queue()
        self._connected = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Start the background connection task. Returns immediately.

        The task reconnects forever (with backoff) until :meth:`stop`; a broker
        being down is not an error the caller must handle.
        """
        if self._task is not None and not self._task.done():
            raise MqttBusError("bus already running")
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="mqtt-bus")

    async def stop(self) -> None:
        self._stop.set()
        self._connected.clear()
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def wait_connected(self, timeout: float | None = None) -> bool:
        """True once the broker accepted the connection, False on timeout."""
        try:
            await asyncio.wait_for(self._connected.wait(), timeout)
            return self._connected.is_set()
        except TimeoutError:
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    # -- pub / sub ---------------------------------------------------------

    def subscribe(self, topic: str, handler: EnvelopeHandler) -> None:
        """Handle decoded envelopes on ``topic``."""
        first = self._is_new_topic(topic)
        self._envelope_handlers.setdefault(topic, []).append(handler)
        if first and self.is_connected:
            self._commands.put_nowait(("subscribe", topic))

    def subscribe_raw(self, topic: str, handler: RawHandler) -> None:
        """Handle the payload as a plain string.

        The exit LPR announcement and the signage topic carry bare JSON, not an
        envelope, so they cannot go through :meth:`subscribe`.
        """
        first = self._is_new_topic(topic)
        self._raw_handlers.setdefault(topic, []).append(handler)
        if first and self.is_connected:
            self._commands.put_nowait(("subscribe", topic))

    def publish(self, topic: str, message: Envelope, *, retain: bool = False) -> None:
        """Queue an envelope for the connected client (non-blocking)."""
        self.publish_raw(topic, message.to_json(), retain=retain)

    def publish_raw(
        self, topic: str, payload: str, *, retain: bool = False, qos: int = 1
    ) -> None:
        if not self.is_connected:
            logger.warning("dropping publish to %s (broker not connected)", topic)
            return
        logger.debug("-> %s %s", topic, payload)
        self._commands.put_nowait(("publish", topic, payload, qos, retain))

    def _is_new_topic(self, topic: str) -> bool:
        return topic not in self._envelope_handlers and topic not in self._raw_handlers

    # -- internals ---------------------------------------------------------

    def _topics(self) -> list[str]:
        return [
            *self._envelope_handlers.keys(),
            *self._raw_handlers.keys(),
        ]

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=self.host,
                    port=self.port,
                    username=self._username,
                    password=self._password,
                    identifier=f"{self._client_id}-{uuid.uuid4().hex[:6]}",
                    keepalive=self._keepalive,
                ) as client:
                    for topic in self._topics():
                        await client.subscribe(topic, qos=1)
                    self._connected.set()
                    logger.info(
                        "connected to MQTT broker %s:%s as %s",
                        self.host,
                        self.port,
                        self._client_id,
                    )
                    reader = asyncio.create_task(self._read(client))
                    writer = asyncio.create_task(self._write(client))
                    try:
                        done, _pending = await asyncio.wait(
                            {reader, writer}, return_when=asyncio.FIRST_EXCEPTION
                        )
                        for task in done:
                            exc = task.exception()
                            if exc is not None:
                                raise exc
                    finally:
                        for task in (reader, writer):
                            task.cancel()
                        await asyncio.gather(reader, writer, return_exceptions=True)
                        self._connected.clear()
            except asyncio.CancelledError:
                break
            except MqttError as exc:
                if self._stop.is_set():
                    break
                logger.warning(
                    "MQTT disconnected (%s); reconnecting in %ss",
                    exc,
                    self._reconnect_seconds,
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), self._reconnect_seconds)
                except TimeoutError:
                    pass

    async def _read(self, client: aiomqtt.Client) -> None:
        async for message in client.messages:
            topic = str(message.topic)
            raw_handlers = self._raw_handlers.get(topic)
            if raw_handlers:
                text = message.payload.decode("utf-8", errors="replace")
                for handler in raw_handlers:
                    await self._safely(handler, topic, text)

            envelope_handlers = self._envelope_handlers.get(topic)
            if not envelope_handlers:
                continue

            try:
                envelope = parse(message.payload)
            except ProtocolError as exc:
                logger.warning("dropping malformed message on %s: %s", topic, exc)
                continue

            for handler in envelope_handlers:
                await self._safely(handler, topic, envelope)

    async def _write(self, client: aiomqtt.Client) -> None:
        while True:
            command = await self._commands.get()
            if command[0] == "subscribe":
                await client.subscribe(command[1], qos=1)
            else:
                _kind, topic, payload, qos, retain = command
                await client.publish(topic, payload, qos=qos, retain=retain)

    @staticmethod
    async def _safely(handler: Callable[..., Awaitable[Any]], topic: str, payload: Any) -> None:
        """A failing handler must not kill the network loop."""
        try:
            await handler(topic, payload)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("handler for %s failed", topic)
