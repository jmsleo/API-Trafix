"""Authenticated operator POS endpoints (``/api/pos/*``).

The legacy wire routes (``/api/gateout/gateoutKasir`` etc.) stay as they are
for the loopback / Tauri contract. This router is the Operator App layer: every
request is an authenticated operator with an **active operator session**, and
all transaction context (gate, operator, shift) is taken from that session
rather than trusted from the request body.

It also serves the real-time gate-event stream (Server-Sent Events) so the POS
screen can show the barrier opening and transactions settling without polling.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import redis.exceptions
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.config.redis import get_redis
from api_trafix.core.dependencies import (
    get_active_operator_session,
    get_current_user_query,
)
from api_trafix.models import GateEvent, OperatorSession, User, UserRole
from api_trafix.services import gate_cycle as service
from api_trafix.services.events import (
    GATE_EVENTS_CHANNEL,
    TYPE_TRANSACTION_SETTLED,
    TYPE_TRANSACTION_VOIDED,
    publish_gate_event,
)
from api_trafix.schemas.operator_session import OperatorSessionRead

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pos", tags=["POS"])


async def _operator_query_user(
    current_user: User = Depends(get_current_user_query),
) -> User:
    """An operator authenticated via ``?token=`` (for EventSource)."""
    if current_user.role != UserRole.OPERATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    return current_user


# -- request/response models -------------------------------------------------


class PosSettleRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    transaction_code: str | None = None
    police_number: str | None = None
    lost_ticket: bool = False
    vehicle_id: int | None = None


class PosVoidRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    transaction_code: str
    reason: str = ""


class PosPrintRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    transaction_code: str
    gate: str | None = None


# -- payload helpers (mirror the wire response shapes) ------------------------


def _settle_payload(result: service.GateOutResult) -> dict[str, Any]:
    """``responData()`` — the body ``gateoutKasir`` returns on success."""
    return {
        "transaction_code": result.transaction_code,
        "vehicle_id": result.vehicle_id,
        "time_checkin": result.time_checkin,
        "time_checkout": result.time_checkout,
        "duration": result.duration,
        "total": result.total,
        "cam_in": result.cam_in,
        "cam_out": result.cam_out,
        "payment_status": result.payment_status,
        "police_number": result.plate_in,
        "admin_id": result.admin_id,
        "shift_id": result.shift_id,
        "created_at": result.created_at,
        "updated_at": result.updated_at,
        "discount": "false",
    }


def _quote_payload(result: service.GateOutResult) -> dict[str, Any]:
    """The facts ``detailtransaction`` shows before the money is taken."""
    return {
        "status": result.status,
        "transaction_code": result.transaction_code,
        "total": result.total,
        "duration": result.duration,
        "police_number": result.plate_in,
        "plate_out": result.plate_out,
        "plate_match": result.plate_match,
        "time_checkin": result.time_checkin,
        "time_checkout": result.time_checkout,
        "member": result.is_member,
        "name": result.member_name,
        "breakdown": result.breakdown,
        "vehicle_id": result.vehicle_id,
        "message": result.message,
    }


def _action_payload(result: service.PosActionResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "transaction_code": result.transaction_code,
        "message": result.message,
        "blocks_printed": result.blocks_printed,
        "refunded": result.refunded,
        "total": result.total,
    }


# -- session ---------------------------------------------------------------


@router.get("/session", response_model=OperatorSessionRead)
async def current_session(
    operator_session: OperatorSession = Depends(get_active_operator_session),
):
    """The operator's active session — the gate and shift context in use."""
    return operator_session


# -- transactions ----------------------------------------------------------


@router.post("/transactions/quote")
async def quote_transaction(
    payload: PosSettleRequest,
    request: Request,
    _: OperatorSession = Depends(get_active_operator_session),
):
    """What would this vehicle pay? Read-only — nothing is written."""
    result = await request.app.state.gate_cycle.quote(
        code=payload.transaction_code,
        plate=payload.police_number,
        lost=payload.lost_ticket,
        vehicle_id=payload.vehicle_id,
    )
    if result.status == service.STATUS_NOT_FOUND:
        return {
            "status": "notfound",
            "message": result.message,
        }
    return {"status": "success", "data": _quote_payload(result)}


@router.post("/transactions/settle")
async def settle_transaction(
    payload: PosSettleRequest,
    request: Request,
    operator_session: OperatorSession = Depends(get_active_operator_session),
):
    """Settle and release — context comes from the active session."""
    srv = request.app.state.gate_cycle
    gate = operator_session.gate.gate_code

    if payload.lost_ticket and not payload.transaction_code:
        result = await srv.lost_ticket(
            gate=gate,
            plate=payload.police_number,
            vehicle_id=payload.vehicle_id,
            exit_operator_id=operator_session.user_id,
            exit_shift_id=operator_session.shift_id,
        )
    else:
        result = await srv.gate_out(
            gate=gate,
            code=payload.transaction_code,
            plate_num=payload.police_number,
            lost=payload.lost_ticket,
            vehicle_id=payload.vehicle_id,
            exit_operator_id=operator_session.user_id,
            exit_shift_id=operator_session.shift_id,
        )

    if result.status == service.STATUS_NOT_FOUND:
        return {"status": "notfound", "message": result.message}
    if result.status == service.STATUS_TICKET_USED:
        return {"status": "already_paid", "message": result.message}

    await publish_gate_event(
        TYPE_TRANSACTION_SETTLED,
        gate=gate,
        transaction_code=result.transaction_code,
        total=result.total,
        operator=operator_session.user_id,
    )
    return {"status": "success", "data": _settle_payload(result)}


@router.post("/transactions/void")
async def void_transaction(
    payload: PosVoidRequest,
    request: Request,
    operator_session: OperatorSession = Depends(get_active_operator_session),
):
    """Void a parked or paid transaction (refunding any payment rows)."""
    result = await request.app.state.gate_cycle.void_transaction(
        code=payload.transaction_code,
        operator_id=operator_session.user_id,
        shift_id=operator_session.shift_id,
        reason=payload.reason,
    )
    if result.status == service.STATUS_NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.message)
    if result.status == "already_void":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.message)

    await publish_gate_event(
        TYPE_TRANSACTION_VOIDED,
        gate=operator_session.gate.gate_code,
        transaction_code=result.transaction_code,
        operator=operator_session.user_id,
    )
    return {"status": "success", "data": _action_payload(result)}


@router.post("/transactions/reprint")
async def reprint_ticket(
    payload: PosPrintRequest,
    request: Request,
    _: OperatorSession = Depends(get_active_operator_session),
):
    """Reprint the entry ticket the driver lost / the printer failed to emit."""
    result = await request.app.state.gate_cycle.reprint_ticket(
        code=payload.transaction_code, gate=payload.gate
    )
    if result.status == service.STATUS_NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.message)
    if result.status == "already_void":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.message)
    return {"status": "success", "data": _action_payload(result)}


@router.post("/transactions/receipt")
async def print_exit_receipt(
    payload: PosPrintRequest,
    request: Request,
    _: OperatorSession = Depends(get_active_operator_session),
):
    """Print the exit (payment) receipt after a cash settlement."""
    result = await request.app.state.gate_cycle.print_exit_receipt(
        code=payload.transaction_code, gate=payload.gate
    )
    if result.status == service.STATUS_NOT_FOUND:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.message)
    if result.status == "already_void":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.message)
    return {"status": "success", "data": _action_payload(result)}


# -- real-time events --------------------------------------------------------


def _sse_frame(data: dict[str, Any]) -> str:
    return f"event: {data.get('type', 'message')}\ndata: {json.dumps(data)}\n\n"


async def gate_events_iter(
    *,
    gate: str | None,
    snapshot: Callable[[], Awaitable[list[dict[str, Any]]]],
    pubsub: Any | None,
    disconnect: Callable[[], bool] | None = None,
):
    """Yield SSE frames for the POS event stream.

    Split out of the HTTP endpoint so the stream semantics (snapshot replay,
    gate filtering, keepalive, unsubscribe) can be tested without an endless
    HTTP connection.
    """
    for frame in await snapshot():
        yield _sse_frame(frame)

    try:
        while True:
            if disconnect is not None and disconnect():
                break
            if pubsub is None:
                await asyncio.sleep(3)
                yield ": keepalive\n\n"
                continue
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
                await pubsub.unsubscribe(GATE_EVENTS_CHANNEL)
            except (redis.exceptions.RedisError, OSError):
                pass


@router.get("/events/stream")
async def gate_events_stream(
    request: Request,
    gate: str | None = Query(default=None),
    _: User = Depends(_operator_query_user),
    db: AsyncSession = Depends(get_db),
):
    """Server-Sent Events for the POS screen.

    Streams ``barrier_command`` / ``barrier_opened`` / ``transaction_settled`` /
    ``transaction_voided`` events. Authenticate with ``?token=<access_token>``
    because EventSource cannot set an Authorization header. On connect the last
    ``gate_events`` rows are replayed, and Redis outages fall back to keepalive
    frames so the stream never dies.
    """

    async def _snapshot() -> list[dict[str, Any]]:
        stmt = select(GateEvent).order_by(GateEvent.ts.desc()).limit(20)
        if gate is not None:
            stmt = stmt.where(GateEvent.gate_code == gate)
        rows = (await db.execute(stmt)).scalars().all()
        return [
            {
                "type": "snapshot",
                "ts": row.ts.isoformat(),
                "gate": row.gate_code,
                "method": row.method,
                "transaction_code": row.ticket_number,
                "detail": row.detail,
            }
            for row in reversed(rows)
        ]

    try:
        r = await get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(GATE_EVENTS_CHANNEL)
    except (redis.exceptions.RedisError, OSError) as exc:
        log.warning("gate events stream without Redis: %s", exc)
        pubsub = None

    async def event_iter():
        async for frame in gate_events_iter(
            gate=gate,
            snapshot=_snapshot,
            pubsub=pubsub,
            disconnect=request.is_disconnected,
        ):
            yield frame

    return StreamingResponse(
        event_iter(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
