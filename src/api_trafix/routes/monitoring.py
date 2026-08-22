"""Monitoring endpoints for the Teknisi portal.

Consolidates live device status (controllers via ``gate_health``, cameras/LPR
via short HTTP probes, signage via the signage display service), MQTT broker
status, reader (RFID) events, and the device log.  Read endpoints stay open
(consistent with the existing monitoring design); the write endpoints
(``test`` / ``restart``) require admin or teknisi.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any

import httpx
import redis.exceptions
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from api_trafix.config.database import get_db
from api_trafix.config.redis import get_redis
from api_trafix.core.dependencies import get_current_admin_or_teknisi
from api_trafix.crud import device as device_crud
from api_trafix.crud import gate as gate_crud
from api_trafix.models import GateEvent, User
from api_trafix.models.devices import Device
from api_trafix.models.gates import Gate
from api_trafix.services.device_registry import RegistryError
from api_trafix.services.events import GATE_EVENTS_CHANNEL, SYSTEM_EVENTS_CHANNEL

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitoring", tags=["Monitoring"])

# Gate is considered online when a heartbeat is fresher than this.
_HEARTBEAT_TIMEOUT = timedelta(seconds=120)
# HTTP probe timeout for cameras / LPR units.
_PROBE_TIMEOUT = 1.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _kind_of(device_type: str) -> str:
    t = device_type.lower()
    if "controller" in t:
        return "controller"
    if "lpr" in t:
        return "lpr"
    if "camera" in t:
        return "camera"
    if "reader" in t:
        return "reader"
    if "signage" in t:
        return "signage"
    return "other"


async def _probe_http(url: str, timeout: float = _PROBE_TIMEOUT) -> dict[str, Any]:
    """Best-effort HTTP reachability probe. Never raises."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            resp = await client.get(url)
            latency = round((time.monotonic() - start) * 1000)
            return {
                "reachable": True,
                "latency_ms": latency,
                "status_code": resp.status_code,
                "detail": f"HTTP {resp.status_code} ({latency} ms)",
            }
    except (httpx.HTTPError, OSError) as exc:
        return {
            "reachable": False,
            "latency_ms": None,
            "status_code": None,
            "detail": f"Unreachable: {type(exc).__name__}",
        }


def _controller_health(request: Request, gate_code: str | None) -> dict[str, Any] | None:
    if gate_code is None:
        return None
    gate_health = getattr(request.app.state, "gate_health", None)
    if gate_health is None:
        return None
    return gate_health.get_one(gate_code)


def _signage_state(request: Request, gate_code: str | None) -> dict[str, Any] | None:
    if gate_code is None:
        return None
    service = getattr(request.app.state, "signage_display", None)
    if service is None:
        return None
    try:
        state = service.get_state(gate_code)
    except Exception:  # noqa: BLE001
        return None
    return {
        "gate_code": state.gate_code,
        "status": state.status,
        "plate_number": state.plate_number,
        "transaction_code": state.transaction_code,
        "last_updated": state.last_updated.isoformat(),
    }


def _live_status_for(
    device: Device,
    request: Request,
    health: dict[str, Any] | None = None,
    signage: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Derive a live status + detail for a device row.

    Returns ``(status, detail)`` where status is online/offline/trouble.
    """
    kind = _kind_of(device.type)
    if kind == "controller":
        if health is not None:
            status = "online" if health["is_online"] else "offline"
            return status, {
                "connection_type": health.get("connection_type"),
                "sensors": health.get("sensor_states"),
                "relays": health.get("relay_states"),
                "firmware": health.get("firmware_version"),
                "last_heartbeat_at": health.get("last_heartbeat_at"),
                "total_heartbeats": health.get("total_heartbeats"),
                "total_inputs": health.get("total_inputs"),
            }
        return "offline", {"detail": "No gate health entry registered"}

    if kind == "signage":
        if signage is not None:
            updated = signage.get("last_updated")
            is_recent = False
            if updated:
                try:
                    is_recent = (
                        datetime.now().astimezone()
                        - datetime.fromisoformat(updated)
                        < _HEARTBEAT_TIMEOUT
                    )
                except ValueError:
                    is_recent = False
            status = "online" if is_recent else "offline"
            return status, {"signage_status": signage.get("status"), "detail": updated}
        return "offline", {"detail": "No signage state registered"}

    # lpr / camera / reader / other: fall back to DB status + heartbeat age.
    detail: dict[str, Any] = {}
    if device.last_heartbeat is not None:
        fresh = datetime.now().astimezone() - device.last_heartbeat < _HEARTBEAT_TIMEOUT
        detail["last_heartbeat"] = device.last_heartbeat.isoformat()
        if fresh:
            return "online", detail
    return device.status if device.status in ("online", "trouble") else "offline", detail


def _registry_info(request: Request, gate_code: str | None, kind: str) -> dict[str, Any]:
    registry = getattr(request.app.state, "device_registry", None)
    if registry is None or gate_code is None:
        return {}
    try:
        if kind == "lpr":
            lpr = registry.lpr_for(gate_code)
            return {"base_url": lpr.base_url, "serves_http": lpr.serves_http}
        if kind == "controller":
            ctrl = registry.controller_for(gate_code)
            return {"serial_no": ctrl.serial_no, "connection_type": ctrl.connection_type}
        if kind == "camera":
            return {"cameras": [c.name for c in registry.cameras().values()]}
    except RegistryError:
        return {}
    return {}


async def _build_device_row(device: Device, request: Request, gate: Gate | None) -> dict[str, Any]:
    kind = _kind_of(device.type)
    gate_code = gate.gate_code if gate else None
    health = _controller_health(request, gate_code) if kind == "controller" else None
    signage = _signage_state(request, gate_code) if kind == "signage" else None
    status, detail = _live_status_for(device, request, health=health, signage=signage)

    row: dict[str, Any] = {
        "id": str(device.id),
        "name": device.name,
        "type": device.type,
        "kind": kind,
        "ip_address": device.ip_address,
        "gate_id": str(device.gate_id),
        "gate_code": gate_code,
        "gate_name": gate.name if gate else None,
        "config": device.config or {},
        "status": status,
        "last_heartbeat": device.last_heartbeat.isoformat() if device.last_heartbeat else None,
        "registry": _registry_info(request, gate_code, kind),
    }
    row.update(detail)
    return row


# ---------------------------------------------------------------------------
# Snapshot builders (shared by the REST endpoints and the SSE stream)
# ---------------------------------------------------------------------------

async def _build_device_snapshot(
    request: Request,
    db: AsyncSession,
    *,
    search: str | None = None,
    device_type: str | None = None,
    kind: str | None = None,
    gate_code: str | None = None,
    status_filter: str | None = None,
    probe: bool = True,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """Consolidated live device list merged with runtime health data."""
    stmt = select(Device, Gate).join(Gate, Device.gate_id == Gate.id)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(Device.name.ilike(like) | Device.ip_address.ilike(like))
    if device_type:
        stmt = stmt.where(Device.type.ilike(f"%{device_type.strip()}%"))
    if gate_code:
        stmt = stmt.where(Gate.gate_code == gate_code)

    rows = (await db.execute(stmt)).all()

    items = []
    for device, gate in rows:
        if kind and _kind_of(device.type) != kind:
            continue
        row = await _build_device_row(device, request, gate)
        if status_filter and row["status"] != status_filter:
            continue
        items.append(row)

    # Sort: controllers by gate_code, then by name.
    items.sort(key=lambda r: (r["gate_code"] or "", r["name"]))

    if probe:
        # Concurrent HTTP probes for lpr/camera devices (best-effort).
        async def _probe_item(item: dict[str, Any]) -> dict[str, Any]:
            if item["kind"] not in ("lpr", "camera"):
                return item
            url = None
            if item["kind"] == "lpr":
                base = item["registry"].get("base_url") or f"http://{item['ip_address']}:8090"
                url = f"{base}/checklpr"
            elif item["kind"] == "camera":
                snapshot = item["config"].get("snapshot_path", "/cgi-bin/snapshot.cgi")
                url = f"http://{item['ip_address']}{snapshot}"
            if url is None:
                return item
            result = await _probe_http(url)
            item["status"] = "online" if result["reachable"] else "offline"
            item["probe"] = result
            return item

        items = await asyncio.gather(*(_probe_item(i) for i in items))

    total = len(items)
    start = (page - 1) * page_size
    paged = items[start : start + page_size]

    return {
        "items": paged,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "last_updated": datetime.now().isoformat(),
    }


def _build_mqtt_snapshot(request: Request) -> dict[str, Any]:
    """MQTT broker status + TCP gateway counts for the Teknisi dashboard."""
    sys_status = getattr(request.app.state, "system_status", None)
    mqtt = sys_status.get_mqtt_status() if sys_status else {"connected": False}
    tcp = sys_status.get_tcp_status() if sys_status else {"connected_gates": 0, "total_gates": 0}
    tcp_gateway = getattr(request.app.state, "tcp_gateway", None)
    connections = tcp_gateway.get_health_all() if tcp_gateway else []
    return {"mqtt": mqtt, "tcp": {**tcp, "connections": connections}}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/devices")
async def monitoring_devices(
    request: Request,
    search: str | None = Query(default=None, max_length=100),
    device_type: str | None = Query(default=None, max_length=50),
    kind: str | None = Query(default=None, max_length=50),
    gate_code: str | None = Query(default=None, max_length=16),
    status_filter: str | None = Query(default=None, alias="status", max_length=10),
    probe: bool = Query(default=True, description="HTTP-probe lpr/camera devices"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Live device list merged with runtime health data."""
    return await _build_device_snapshot(
        request,
        db,
        search=search,
        device_type=device_type,
        kind=kind,
        gate_code=gate_code,
        status_filter=status_filter,
        probe=probe,
        page=page,
        page_size=page_size,
    )


@router.get("/mqtt")
async def monitoring_mqtt(request: Request):
    """MQTT broker status + TCP gateway counts for the Teknisi dashboard."""
    return _build_mqtt_snapshot(request)


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------

# Interval between periodic snapshot re-pushes.
_MONITORING_TICK_S = 5.0
# Debounce: skip an event-triggered snapshot if one was just pushed.
_MONITORING_MIN_INTERVAL_S = 2.0
# Comment keepalive cadence.
_MONITORING_KEEPALIVE_S = 15.0


def _sse_snapshot_frame(payload: dict[str, Any]) -> str:
    return f"event: snapshot\ndata: {json.dumps(payload, default=str)}\n\n"


async def _monitoring_stream_iter(
    request: Request,
    db: AsyncSession,
    pubsub: Any,
) -> Any:
    """Yield SSE frames: snapshot on connect, then on Redis events and a
    periodic tick. Best-effort: Redis outage degrades to tick-only."""
    last_push = 0.0
    last_keepalive = time.monotonic()

    async def _push_snapshot() -> str:
        nonlocal last_push
        devices = await _build_device_snapshot(
            request,
            db,
            probe=True,
            page=1,
            page_size=100,
        )
        mqtt = _build_mqtt_snapshot(request)
        last_push = time.monotonic()
        return _sse_snapshot_frame({"devices": devices, "mqtt": mqtt})

    try:
        yield await _push_snapshot()

        while True:
            if await request.is_disconnected():
                break

            if pubsub is None:
                await asyncio.sleep(_MONITORING_TICK_S)
                message = None
            else:
                try:
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=_MONITORING_TICK_S,
                    )
                except (redis.exceptions.RedisError, OSError):
                    message = None

            now = time.monotonic()
            if message is not None and (now - last_push) >= _MONITORING_MIN_INTERVAL_S:
                yield await _push_snapshot()
            elif message is None and (now - last_push) >= _MONITORING_TICK_S:
                yield await _push_snapshot()

            if (now - last_keepalive) >= _MONITORING_KEEPALIVE_S:
                yield ": keepalive\n\n"
                last_keepalive = now
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(GATE_EVENTS_CHANNEL, SYSTEM_EVENTS_CHANNEL)
            except (redis.exceptions.RedisError, OSError):
                pass
            try:
                # unsubscribe() alone does not return the dedicated pubsub
                # connection to the pool; without aclose() every SSE client
                # permanently consumes one slot until MaxConnectionsError.
                await pubsub.aclose()
            except (redis.exceptions.RedisError, OSError):
                pass


@router.get("/stream")
async def monitoring_stream(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events stream of the consolidated monitoring snapshot.

    Pushes ``event: snapshot`` with ``{devices, mqtt}`` on connect, then
    re-pushes on relevant Redis system/gate events and on a 5s tick so
    LPR/camera probes stay fresh. Comment keepalives every 15s. Open
    endpoint, consistent with the other monitoring reads.
    """
    try:
        r = await get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(GATE_EVENTS_CHANNEL, SYSTEM_EVENTS_CHANNEL)
    except (redis.exceptions.RedisError, OSError):
        pubsub = None

    return StreamingResponse(
        _monitoring_stream_iter(request, db, pubsub),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/signage/{gate_code}")
async def monitoring_signage(gate_code: str, request: Request):
    """Current signage display status for a gate."""
    service = getattr(request.app.state, "signage_display", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Signage service not available")
    state = service.get_state(gate_code)
    return {
        "gate_code": state.gate_code,
        "status": state.status,
        "plate_number": state.plate_number,
        "transaction_code": state.transaction_code,
        "ads_count": len(state.ads),
        "media_count": len(state.media),
        "has_idle_image": state.idle_image is not None,
        "last_updated": state.last_updated.isoformat(),
    }


@router.get("/reader-events")
async def monitoring_reader_events(
    gate: str | None = Query(default=None, max_length=16),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Recent RFID ``readCard`` events (reader activity)."""
    stmt = select(GateEvent).where(GateEvent.method == "readCard")
    if gate:
        stmt = stmt.where(GateEvent.gate_code == gate)
    total = len((await db.execute(stmt)).scalars().all())
    stmt = stmt.order_by(GateEvent.ts.desc()).offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "events": [
            {
                "id": str(r.id),
                "ts": r.ts.isoformat(),
                "gate": r.gate_code,
                "source": r.source,
                "detail": r.detail,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


@router.get("/logs")
async def monitoring_logs(
    gate: str | None = Query(default=None, max_length=16),
    source: str | None = Query(default=None, max_length=64),
    method: str | None = Query(default=None, max_length=64),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Device log: gate event history with filters."""
    conditions = []
    if gate:
        conditions.append(GateEvent.gate_code == gate)
    if source:
        conditions.append(GateEvent.source == source)
    if method:
        conditions.append(GateEvent.method == method)
    if date_from:
        try:
            conditions.append(GateEvent.ts >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date_from")
    if date_to:
        try:
            conditions.append(GateEvent.ts <= datetime.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date_to")

    total = len(
        (await db.execute(select(GateEvent.id).where(*conditions))).scalars().all()
    )
    stmt = (
        select(GateEvent)
        .where(*conditions)
        .order_by(GateEvent.ts.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(stmt)).scalars().all()
    return {
        "events": [
            {
                "id": str(r.id),
                "ts": r.ts.isoformat(),
                "gate": r.gate_code,
                "source": r.source,
                "method": r.method,
                "ticket_number": r.ticket_number,
                "detail": r.detail,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
    }


# ---------------------------------------------------------------------------
# Test connection / restart device
# ---------------------------------------------------------------------------

@router.post("/devices/{device_id}/test")
async def test_device(
    device_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin_or_teknisi),
):
    """Best-effort connectivity test for a device.

    - controller: gate health + TCP connect to host:port
    - lpr: ``GET base_url/checklpr`` (when ``serves_http``)
    - camera: ``GET http://host/snapshot_path``
    - reader: health of the attached gate controller
    - signage: signage display service state
    """
    device = await device_crud.get_by_id(db, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    gate = await gate_crud.get_by_id(db, device.gate_id)
    kind = _kind_of(device.type)
    gate_code = gate.gate_code if gate else None

    result: dict[str, Any] = {"reachable": False, "detail": "", "latency_ms": None}

    if kind == "controller":
        health = _controller_health(request, gate_code)
        if health and health.get("is_online"):
            result.update(reachable=True, detail="Controller online (recent heartbeat)")
        else:
            result["detail"] = "Controller has no recent heartbeat"
        # TCP probe if configured
        tcp_gateway = getattr(request.app.state, "tcp_gateway", None)
        if tcp_gateway is not None and gate_code and tcp_gateway.is_connected(gate_code):
            result.update(reachable=True, detail="Controller connected via TCP")
    elif kind == "lpr":
        base = None
        if gate_code:
            registry = getattr(request.app.state, "device_registry", None)
            try:
                base = registry.lpr_for(gate_code).base_url if registry else None
            except RegistryError:
                base = None
        base = base or (device.config or {}).get("base_url") or f"http://{device.ip_address}:8090"
        probe = await _probe_http(f"{base}/checklpr")
        result.update(probe)
    elif kind == "camera":
        snapshot = (device.config or {}).get("snapshot_path", "/cgi-bin/snapshot.cgi")
        probe = await _probe_http(f"http://{device.ip_address}{snapshot}")
        result.update(probe)
    elif kind == "reader":
        health = _controller_health(request, gate_code)
        if health and health.get("is_online"):
            result.update(reachable=True, detail="Reader attached to an online controller")
        else:
            result["detail"] = "Reader's gate controller is offline"
    elif kind == "signage":
        signage = _signage_state(request, gate_code)
        if signage is not None:
            result.update(reachable=True, detail=f"Signage state present ({signage.get('status')})")
        else:
            result["detail"] = "No signage state registered"
    else:
        # Generic TCP reachability on the device port.
        port = int((device.config or {}).get("port", 5000))
        start = time.monotonic()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(device.ip_address, port), timeout=_PROBE_TIMEOUT
            )
            writer.close()
            await writer.wait_closed()
            result.update(
                reachable=True,
                latency_ms=round((time.monotonic() - start) * 1000),
                detail=f"TCP {device.ip_address}:{port} reachable",
            )
        except (OSError, asyncio.TimeoutError) as exc:
            result["detail"] = f"TCP {device.ip_address}:{port} unreachable ({type(exc).__name__})"

    return {
        "device_id": str(device.id),
        "name": device.name,
        "type": device.type,
        "kind": kind,
        "status": "online" if result["reachable"] else "offline",
        **result,
    }


@router.post("/devices/{device_id}/restart")
async def restart_device(
    device_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    """Best-effort device restart.

    The gate wire protocol has no reboot opcode, so for controllers this
    performs a TCP reconnect if the gateway manages that gate; cameras/LPR
    are restarted over HTTP when a ``reboot_path`` is configured. Otherwise it
    reports ``not_supported`` without failing.
    """
    device = await device_crud.get_by_id(db, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device not found")
    gate = await gate_crud.get_by_id(db, device.gate_id)
    gate_code = gate.gate_code if gate else None
    kind = _kind_of(device.type)
    config = device.config or {}

    detail = ""
    status = "not_supported"

    if kind == "controller":
        tcp_gateway = getattr(request.app.state, "tcp_gateway", None)
        if tcp_gateway is not None and gate_code and tcp_gateway.is_connected(gate_code):
            await tcp_gateway._disconnect_gate(gate_code)
            await tcp_gateway._connect_gate(gate_code)
            status = "restarted" if tcp_gateway.is_connected(gate_code) else "failed"
            detail = "TCP connection restarted"
        else:
            detail = "No reboot opcode in the gate wire protocol (MQTT controller)"
    elif kind in ("lpr", "camera"):
        reboot_path = config.get("reboot_path")
        if reboot_path:
            probe = await _probe_http(f"http://{device.ip_address}{reboot_path}")
            status = "restarted" if probe["reachable"] else "failed"
            detail = probe["detail"]
        else:
            detail = f"No reboot_path configured for {device.type}"
    elif kind == "signage":
        signage_publisher = getattr(request.app.state, "signage_publisher", None)
        if signage_publisher is not None and gate_code:
            from api_trafix.config.database import async_session_maker
            try:
                async with async_session_maker() as sdb:
                    await signage_publisher.sync_from_db(sdb)
                status = "restarted"
                detail = "Signage content resynced to displays"
            except Exception as exc:  # noqa: BLE001
                status = "failed"
                detail = str(exc)
        else:
            detail = "Signage publisher not available"
    elif kind == "reader":
        detail = "Reader restart not supported (restart the attached controller instead)"
    else:
        detail = f"Restart not supported for device type {device.type}"

    from api_trafix.services.audit import log_action

    await log_action(
        db,
        module="device",
        action="restart",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Restarted device '{device.name}' ({device.type}) -> {status}",
    )

    return {
        "device_id": str(device.id),
        "name": device.name,
        "type": device.type,
        "kind": kind,
        "status": status,
        "detail": detail,
    }