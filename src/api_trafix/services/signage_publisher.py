"""Publish signage content to the pw-signage display over MQTT.

The display app (``pw-signage``) runs on the legacy box and connects to the
legacy broker, so messages mirror to every configured broker: the primary
(new-server) bus and one bus per ``signage_legacy_brokers`` entry. The display
fetches media files over HTTP from ``signage_public_base_url`` and plays what
it is told:

- ``gate/text``   ``{"status":"..."}``          status / alert text
- ``gate/idle``   ``{"image_name","image_url",...}``  idle background
- ``gate/ads``    ``{"ads_name","image_url","sound_url",...}``  ad slideshow
- ``gate/media``  ``{"gate_number","media_type","url","audio_url",...}``  playlist

Only changed content is re-published (fingerprinted per device+content), so a
60s periodic sync does not spam the display with duplicates; a full re-publish
happens once when the API restarts (fresh in-memory state). Deactivated content
is re-published with an expired date so the display's own cleanup purges it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.models import Device, Signage, SignageAssignment, SignageContent
from api_trafix.models.signage import SignageContentType
from api_trafix.services.mqtt_bus import MqttBus
from api_trafix.services.protocol import gate_status_topic, signage

logger = logging.getLogger(__name__)

DEFAULT_TEXT_TOPIC = "gate/text"
DEFAULT_MEDIA_TOPIC = "gate/media"
DEFAULT_ADS_TOPIC = "gate/ads"
DEFAULT_IDLE_TOPIC = "gate/idle"

_FAR_FUTURE = "2099-12-31"


def _compact(payload: dict) -> str:
    return json.dumps(payload, separators=(",", ":"))


def _today() -> datetime.date:
    return datetime.now(UTC).date()


class SignagePublisher:
    """Mirror signage content and gate status to every configured broker."""

    def __init__(
        self,
        primary: MqttBus,
        mirrors: list[MqttBus],
        *,
        base_url: str,
    ) -> None:
        self.primary = primary
        self.mirrors = list(mirrors)
        self.base_url = base_url.rstrip("/")
        self._published: dict[tuple[str, str], str] = {}
        self._idle_fingerprint: dict[str, str] = {}
        self._sync_lock = asyncio.Lock()

    @property
    def buses(self) -> list[MqttBus]:
        return [self.primary, *self.mirrors]

    # -- gate status --------------------------------------------------------

    def publish_gate_status(self, gate: str, status: str) -> None:
        """Keep the legacy ``/GATE/IN/N/status`` contract and mirror ``gate/text``."""
        payload = signage(status)
        self.primary.publish_raw(gate_status_topic(gate), payload)
        for bus in self.buses:
            bus.publish_raw(DEFAULT_TEXT_TOPIC, payload)

    # -- content sync -------------------------------------------------------

    def _file_url(self, content_id: uuid.UUID) -> str:
        return f"{self.base_url}/signages/contents/{content_id}/file"

    def _window(self, content: SignageContent) -> tuple[str, str]:
        start = content.broadcast_start.date().isoformat() if content.broadcast_start else _today().isoformat()
        end = content.broadcast_end.date().isoformat() if content.broadcast_end else _FAR_FUTURE
        return start, end

    @staticmethod
    def _expired_window() -> tuple[str, str]:
        yesterday = (_today() - timedelta(days=1)).isoformat()
        return yesterday, yesterday

    def _publish_content(
        self,
        device: Device,
        content: SignageContent,
        gate_number: str,
        *,
        expired: bool,
    ) -> None:
        cfg = device.config or {}
        start, end = self._expired_window() if expired else self._window(content)
        url = self._file_url(content.id)
        topics = (
            cfg.get("media_topic", DEFAULT_MEDIA_TOPIC),
            cfg.get("ads_topic", DEFAULT_ADS_TOPIC),
            cfg.get("idle_topic", DEFAULT_IDLE_TOPIC),
        )
        for bus in self.buses:
            if content.content_type == SignageContentType.VIDEO:
                bus.publish_raw(
                    topics[0],
                    _compact(
                        {
                            "gate_number": gate_number,
                            "media_type": "video",
                            "url": url,
                            "audio_url": "",
                            "title": content.title,
                            "start_date": start,
                            "end_date": end,
                        }
                    ),
                )
            elif content.content_type == SignageContentType.IMAGE:
                bus.publish_raw(
                    topics[1],
                    _compact(
                        {
                            "ads_name": content.title,
                            "image_url": url,
                            "sound_url": "",
                            "start_date": start,
                            "end_date": end,
                        }
                    ),
                )

    def _publish_idle(self, device: Device, content: SignageContent, *, expired: bool) -> None:
        cfg = device.config or {}
        start, end = self._expired_window() if expired else self._window(content)
        topic = cfg.get("idle_topic", DEFAULT_IDLE_TOPIC)
        payload = _compact(
            {
                "image_name": content.title,
                "image_url": self._file_url(content.id),
                "start_date": start,
                "end_date": end,
            }
        )
        for bus in self.buses:
            bus.publish_raw(topic, payload)

    async def sync_from_db(self, db: AsyncSession) -> int:
        """Publish assigned active signage content to its display device."""
        async with self._sync_lock:
            return await self._sync_locked(db)

    async def _sync_locked(self, db: AsyncSession) -> int:
        if not all(bus.is_connected for bus in self.buses):
            logger.warning("signage: not all brokers connected, deferring sync")
            return 0
        devices = (
            (
                await db.execute(
                    select(Device)
                    .where(Device.type.ilike("%signage%"))
                    .options(selectinload(Device.gate))
                )
            )
            .scalars()
            .all()
        )
        if not devices:
            logger.info("signage: no Signage devices configured, skipping sync")
            return 0

        by_code: dict[str, Device] = {}
        for device in devices:
            code = (device.config or {}).get("signage_code") or device.name
            by_code[str(code)] = device

        rows = (
            await db.execute(
                select(Signage, SignageContent, SignageAssignment)
                .join(SignageAssignment, SignageAssignment.signage_id == Signage.id)
                .join(SignageContent, SignageContent.id == SignageAssignment.content_id)
                .order_by(SignageContent.created_at.asc())
            )
        ).all()

        first_image: dict[str, SignageContent] = {}
        first_image_device: dict[str, Device] = {}
        published = 0

        for signage_row, content, assignment in rows:
            device = by_code.get(signage_row.code)
            if device is None:
                continue
            cfg = device.config or {}
            gate_number = str(cfg.get("gate_number") or getattr(device.gate, "gate_code", None) or "")
            key = (str(device.id), str(content.id))
            active = bool(content.is_active and assignment.is_active)
            fingerprint = (
                f"{content.updated_at.isoformat()}|{content.is_active}|{assignment.is_active}"
            )

            if not active:
                if key in self._published:
                    self._publish_content(device, content, gate_number, expired=True)
                    self._published.pop(key, None)
                    published += 1
                if self._idle_fingerprint.get(str(device.id), "").startswith(f"{content.id}|"):
                    self._publish_idle(device, content, expired=True)
                    self._idle_fingerprint.pop(str(device.id), None)
                continue

            if self._published.get(key) == fingerprint:
                continue

            self._publish_content(device, content, gate_number, expired=False)
            self._published[key] = fingerprint
            published += 1

            if content.content_type == SignageContentType.IMAGE:
                first_image.setdefault(str(device.id), content)
                first_image_device.setdefault(str(device.id), device)

        for device_id, content in first_image.items():
            device = first_image_device[device_id]
            fp = f"{content.id}|{content.updated_at.isoformat()}"
            if self._idle_fingerprint.get(device_id) == fp:
                continue
            self._publish_idle(device, content, expired=False)
            self._idle_fingerprint[device_id] = fp

        if published:
            logger.info("signage: published %d content change(s)", published)
        return published
