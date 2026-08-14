"""Resolve the hardware layout from the ``devices`` table.

The mock resolves gate controllers, LPR units and cameras from
``config/devices.yaml``; API-Trafix keeps the same information in the database
so an operator can re-point a device without touching files on the host. This
module is a thin, cached read of ``devices`` joined to ``gates``, keyed by the
wire ``gate_code`` ("1"/"2") the hardware speaks.

A device's ``type`` string decides its role::

    Controller / MQTT  -> gate controller (relay + printer)
    Camera LPR / LPR   -> plate camera
    Camera             -> CCTV snapshot

The ``config`` JSON column holds the optional per-device knobs:

* controller: ``{"serial_no": "441D6491AF17"}``
* lpr: ``{"serves_http": false, "pos_topic_gate": "1"}``
* camera: ``{"snapshot_path": "/cgi-bin/snapshot.cgi"}``
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from api_trafix.models.devices import Device
from api_trafix.models.gates import Gate

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class RegistryError(KeyError):
    """Raised when no device is configured for a requested gate or role."""


@dataclass(frozen=True)
class GateController:
    """The relay + printer board for one gate."""

    name: str
    gate_code: str
    host: str
    serial_no: str
    gate_type: str


@dataclass(frozen=True)
class LprDevice:
    """An LPR unit.

    The entry unit answers ``GET :8090/checklpr``. The exit unit publishes to
    MQTT instead and, on site, serves nothing at all — see flow.md §7.2.
    """

    name: str
    gate_code: str
    host: str
    base_url: str
    serves_http: bool
    # The gate number the device actually uses on the `gate/out/{gate}/pos`
    # wire topic. Decoupled from the logical `gate` because the real exit LPR
    # (.149) publishes with "1" while the exit lane is logically gate "2"
    # (flow.md §8). Defaults to the logical gate.
    pos_topic_gate: str


@dataclass(frozen=True)
class CameraDevice:
    """A Uniview IP camera used for the CCTV snapshot."""

    name: str
    host: str
    snapshot_path: str
    username: str | None = None
    password: str | None = None


def _as_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in {"1", "true", "yes", "on"}


def _as_str(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


class DeviceRegistry:
    """Cached view of the hardware layout, keyed by ``Gate.gate_code``.

    :meth:`reload` re-reads the database and atomically swaps the cached maps,
    so it can be called by admin tooling while the orchestrator keeps running.
    """

    def __init__(self, session_factory: Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self._controllers: dict[str, GateController] = {}
        self._lpr: dict[str, LprDevice] = {}
        self._cameras: dict[str, CameraDevice] = {}

    # -- lifecycle ---------------------------------------------------------

    async def reload(self) -> None:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Device, Gate).join(Gate, Device.gate_id == Gate.id)
                )
            ).all()

        controllers: dict[str, GateController] = {}
        lpr: dict[str, LprDevice] = {}
        cameras: dict[str, CameraDevice] = {}

        for device, gate in rows:
            code = gate.gate_code
            if not code:
                logger.warning(
                    "device %s is attached to gate %s which has no gate_code "
                    "(no wire id) — skipping",
                    device.name,
                    gate.id,
                )
                continue
            config = device.config or {}
            kind = device.type.lower()
            if "lpr" in kind:
                lpr[code] = LprDevice(
                    name=device.name,
                    gate_code=code,
                    host=device.ip_address,
                    base_url=_as_str(
                        config.get("base_url"), f"http://{device.ip_address}:8090"
                    ).rstrip("/"),
                    serves_http=_as_bool(config.get("serves_http"), True),
                    pos_topic_gate=_as_str(config.get("pos_topic_gate"), code),
                )
            elif "camera" in kind:
                cameras[device.name] = CameraDevice(
                    name=device.name,
                    host=device.ip_address,
                    snapshot_path=_as_str(
                        config.get("snapshot_path"), "/cgi-bin/snapshot.cgi"
                    ),
                    username=config.get("username") or None,
                    password=config.get("password") or None,
                )
            elif "controller" in kind:
                controllers[code] = GateController(
                    name=device.name,
                    gate_code=code,
                    host=device.ip_address,
                    serial_no=_as_str(config.get("serial_no")),
                    gate_type=gate.type.value,
                )
            else:
                logger.warning("device %s has unknown type %r — ignored", device.name, device.type)

        with self._lock:
            self._controllers = controllers
            self._lpr = lpr
            self._cameras = cameras

        logger.info(
            "device registry loaded: %d controllers, %d lpr, %d cameras",
            len(controllers),
            len(lpr),
            len(cameras),
        )

    # -- lookups -----------------------------------------------------------

    def controllers(self) -> dict[str, GateController]:
        with self._lock:
            return dict(self._controllers)

    def lpr_items(self) -> dict[str, LprDevice]:
        with self._lock:
            return dict(self._lpr)

    def cameras(self) -> dict[str, CameraDevice]:
        with self._lock:
            return dict(self._cameras)

    def controller_for(self, gate_code: str) -> GateController:
        try:
            return self.controllers()[str(gate_code)]
        except KeyError:
            raise RegistryError(
                f"no gate controller configured for gate {gate_code!r}"
            ) from None

    def lpr_for(self, gate_code: str) -> LprDevice:
        try:
            return self.lpr_items()[str(gate_code)]
        except KeyError:
            raise RegistryError(
                f"no LPR configured for gate {gate_code!r}"
            ) from None

    def entry_gate_codes(self) -> set[str]:
        return {
            code
            for code, controller in self.controllers().items()
            if controller.gate_type == "gate_in"
        }

    def exit_gate_codes(self) -> set[str]:
        return {
            code
            for code, controller in self.controllers().items()
            if controller.gate_type == "gate_out"
        }
