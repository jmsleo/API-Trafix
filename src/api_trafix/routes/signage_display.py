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

from api_trafix.services.signage_display import get_signage_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/signage", tags=["Signage Display"])


@router.post("/vehicle-detected")
async def vehicle_detected(request: Request):
    """Called by GPIO bridge when a vehicle is detected on the arrival loop.

    Triggers the 'welcome' status on the signage display.
    """
    body = await request.json()
    gate_code = body.get("gate")
    if not gate_code:
        raise HTTPException(status_code=400, detail="gate code required")

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
    body = await request.json()
    gate_code = body.get("gate")
    if not gate_code:
        raise HTTPException(status_code=400, detail="gate code required")

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
    body = await request.json()
    status = body.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="status required")

    valid_statuses = ["welcome", "thanks", "idle"]
    if status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {valid_statuses}"
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


@router.get("/stream/{gate_code}")
async def signage_stream(gate_code: str):
    """SSE stream for real-time signage updates.

    The web-based signage display connects to this endpoint
    to receive live updates.
    """
    service = get_signage_service()

    async def event_generator():
        queue = service.subscribe(gate_code)
        try:
            # Send initial state
            state = service.get_state(gate_code)
            yield {
                "event": "status",
                "data": json.dumps({
                    "gate": gate_code,
                    "status": state.status,
                    "plate_number": state.plate_number,
                    "transaction_code": state.transaction_code,
                }),
            }

            # Send ads
            if state.ads:
                yield {
                    "event": "ads",
                    "data": json.dumps({
                        "gate": gate_code,
                        "ads": state.ads,
                    }),
                }

            # Send idle image
            if state.idle_image:
                yield {
                    "event": "idle",
                    "data": json.dumps({
                        "gate": gate_code,
                        "image": state.idle_image,
                    }),
                }

            # Listen for updates
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {
                        "event": message.get("event", "update"),
                        "data": json.dumps(message),
                    }
                except asyncio.TimeoutError:
                    # Send keepalive
                    yield {"event": "ping", "data": "{}"}
        finally:
            service.unsubscribe(gate_code)

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
        raise HTTPException(status_code=503, detail="Signage publisher not available")

    from api_trafix.config.database import async_session_maker
    try:
        async with async_session_maker() as db:
            count = await signage_publisher.sync_from_db(db)
        return {"status": "ok", "synced": count}
    except Exception as e:
        logger.exception("Content sync failed")
        raise HTTPException(status_code=500, detail=str(e))
