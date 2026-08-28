"""Signage display API endpoints.

Provides endpoints for:
- GPIO bridge callbacks (vehicle detected, help button)
- Signage status queries
- SSE stream for real-time updates
- Signage control (manual status updates)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from api_trafix.services.signage_display import get_signage_service, device_gate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signage", tags=["Signage Display"])


def _sse_frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _body(request: Request) -> dict[str, Any]:
    """The request body as a dict, tolerant of how it was sent.

    The GPIO bridge posts JSON (``requests.post(..., json=...)``), but a bare
    ``curl -d '{"gate":"1"}'`` without the ``Content-Type`` header sends the
    same body as ``application/x-www-form-urlencoded``. Try JSON regardless of
    the header so both work; fall back to form fields; an empty/invalid body
    becomes ``{}`` so a caller mistake returns a 400 instead of a 500.
    """
    content_type = request.headers.get("content-type", "")

    if "application/json" in content_type:
        try:
            payload = await request.json()
        except (ValueError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    raw = await request.body()
    if raw:
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                return payload
        except (ValueError, json.JSONDecodeError):
            pass

    if "form-data" in content_type or "x-www-form-urlencoded" in content_type:
        form = await request.form()
        return {key: form[key] for key in form}

    return {}


async def _resolve_screen(key: str) -> dict[str, Any]:
    """Resolve a stream key (signage code or gate code) to screen info.

    Returns a dict with:
      - ``key``: the queue key to subscribe to (the gate code for
        gate-attached screens, otherwise the signage code)
      - ``screen_key``: signage code of the screen (the key itself if unknown)
      - ``gate_code``: gate code if the screen is attached to a gate, else None
      - ``mode``: ``"gate"`` if attached to a gate, else ``"ads"``

    Unknown keys fall back to ``mode="gate"`` so gate-only streams (and the
    legacy static display page) keep working even without a Device row.
    """
    try:
        from api_trafix.config.database import async_session_maker
        from api_trafix.models import Device
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with async_session_maker() as db:
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
            screens: list[tuple[str, str | None]] = []
            for device in devices:
                cfg = device.config or {}
                code = str(cfg.get("signage_code") or device.name)
                gate = device_gate(cfg, device) or None
                screens.append((code, gate))

            for code, gate in screens:
                if code == key:
                    if gate:
                        return {
                            "key": gate,
                            "screen_key": code,
                            "gate_code": gate,
                            "mode": "gate",
                        }
                    return {
                        "key": code,
                        "screen_key": code,
                        "gate_code": None,
                        "mode": "ads",
                    }

            for code, gate in screens:
                if gate and gate == key:
                    return {
                        "key": gate,
                        "screen_key": code,
                        "gate_code": gate,
                        "mode": "gate",
                    }
    except Exception:  # noqa: BLE001
        logger.exception("failed to resolve signage screen %s", key)

    return {"key": key, "screen_key": key, "gate_code": key, "mode": "gate"}


@router.post("/vehicle-detected")
async def vehicle_detected(request: Request):
    """Called by GPIO bridge when a vehicle is detected on the arrival loop.

    Triggers the 'welcome' status on the signage display.
    """
    body = await _body(request)
    gate_code = body.get("gate")
    if not gate_code:
        raise HTTPException(status_code=400, detail="kode gerbang wajib diisi")

    service = get_signage_service()
    await service.update_status(gate_code, "welcome")

    # Also publish to MQTT for backward compatibility
    signage_publisher = getattr(request.app.state, "signage_publisher", None)
    if signage_publisher:
        signage_publisher.publish_gate_status(gate_code, "welcome")

    return {"status": "ok", "gate": gate_code, "signage_status": "welcome"}


@router.post("/help-button")
async def help_button(request: Request):
    """Called by GPIO bridge when the help button is pressed.

    Logs the event and could trigger an intercom call.
    """
    body = await _body(request)
    gate_code = body.get("gate")
    if not gate_code:
        raise HTTPException(status_code=400, detail="kode gerbang wajib diisi")

    logger.info("Help button pressed on gate %s", gate_code)

    # Publish system event for monitoring
    from api_trafix.services.events import publish_system_event
    await publish_system_event(
        "help_button_pressed",
        gate=gate_code,
    )

    return {"status": "ok", "gate": gate_code}


@router.get("/status/{gate_code}")
async def get_signage_status(gate_code: str):
    """Get current signage status for a gate."""
    service = get_signage_service()
    state = service.get_state(gate_code)

    return {
        "gate_code": state.gate_code,
        "status": state.status,
        "plate_number": state.plate_number,
        "transaction_code": state.transaction_code,
        "ads_count": len(state.ads),
        "has_idle_image": state.idle_image is not None,
        "media_count": len(state.media),
        "last_updated": state.last_updated.isoformat(),
    }


@router.post("/status/{gate_code}")
async def update_signage_status(gate_code: str, request: Request):
    """Manually update signage status (for testing or admin control)."""
    body = await _body(request)
    status = body.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="status wajib diisi")

    valid_statuses = ["welcome", "thanks", "idle"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Status tidak valid. Harus salah satu dari: {valid_statuses}"
        )

    service = get_signage_service()
    await service.update_status(
        gate_code,
        status,
        plate_number=body.get("plate_number", ""),
        transaction_code=body.get("transaction_code", ""),
    )

    # Also publish to MQTT for backward compatibility
    signage_publisher = getattr(request.app.state, "signage_publisher", None)
    if signage_publisher:
        signage_publisher.publish_gate_status(gate_code, status)

    return {"status": "ok", "gate": gate_code, "signage_status": status}


@router.get("/stream/{key}")
async def signage_stream(key: str):
    """SSE stream for real-time signage updates.

    The key may be a signage code (``SCR1``) or a gate code (``1``). The
    stream resolves the screen, announces its mode (``gate`` vs ``ads``) and
    then pushes status + per-screen ads/idle/media.

    The web-based signage display connects to this endpoint
    to receive live updates.
    """
    info = await _resolve_screen(key)
    service = get_signage_service()
    subscribe_key = info["key"]

    async def event_generator():
        queue = service.subscribe(subscribe_key)
        try:
            # Announce the resolved screen/mode first.
            yield _sse_frame("screen", info)

            # Send initial state
            state = service.get_state(subscribe_key)
            if info["mode"] == "gate":
                yield _sse_frame("status", {
                    "gate": info["gate_code"],
                    "status": state.status,
                    "plate_number": state.plate_number,
                    "transaction_code": state.transaction_code,
                })

            # Send ads
            if state.ads:
                yield _sse_frame("ads", {
                    "gate": subscribe_key,
                    "ads": state.ads,
                })

            # Send idle image
            if state.idle_image:
                yield _sse_frame("idle", {
                    "gate": subscribe_key,
                    "image": state.idle_image,
                })

            # Send media playlist
            if state.media:
                yield _sse_frame("media", {
                    "gate": subscribe_key,
                    "media": state.media,
                })

            # Listen for updates
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield _sse_frame(message.get("event", "status"), message)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            service.unsubscribe(subscribe_key, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/content/sync")
async def sync_content(request: Request):
    """Trigger a content sync from database to displays."""
    signage_publisher = getattr(request.app.state, "signage_publisher", None)
    if signage_publisher is None:
        raise HTTPException(status_code=503, detail="Publisher signage tidak tersedia")

    from api_trafix.config.database import async_session_maker
    try:
        async with async_session_maker() as db:
            count = await signage_publisher.sync_from_db(db)
        return {"status": "ok", "synced": count}
    except Exception as e:
        logger.exception("Content sync failed")
        raise HTTPException(status_code=500, detail=str(e))
