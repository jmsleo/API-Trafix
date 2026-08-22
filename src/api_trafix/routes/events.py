"""Unified real-time event stream and paginated gate event history.

``GET /api/events/stream`` merges the gate-cycle SSE (barrier/settle) and
the system-health SSE (MQTT status, heartbeat, online/offline) into one
stream.  ``GET /api/gate/events`` provides paginated history from the DB.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Callable
from typing import Any

import redis.exceptions
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from api_trafix.config.redis import get_redis
from api_trafix.config.database import get_db
from api_trafix.models.gate_events import GateEvent

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Events"])

GATE_EVENTS_CHANNEL = "gate:events"
SYSTEM_EVENTS_CHANNEL = "system:events"


def _sse_frame(data: dict[str, Any]) -> str:
    return f"event: {data.get('type', 'message')}\ndata: {json.dumps(data)}\n\n"


async def _unified_events_iter(
    *,
    gate: str | None,
    snapshot: AsyncGenerator[dict, None] | None,
    pubsub: Any | None,
    disconnect: Callable[[], bool] | None = None,
) -> AsyncGenerator[str, None]:
    """Yield SSE frames for the unified event stream.

    Subscribes to both GATE_EVENTS_CHANNEL and SYSTEM_EVENTS_CHANNEL and
    yields frames as they arrive, interleaved.
    """
    if snapshot is not None:
        async for frame in snapshot:
            yield _sse_frame(frame)

    if pubsub is None:
        while True:
            if disconnect is not None and disconnect():
                break
            await asyncio.sleep(3)
            yield ": keepalive\n\n"
        return

    try:
        while True:
            if disconnect is not None and disconnect():
                break
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=15
            )
            if message is None:
                yield ": keepalive\n\n"
                continue
            try:
                data = json.loads(str(message.get("data") or "{}"))
            except json.JSONDecodeError:
                continue
            if gate is not None and data.get("gate") not in (None, gate):
                continue
            yield _sse_frame(data)
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe()
            except (redis.exceptions.RedisError, OSError):
                pass
            try:
                # unsubscribe() alone does not return the dedicated pubsub
                # connection to the pool; without aclose() every SSE client
                # permanently consumes one slot until MaxConnectionsError.
                await pubsub.aclose()
            except (redis.exceptions.RedisError, OSError):
                pass


@router.get("/events/stream")
async def unified_events_stream(
    request: Request,
    gate: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events stream: gate cycle + system health combined.

    Query params:
    - ``gate``: filter to a specific gate code (optional).

    On connect the last 20 gate events are replayed, then both Redis
    channels are subscribed and events stream in real time.
    """

    async def _snapshot_rows():
        stmt = select(GateEvent).order_by(GateEvent.ts.desc()).limit(20)
        if gate is not None:
            stmt = stmt.where(GateEvent.gate_code == gate)
        rows = (await db.execute(stmt)).scalars().all()
        for row in reversed(rows):
            yield {
                "type": "snapshot",
                "ts": row.ts.isoformat(),
                "gate": row.gate_code,
                "source": row.source,
                "method": row.method,
                "detail": row.detail,
            }

    snapshot_gen = _snapshot_rows()

    try:
        r = await get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(GATE_EVENTS_CHANNEL, SYSTEM_EVENTS_CHANNEL)
    except (redis.exceptions.RedisError, OSError):
        pubsub = None

    async def _gen():
        async for frame in _unified_events_iter(
            gate=gate,
            snapshot=snapshot_gen,
            pubsub=pubsub,
            disconnect=lambda: request.is_disconnected(),
        ):
            yield frame

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/gate/events")
async def gate_events_history(
    gate: str | None = Query(default=None),
    source: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Paginated gate event history from the database.

    Query params:
    - ``gate``: filter to a specific gate code (optional).
    - ``source``: filter by event source (optional).
    - ``offset``: pagination offset (default 0).
    - ``limit``: page size, max 200 (default 50).
    """
    stmt = select(GateEvent).order_by(GateEvent.ts.desc())
    if gate is not None:
        stmt = stmt.where(GateEvent.gate_code == gate)
    if source is not None:
        stmt = stmt.where(GateEvent.source == source)
    stmt = stmt.offset(offset).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "events": [
            {
                "id": row.id,
                "ts": row.ts.isoformat(),
                "gate": row.gate_code,
                "source": row.source,
                "method": row.method,
                "detail": row.detail,
            }
            for row in rows
        ],
        "offset": offset,
        "limit": limit,
    }
