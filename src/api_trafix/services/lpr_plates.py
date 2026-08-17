"""In-memory plate buffer for LPR units that push instead of being polled.

The ECV86 camera (protoType 3) announces a read over MQTT (``cmd: result``)
and pushes the snapshot as a separate multipart POST. The two halves can
arrive in either order, seconds apart, so the orchestrator and the upload
endpoint cooperate through this buffer:

* the MQTT handler calls :meth:`set_plate` — the plate is ready to print even
  before the image lands;
* the upload endpoint calls :meth:`attach_image`, matching the picture to the
  buffered read by the ``full_pic_path`` basename;
* at the ticket button the orchestrator calls :meth:`take_plate`.

Everything runs on the API's single event loop (FastAPI handlers and the
orchestrator task share it), so no lock is needed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _PlateEntry:
    plate: str | None = None
    image_url: str = ""
    seen_at: float = 0.0
    # full_pic_path basename -> this gate, for the upload endpoint to match on.
    file_basenames: set[str] = field(default_factory=set)


class LprPlateBuffer:
    """Correlate pushed LPR reads with their pushed snapshots, per gate."""

    def __init__(self) -> None:
        self._entries: dict[str, _PlateEntry] = {}
        # full_pic_path basename -> gate code (from the last MQTT result).
        self._basename_to_gate: dict[str, str] = {}
        # basename -> stored relative path of snapshots that arrived before the
        # plate result (so a late MQTT message can still pick the image up).
        self._uploaded: dict[str, str] = {}

    # -- producers ---------------------------------------------------------

    def set_plate(self, gate: str, plate: str, *basenames: str) -> None:
        """Record a plate read for ``gate``, keyed for later image matching."""
        entry = self._entries.setdefault(gate, _PlateEntry())
        entry.plate = plate
        entry.seen_at = time.monotonic()
        for basename in basenames:
            if basename:
                entry.file_basenames.add(basename)
                self._basename_to_gate[basename] = gate
                if basename in self._uploaded:
                    entry.image_url = self._uploaded[basename]

    def attach_image(self, basename: str, relative: str) -> str | None:
        """Store an uploaded snapshot and return the gate it belongs to.

        Returns ``None`` when no plate read has announced this file yet.
        """
        self._uploaded[basename] = relative
        gate = self._basename_to_gate.get(basename)
        if gate is not None and gate in self._entries:
            self._entries[gate].image_url = relative
        logger.debug("stored camera image %s (%s)", basename, relative)
        return gate

    # -- consumer ----------------------------------------------------------

    def take_plate(self, gate: str, max_age: float) -> tuple[str, str]:
        """Consume the freshest buffered plate for ``gate``.

        Returns ``(plate, image_url)`` or ``("", "")`` when there is nothing
        fresh. A plate older than ``max_age`` is discarded rather than handed
        to a later car.
        """
        entry = self._entries.get(gate)
        if entry is None or not entry.plate:
            return "", ""
        age = time.monotonic() - entry.seen_at
        if age > max_age:
            logger.debug("gate %s: buffered plate aged %.1fs, dropping", gate, age)
            entry.plate = None
            return "", ""
        plate, image_url = entry.plate, entry.image_url
        entry.plate = None
        return plate, image_url
