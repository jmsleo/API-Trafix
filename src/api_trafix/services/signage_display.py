"""Signage Display Service — manages the state of web-based signage displays.

Replaces the Vala signage app's MQTT-based state management with an in-process
state store whose updates are pushed to web displays over SSE.

Each signage display connects via SSE and receives real-time updates:
- Gate status (welcome, thanks)
- Ads playlist
- Idle background
- Media playlist

Content (ads/idle/media) is populated by :class:`SignagePublisher` during its
periodic DB sync; status is driven by the orchestrator and GPIO callbacks.
Redis pub/sub channels are also published to for cross-process consumers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from api_trafix.services.events import publish_system_event

logger = logging.getLogger(__name__)


def device_gate(cfg: dict[str, Any] | None, device: Any) -> str:
    """Gate code a signage device is attached to, or ``""`` when unattached.

    An explicit ``gate_number`` in the device config decides the gate; an
    explicit empty value marks the screen as a standalone advertising screen
    (no gate overlay). Only when the key is absent do we fall back to the
    device's own gate relation.
    """
    cfg = cfg or {}
    if "gate_number" in cfg:
        value = cfg.get("gate_number")
        return str(value) if value not in (None, "") else ""
    return str(getattr(device.gate, "gate_code", None) or "")

# Redis channels for signage
SIGNAGE_CHANNEL_PREFIX = "signage:"
SIGNAGE_TEXT_CHANNEL = f"{SIGNAGE_CHANNEL_PREFIX}text"
SIGNAGE_ADS_CHANNEL = f"{SIGNAGE_CHANNEL_PREFIX}ads"
SIGNAGE_IDLE_CHANNEL = f"{SIGNAGE_CHANNEL_PREFIX}idle"
SIGNAGE_MEDIA_CHANNEL = f"{SIGNAGE_CHANNEL_PREFIX}media"


@dataclass
class SignageState:
    """Current state of a signage display."""

    gate_code: str
    status: str = "idle"  # welcome, thanks, idle
    plate_number: str = ""
    transaction_code: str = ""
    ads: list[dict[str, Any]] = field(default_factory=list)
    idle_image: dict[str, Any] | None = None
    media: list[dict[str, Any]] = field(default_factory=list)
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))


class SignageDisplayService:
    """Manages signage display state and pushes updates via Redis pub/sub."""

    def __init__(self, redis_client=None) -> None:
        self.redis = redis_client
        self._states: dict[str, SignageState] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def get_state(self, gate_code: str) -> SignageState:
        """Get current state for a gate's signage display."""
        if gate_code not in self._states:
            self._states[gate_code] = SignageState(gate_code=gate_code)
        return self._states[gate_code]

    async def update_status(self, gate_code: str, status: str, **kwargs: Any) -> None:
        """Update signage status and push to subscribers."""
        state = self.get_state(gate_code)
        state.status = status
        state.last_updated = datetime.now(UTC)

        # Update optional fields
        if "plate_number" in kwargs:
            state.plate_number = kwargs["plate_number"]
        if "transaction_code" in kwargs:
            state.transaction_code = kwargs["transaction_code"]

        message = {
            "event": "status",
            "gate": gate_code,
            "status": status,
            "plate_number": state.plate_number,
            "transaction_code": state.transaction_code,
            "timestamp": state.last_updated.isoformat(),
        }

        # Push directly to subscriber queues
        self._push_to_subscribers(gate_code, message)

        # Also publish to Redis for other processes
        await self._publish(SIGNAGE_TEXT_CHANNEL, message)

        logger.info("Signage %s: status -> %s", gate_code, status)

    async def update_ads(self, gate_code: str, ads: list[dict[str, Any]]) -> None:
        """Update ads playlist for a gate."""
        state = self.get_state(gate_code)
        if state.ads == ads:
            return
        state.ads = ads
        state.last_updated = datetime.now(UTC)

        message = {
            "event": "ads",
            "gate": gate_code,
            "ads": ads,
            "timestamp": state.last_updated.isoformat(),
        }
        self._push_to_subscribers(gate_code, message)
        await self._publish(SIGNAGE_ADS_CHANNEL, message)

        logger.info("Signage %s: ads updated (%d items)", gate_code, len(ads))

    async def update_idle(self, gate_code: str, image: dict[str, Any] | None) -> None:
        """Update idle background image."""
        state = self.get_state(gate_code)
        if state.idle_image == image:
            return
        state.idle_image = image
        state.last_updated = datetime.now(UTC)

        message = {
            "event": "idle",
            "gate": gate_code,
            "image": image,
            "timestamp": state.last_updated.isoformat(),
        }
        self._push_to_subscribers(gate_code, message)
        await self._publish(SIGNAGE_IDLE_CHANNEL, message)

        logger.info("Signage %s: idle image updated", gate_code)

    async def update_media(self, gate_code: str, media: list[dict[str, Any]]) -> None:
        """Update media playlist."""
        state = self.get_state(gate_code)
        if state.media == media:
            return
        state.media = media
        state.last_updated = datetime.now(UTC)

        message = {
            "event": "media",
            "gate": gate_code,
            "media": media,
            "timestamp": state.last_updated.isoformat(),
        }
        self._push_to_subscribers(gate_code, message)
        await self._publish(SIGNAGE_MEDIA_CHANNEL, message)

        logger.info("Signage %s: media updated (%d items)", gate_code, len(media))

    async def _publish(self, channel: str, data: dict[str, Any]) -> None:
        """Publish message to Redis channel."""
        if self.redis is None:
            return

        try:
            message = json.dumps(data, default=str)
            await self.redis.publish(channel, message)
        except Exception as e:
            logger.error("Redis publish failed: %s", e)

    def _push_to_subscribers(self, gate_code: str, message: dict[str, Any]) -> None:
        """Push a message directly to all subscriber queues for a gate."""
        queues = self._subscribers.get(gate_code)
        if queues is None:
            return
        for queue in list(queues):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.warning("Signage subscriber queue full for gate %s", gate_code)

    def subscribe(self, gate_code: str) -> asyncio.Queue:
        """Subscribe to updates for a specific gate."""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(gate_code, set()).add(queue)
        return queue

    def unsubscribe(self, gate_code: str, queue: asyncio.Queue | None = None) -> None:
        """Unsubscribe from updates."""
        queues = self._subscribers.get(gate_code)
        if queues is None:
            return
        if queue is not None:
            queues.discard(queue)
        elif queues:
            queues.discard(next(iter(queues)))
        if not queues:
            self._subscribers.pop(gate_code, None)


# Global instance
_signage_service: SignageDisplayService | None = None


def get_signage_service(redis_client=None) -> SignageDisplayService:
    """Get or create the global signage service instance."""
    global _signage_service
    if _signage_service is None:
        _signage_service = SignageDisplayService(redis_client)
    return _signage_service
