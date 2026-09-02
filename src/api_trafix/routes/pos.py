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
from uuid import UUID

import redis.exceptions
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.config.database import get_db
from api_trafix.config.redis import get_redis
from api_trafix.core.dependencies import (
    get_active_operator_session,
    get_current_user_query,
)
from api_trafix.crud import gate as gate_crud
from api_trafix.crud import shift as shift_crud
from api_trafix.crud import vehicle_type as vehicle_type_crud
from api_trafix.models import (
    GateEvent,
    OperatorSession,
    ParkingRate,
    RateStatus,
    ShiftStatus,
    User,
    UserRole,
    VehicleStatus,
)
from api_trafix.services import gate_cycle as service
from api_trafix.services.vehicles import vehicle_id_of
from api_trafix.services.events import (
    GATE_EVENTS_CHANNEL,
    TYPE_TRANSACTION_SETTLED,
    TYPE_TRANSACTION_VOIDED,
    publish_gate_event,
)
from api_trafix.schemas.operator_session import OperatorSessionRead

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pos", tags=["POS"])


async def _active_base_price(db: AsyncSession, vehicle_type_id: UUID) -> int | None:
    """The flat ``base_price`` of the active rate for a vehicle class."""
    rate = await db.scalar(
        select(ParkingRate)
        .where(
            ParkingRate.vehicle_type_id == vehicle_type_id,
            ParkingRate.status == RateStatus.ACTIVE,
        )
        .order_by(ParkingRate.created_at.desc())
    )
    return rate.base_price if rate is not None else None


async def _active_rates(db: AsyncSession) -> list[ParkingRate]:
    """Every active tarif parkir, newest first, with its vehicle type loaded."""
    return list(
        (
            await db.execute(
                select(ParkingRate)
                .where(ParkingRate.status == RateStatus.ACTIVE)
                .options(selectinload(ParkingRate.vehicle_type))
                .order_by(ParkingRate.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def _operator_query_user(
    current_user: User = Depends(get_current_user_query),
) -> User:
    """An operator authenticated via ``?token=`` (for EventSource)."""
    if current_user.role != UserRole.OPERATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hak akses tidak mencukupi",
        )
    return current_user


# -- request/response models -------------------------------------------------


class PosSettleRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    transaction_code: str | None = None
    police_number: str | None = None
    lost_ticket: bool = False
    vehicle_id: int | None = None
    # An admin-managed vehicle class (wins over the legacy wire id).
    vehicle_type_id: UUID | None = None
    # The exact admin-managed tarif parkir to price with (wins over the
    # vehicle class lookup, which falls back to the latest active rate).
    parking_rate_id: UUID | None = None
    # Quote-only: price a manual ticket even though no transaction exists yet.
    manual: bool = False
    # Payment method chosen by the cashier (TUNAI / QRIS / E-MONEY).
    payment_method: str | None = None


class PosVoidRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    transaction_code: str
    reason: str = ""


class PosPrintRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    transaction_code: str
    gate: str | None = None


class PosManualRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    police_number: str
    vehicle_id: int | None = None
    # An admin-managed vehicle class (wins over the legacy wire id).
    vehicle_type_id: UUID | None = None
    # The exact admin-managed tarif parkir to price with (wins over the
    # vehicle class lookup).
    parking_rate_id: UUID | None = None
    total: float | None = None
    payment_method: str | None = None


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


@router.get("/refs")
async def operator_references(
    db: AsyncSession = Depends(get_db),
):
    """Reference data the POS screen needs (shifts, gates, vehicle classes).

    Public on purpose: the operator login screen fetches it *before* the
    operator is authenticated, so this endpoint must not require a token.
    """
    shifts, _ = await shift_crud.get_all(
        db, status=ShiftStatus.ACTIVE, page_size=100
    )
    gates, _ = await gate_crud.get_all(db, page_size=100)
    vehicle_types, _ = await vehicle_type_crud.get_all(
        db, status=VehicleStatus.ACTIVE, page_size=100
    )
    rates = await _active_rates(db)
    return {
        "shifts": [
            {
                "id": s.id,
                "name": s.name,
                "start_time": str(s.start_time),
                "finish_time": str(s.finish_time),
                "crosses_midnight": s.crosses_midnight,
                "status": s.status.value,
            }
            for s in shifts
        ],
        "gates": [
            {
                "id": g.id,
                "name": g.name,
                "gate_code": g.gate_code,
                "type": g.type.value,
                "status": g.status.value,
            }
            for g in gates
        ],
        "vehicle_types": [
            {
                "id": vt.id,
                "code": vt.code,
                "name": vt.name,
                # Flat manual-ticket price from the active parking rate (the
                # single source of truth); None when no active rate exists.
                "base_price": await _active_base_price(db, vt.id),
                # The gate-cycle wire id (1-4) the POS hotkeys address, or
                # None for classes outside the wire contract.
                "wire_id": await vehicle_id_of(db, vt.id),
                "status": vt.status.value,
            }
            for vt in vehicle_types
        ],
        # Every active tarif parkir — the operator's "pilih kendaraan" list
        # is built from these, so the price shown is the exact tariff that
        # will be charged (passed back as parking_rate_id).
        "rates": [
            {
                "id": rate.id,
                "name": rate.name,
                "vehicle_type_id": rate.vehicle_type_id,
                "vehicle_type_name": rate.vehicle_type.name
                if rate.vehicle_type is not None
                else None,
                "base_price": rate.base_price,
                "fee_category": rate.fee_category,
                "ticket_charge": rate.ticket_charge,
                "stay_charge": rate.stay_charge,
                "status": rate.status.value,
                "updated_at": rate.updated_at.isoformat() if rate.updated_at else None,
            }
            for rate in rates
        ],
    }


# -- transactions ----------------------------------------------------------


@router.post("/transactions/quote")
async def quote_transaction(
    payload: PosSettleRequest,
    request: Request,
    _: OperatorSession = Depends(get_active_operator_session),
):
    """What would this vehicle pay? Read-only — nothing is written."""
    if payload.manual:
        # A manual ticket has no recorded entry by definition — price it
        # directly instead of looking for a transaction behind the plate.
        result = await request.app.state.gate_cycle.preview_fee(
            kind="manual",
            vehicle_type_id=payload.vehicle_type_id,
            parking_rate_id=payload.parking_rate_id,
            vehicle_id=payload.vehicle_id,
        )
    else:
        result = await request.app.state.gate_cycle.quote(
            code=payload.transaction_code,
            plate=payload.police_number,
            lost=payload.lost_ticket,
            vehicle_id=payload.vehicle_id,
            vehicle_type_id=payload.vehicle_type_id,
            parking_rate_id=payload.parking_rate_id,
        )
        if result.status == service.STATUS_NOT_FOUND and payload.lost_ticket:
            # No open transaction behind this plate — for lost tickets that
            # is expected, so answer with the would-be charge instead.
            result = await request.app.state.gate_cycle.preview_fee(
                kind="lost",
                vehicle_type_id=payload.vehicle_type_id,
                parking_rate_id=payload.parking_rate_id,
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
            vehicle_type_id=payload.vehicle_type_id,
            parking_rate_id=payload.parking_rate_id,
            payment_method=payload.payment_method,
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
            vehicle_type_id=payload.vehicle_type_id,
            parking_rate_id=payload.parking_rate_id,
            payment_method=payload.payment_method,
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


@router.post("/transactions/manual")
async def manual_transaction(
    payload: PosManualRequest,
    request: Request,
    operator_session: OperatorSession = Depends(get_active_operator_session),
):
    """Record a transaction by hand (F9) when the entry ticket never printed.

    The flat rate for the vehicle class is charged and the barrier opens —
    there is nothing left to settle.
    """
    result = await request.app.state.gate_cycle.manual_ticket(
        police_number=payload.police_number,
        vehicle_id=payload.vehicle_id,
        vehicle_type_id=payload.vehicle_type_id,
        parking_rate_id=payload.parking_rate_id,
        total=payload.total,
        payment_method=payload.payment_method,
        gate=operator_session.gate.gate_code,
        exit_operator_id=operator_session.user_id,
        exit_shift_id=operator_session.shift_id,
    )
    if result.status == service.STATUS_NOT_FOUND:
        return {"status": "notfound", "message": result.message}
    await publish_gate_event(
        TYPE_TRANSACTION_SETTLED,
        gate=operator_session.gate.gate_code,
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
            try:
                # unsubscribe() alone does not return the dedicated pubsub
                # connection to the pool; without aclose() every SSE client
                # permanently consumes one slot until MaxConnectionsError.
                await pubsub.aclose()
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
