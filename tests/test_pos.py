"""Tests for the operator POS router (``/api/pos/*``) and session start.

Covers the P0/P1 gaps from PRD_GAP_ANALYSIS_OPERATOR_APP.md (payment method
excluded): active-session enforcement, settle with session context, void
(parked + paid/refund), reprint, exit receipt, and the SSE event stream.
Login is username/password only; operator sessions open via
``POST /operator-sessions/start``.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from api_trafix.config.database import get_db
from api_trafix.config.redis import close_redis
from api_trafix.config.settings import get_settings
from api_trafix.core.security import create_access_token, hash_password
from api_trafix.models import (
    Gate,
    GateStatus,
    GateType,
    OperatorSession,
    OperatorShiftAssignment,
    OperatorShiftAssignmentStatus,
    ParkingStatus,
    ParkTransaction,
    Payment,
    PaymentStatus,
    Shift,
    ShiftStatus,
    User,
    UserRole,
    UserStatus,
    VehicleStatus,
    VehicleType,
)
from api_trafix.routes import auth as auth_routes
from api_trafix.routes import gate_cycle as gate_routes
from api_trafix.routes import operator_session as operator_session_routes
from api_trafix.routes import pos as pos_routes
from api_trafix.services.gate_cycle import WIB, GateCycleConfig, GateCycleService, NullPublisher
from api_trafix.services.seed import seed_reference_data
from api_trafix.services.snapshots import SnapshotStore


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _plate() -> str:
    return f"H{uuid.uuid4().hex[:6].upper()}"


@pytest_asyncio.fixture
async def pos(db_sessionmaker, tmp_path):
    # This file logs in far more than 20x/minute from one client IP; without
    # raising the per-IP limit the login throttle trips mid-run. The settings
    # singleton is built on first use (long before this module imports), so
    # the cache must be dropped after touching the env.
    os.environ.setdefault("LOGIN_IP_RATE_LIMIT", "1000")
    get_settings.cache_clear()

    async with db_sessionmaker() as db:
        await seed_reference_data(db)

    publisher = NullPublisher()
    svc = GateCycleService(
        db_sessionmaker,
        publisher=publisher,
        storage=SnapshotStore(Path(tmp_path)),
        config=GateCycleConfig(
            site_name="POS Test",
            site_address="Jl. Test 1",
            storage_dir=Path(tmp_path),
        ),
        print_gap_seconds=0,
    )
    app = FastAPI()
    app.include_router(auth_routes.router)
    app.include_router(gate_routes.router)
    app.include_router(operator_session_routes.router)
    app.include_router(pos_routes.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.state.gate_cycle = svc

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            svc=svc,
            publisher=publisher,
            db=db_sessionmaker,
        )
    # The module-level Redis client is bound to this test's event loop.
    await close_redis()


async def _create_operator(db, *, role=UserRole.OPERATOR, suffix=None):
    suffix = suffix or _suffix()
    user = User(
        name=f"POS {role.value} {suffix}",
        username=f"pos-{role.value}-{suffix}",
        password=hash_password("secret123"),
        role=role,
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_shift(db, name=None, *, status=ShiftStatus.ACTIVE):
    """A shift whose window always contains the current WIB time."""
    now = datetime.now(WIB)
    start = (now - timedelta(hours=1)).time()
    finish = (now + timedelta(hours=1)).time()
    shift = Shift(
        name=name or f"shift-{_suffix()}",
        start_time=start,
        finish_time=finish,
        crosses_midnight=start >= finish,
        status=status,
    )
    db.add(shift)
    await db.commit()
    await db.refresh(shift)
    return shift


async def _assign(db, operator, shift):
    db.add(
        OperatorShiftAssignment(
            operator_id=operator.id,
            shift_id=shift.id,
            status=OperatorShiftAssignmentStatus.ACTIVE,
        )
    )
    await db.commit()


async def _gate(db, code="1") -> Gate:
    gate = await db.scalar(select(Gate).where(Gate.gate_code == code))
    assert gate is not None, f"gate {code} not seeded"
    return gate


async def _login(pos, operator):
    return await pos.client.post(
        "/auth/login",
        json={"username": operator.username, "password": "secret123"},
    )


async def _start_session(pos, token, shift_id, gate_id=None):
    payload = {"shift_id": str(shift_id)}
    if gate_id is not None:
        payload["gate_id"] = str(gate_id)
    return await pos.client.post(
        "/operator-sessions/start",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )


async def _open_session(pos, *, gate_code="2", operator=None):
    """Login an operator and start a session, returning (token, session, operator)."""
    async with pos.db() as db:
        operator = operator or await _create_operator(db)
        shift = await _create_shift(db)
        await _assign(db, operator, shift)
        gate = await _gate(db, gate_code)
        gate_id, shift_id = gate.id, shift.id
    login_resp = await _login(pos, operator)
    assert login_resp.status_code == 200, login_resp.text
    token = login_resp.json()["access_token"]
    resp = await _start_session(pos, token, shift_id, gate_id)
    assert resp.status_code == 201, resp.text
    return token, resp.json(), operator


async def _enter(pos, *, gate="1", plate=None):
    resp = await pos.client.post(
        "/api/gatein",
        json={
            "gate": gate,
            "vehicle_id": 1,
            "plate_num": plate or _plate(),
            "url_gambar": "",
            "serialNo": "441D6491AF17",
        },
    )
    assert resp.status_code == 200
    return resp.json()["kode_tiket"]


async def _backdate(db, code, hours=2):
    """Push a transaction's entry time back so the flat fee kicks in."""
    tx = await db.scalar(
        select(ParkTransaction).where(ParkTransaction.ticket_number == code)
    )
    assert tx is not None
    tx.entry_time = datetime.now(WIB) - timedelta(hours=hours)
    await db.commit()


# -- session enforcement ------------------------------------------------------


async def test_settle_requires_an_active_session(pos):
    async with pos.db() as db:
        operator = await _create_operator(db)
    token, _ = create_access_token(str(operator.id), "operator")

    resp = await pos.client.post(
        "/api/pos/transactions/settle",
        json={"transaction_code": "0000000001"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "session" in resp.json()["detail"].lower()


async def test_current_session_endpoint(pos):
    token, session, _ = await _open_session(pos)
    resp = await pos.client.get(
        "/api/pos/session", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == session["id"]
    assert body["status"] == "active"


# -- session start (POST /operator-sessions/start) -----------------------------


async def test_login_returns_no_session(pos):
    async with pos.db() as db:
        operator = await _create_operator(db)
    resp = await pos.client.post(
        "/auth/login",
        json={"username": operator.username, "password": "secret123"},
    )
    assert resp.status_code == 200
    assert "session" not in resp.json()


async def test_session_start_requires_shift_and_gate(pos):
    async with pos.db() as db:
        operator = await _create_operator(db)
    login_resp = await _login(pos, operator)
    token = login_resp.json()["access_token"]
    resp = await pos.client.post(
        "/operator-sessions/start",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


async def test_session_start_rejects_non_operator(pos):
    async with pos.db() as db:
        admin = await _create_operator(db, role=UserRole.ADMIN)
        shift = await _create_shift(db)
        shift_id = shift.id
    login_resp = await _login(pos, admin)
    token = login_resp.json()["access_token"]
    resp = await _start_session(pos, token, shift_id)
    assert resp.status_code == 403


async def test_session_start_rejects_unknown_shift(pos):
    async with pos.db() as db:
        operator = await _create_operator(db)
        gate = await _gate(db)
    login_resp = await _login(pos, operator)
    token = login_resp.json()["access_token"]
    resp = await _start_session(pos, token, uuid.uuid4(), gate.id)
    assert resp.status_code == 404


async def test_session_start_opens_session_for_operator(pos):
    async with pos.db() as db:
        operator = await _create_operator(db)
        shift = await _create_shift(db)
        exit_gate = await _gate(db, "2")
        shift_id = shift.id
    login_resp = await _login(pos, operator)
    token = login_resp.json()["access_token"]
    # No gate_id: the backend must resolve the single exit gate itself.
    resp = await _start_session(pos, token, shift_id)
    assert resp.status_code == 201
    session = resp.json()
    assert session["status"] == "active"
    assert session["shift_id"] == str(shift_id)
    assert session["gate_id"] == str(exit_gate.id)

    async with pos.db() as db:
        active = await db.scalar(
            select(OperatorSession).where(OperatorSession.user_id == operator.id)
        )
        assert active is not None and active.status.value == "active"


async def test_session_start_rejects_entry_gate(pos):
    async with pos.db() as db:
        operator = await _create_operator(db)
        shift = await _create_shift(db)
        entry_gate = await _gate(db, "1")
        shift_id, entry_id = shift.id, entry_gate.id
    login_resp = await _login(pos, operator)
    token = login_resp.json()["access_token"]
    resp = await _start_session(pos, token, shift_id, entry_id)
    assert resp.status_code == 400


async def test_session_start_requires_exactly_one_exit_gate(pos):
    extra_exit_id = None
    try:
        async with pos.db() as db:
            operator = await _create_operator(db)
            shift = await _create_shift(db)
            suffix = _suffix()
            extra = Gate(
                name=f"Extra Exit {suffix}",
                gate_code=f"{suffix[:4]}X",
                type=GateType.GATE_OUT,
                status=GateStatus.ONLINE,
            )
            db.add(extra)
            await db.commit()
            await db.refresh(extra)
            extra_exit_id = extra.id
            shift_id = shift.id
        login_resp = await _login(pos, operator)
        token = login_resp.json()["access_token"]
        resp = await _start_session(pos, token, shift_id)
        assert resp.status_code == 422
    finally:
        if extra_exit_id is not None:
            async with pos.db() as db:
                extra = await db.get(Gate, extra_exit_id)
                if extra is not None:
                    await db.delete(extra)
                    await db.commit()


async def test_second_session_start_conflicts(pos):
    token, _, operator = await _open_session(pos)
    async with pos.db() as db:
        shift = await _create_shift(db)
        await _assign(db, operator, shift)
        shift_id = shift.id
    resp = await _start_session(pos, token, shift_id)
    assert resp.status_code == 409
    assert token


# -- settle with session context ----------------------------------------------


async def test_quote_reads_an_open_session(pos):
    token, _, _ = await _open_session(pos)
    code = await _enter(pos)
    resp = await pos.client.post(
        "/api/pos/transactions/quote",
        json={"transaction_code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["transaction_code"] == code


async def test_settle_uses_session_context(pos):
    token, session, operator = await _open_session(pos)
    code = await _enter(pos)
    async with pos.db() as db:
        await _backdate(db, code)

    resp = await pos.client.post(
        "/api/pos/transactions/settle",
        json={"transaction_code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["transaction_code"] == code
    assert body["data"]["total"] == 2000

    async with pos.db() as db:
        tx = await db.scalar(
            select(ParkTransaction).where(ParkTransaction.ticket_number == code)
        )
        assert tx is not None
        assert tx.status_parking == ParkingStatus.COMPLETED
        assert str(tx.exit_operator_id) == str(operator.id)
        assert str(tx.exit_shift_id) == session["shift_id"]


async def test_settle_lost_ticket_with_session_context(pos):
    token, session, operator = await _open_session(pos)
    plate = _plate()
    resp = await pos.client.post(
        "/api/pos/transactions/settle",
        json={"lost_ticket": True, "police_number": plate, "vehicle_id": 1},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    code = body["data"]["transaction_code"]

    async with pos.db() as db:
        tx = await db.scalar(
            select(ParkTransaction).where(ParkTransaction.ticket_number == code)
        )
        assert tx is not None
        assert tx.status_parking == ParkingStatus.COMPLETED
        assert str(tx.exit_operator_id) == str(operator.id)
        assert str(tx.exit_shift_id) == session["shift_id"]


# -- void ---------------------------------------------------------------------


async def test_void_a_parked_transaction(pos):
    token, _, _ = await _open_session(pos)
    code = await _enter(pos)

    resp = await pos.client.post(
        "/api/pos/transactions/void",
        json={"transaction_code": code, "reason": "wrong plate"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["refunded"] == 0

    async with pos.db() as db:
        tx = await db.scalar(
            select(ParkTransaction).where(ParkTransaction.ticket_number == code)
        )
        assert tx.status_parking == ParkingStatus.VOID
        assert "wrong plate" in (tx.keterangan or "")


async def test_void_a_paid_transaction_refunds_and_is_idempotent(pos):
    token, _, _ = await _open_session(pos)
    code = await _enter(pos)
    async with pos.db() as db:
        await _backdate(db, code)
    await pos.client.post(
        "/api/pos/transactions/settle",
        json={"transaction_code": code},
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = await pos.client.post(
        "/api/pos/transactions/void",
        json={"transaction_code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["refunded"] == 1

    async with pos.db() as db:
        tx = await db.scalar(
            select(ParkTransaction).where(ParkTransaction.ticket_number == code)
        )
        assert tx.status_parking == ParkingStatus.VOID
        payment = await db.scalar(
            select(Payment).where(Payment.park_transaction_id == tx.id)
        )
        assert payment is not None
        assert payment.status == PaymentStatus.REFUNDED
        assert payment.amount == 2000

    second = await pos.client.post(
        "/api/pos/transactions/void",
        json={"transaction_code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 409


async def test_void_unknown_transaction_404s(pos):
    token, _, _ = await _open_session(pos)
    resp = await pos.client.post(
        "/api/pos/transactions/void",
        json={"transaction_code": "0000000000"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# -- reprint / receipt --------------------------------------------------------


async def test_reprint_publishes_four_blocks(pos):
    token, _, _ = await _open_session(pos)
    code = await _enter(pos)
    before = len(pos.publisher.printed)

    resp = await pos.client.post(
        "/api/pos/transactions/reprint",
        json={"transaction_code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["blocks_printed"] == 4
    assert len(pos.publisher.printed) == before + 2


async def test_exit_receipt_publishes_one_block(pos):
    token, _, _ = await _open_session(pos)
    code = await _enter(pos)
    await pos.client.post(
        "/api/pos/transactions/settle",
        json={"transaction_code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    before = len(pos.publisher.printed)

    resp = await pos.client.post(
        "/api/pos/transactions/receipt",
        json={"transaction_code": code},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["blocks_printed"] == 1
    assert len(pos.publisher.printed) == before + 1


# -- SSE event stream ---------------------------------------------------------


class FakePubSub:
    """A stand-in for ``redis.asyncio.Redis.pubsub()``.

    ``get_message`` returns one event, then blocks forever — exactly how the
    real pubsub behaves between messages.
    """

    def __init__(self, messages: list[dict]):
        self._queue = list(messages)
        self.unsubscribed = False
        self.closed = False

    async def get_message(self, ignore_subscribe_messages=False, timeout=0.0):
        if self._queue:
            return {"data": json.dumps(self._queue.pop(0))}
        await asyncio.Event().wait()

    async def unsubscribe(self, *channels):
        self.unsubscribed = True

    async def aclose(self):
        self.closed = True


async def test_gate_events_iter_replays_snapshot_and_forwards(pos, monkeypatch):
    from api_trafix.routes.pos import gate_events_iter

    snapshot = [
        {"type": "snapshot", "ts": "2026-08-14T00:00:00+00:00", "gate": "1"},
    ]
    pubsub = FakePubSub(
        [
            {"type": "barrier_opened", "gate": "1", "ts": "2026-08-14T00:00:01+00:00"},
            {"type": "barrier_opened", "gate": "2", "ts": "2026-08-14T00:00:02+00:00"},
        ]
    )

    async def _snapshot():
        return snapshot

    stream = gate_events_iter(
        gate="1", snapshot=_snapshot, pubsub=pubsub, disconnect=lambda: False
    )
    snapshot_frame = await anext(stream)
    event_frame = await anext(stream)
    await stream.aclose()

    assert "event: snapshot" in snapshot_frame
    assert "event: barrier_opened" in event_frame
    assert '"gate": "1"' in event_frame
    # The gate-2 event would have been filtered out by the gate=1 filter.
    assert pubsub.unsubscribed


async def test_gate_events_iter_keepalive_when_redis_down(pos, monkeypatch):
    from api_trafix.routes.pos import gate_events_iter

    async def _empty_snapshot():
        return []

    stream = gate_events_iter(
        gate=None, snapshot=_empty_snapshot, pubsub=None, disconnect=lambda: False
    )
    frame = await anext(stream)
    await stream.aclose()

    assert frame == ": keepalive\n\n"


async def test_gate_events_iter_unsubscribes_on_exit(pos, monkeypatch):
    from api_trafix.routes.pos import gate_events_iter

    pubsub = FakePubSub([{"type": "barrier_opened", "gate": "1"}])

    async def _snapshot():
        return [{"type": "snapshot", "gate": "1"}]

    def _stop():
        return True  # disconnect on first check

    frames = [
        frame
        async for frame in gate_events_iter(
            gate=None, snapshot=_snapshot, pubsub=pubsub, disconnect=_stop
        )
    ]
    assert any(f.startswith("event: snapshot") for f in frames)
    assert pubsub.unsubscribed
    assert pubsub.closed


async def test_sse_stream_rejects_bad_token(pos):
    async with pos.client.stream(
        "GET", "/api/pos/events/stream?token=not-a-token"
    ) as resp:
        assert resp.status_code == 401


async def test_pos_refs_expose_price_and_wire_id(pos):
    """The operator app joins hotkeys to prices via wire_id."""
    resp = await pos.client.get("/api/pos/refs")
    assert resp.status_code == 200

    types = {vt["code"]: vt for vt in resp.json()["vehicle_types"]}
    assert set(types) >= {"MOTOR", "MOBIL", "OJOL", "BUS"}
    assert types["MOTOR"]["wire_id"] == 1
    assert types["MOBIL"]["wire_id"] == 2
    assert types["OJOL"]["wire_id"] == 3
    assert types["BUS"]["wire_id"] == 4
    assert types["MOTOR"]["price"] == 2000
    assert types["MOBIL"]["price"] == 4000
    assert types["OJOL"]["price"] == 0
    assert types["BUS"]["price"] == 6000


async def test_manual_ticket_charges_the_configured_vehicle_price(pos):
    token, _session, _operator = await _open_session(pos)
    headers = {"Authorization": f"Bearer {token}"}

    # The admin edits the Mobil price; the manual ticket must follow it.
    async with pos.db() as db:
        mobil = await db.scalar(select(VehicleType).where(VehicleType.code == "MOBIL"))
        assert mobil is not None
        mobil.price = 7777
        await db.commit()

    try:
        resp = await pos.client.post(
            "/api/pos/transactions/manual",
            json={"police_number": _plate(), "vehicle_id": 2},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["total"] == 7777
        assert data["payment_status"] == "lunas"
    finally:
        # Restore the seed price — the test DB is shared across the suite.
        async with pos.db() as db:
            mobil = await db.scalar(select(VehicleType).where(VehicleType.code == "MOBIL"))
            assert mobil is not None
            mobil.price = 4000
            await db.commit()

    # A class with no configured price falls back to the legacy flat rate.
    async with pos.db() as db:
        motor = await db.scalar(select(VehicleType).where(VehicleType.code == "MOTOR"))
        assert motor is not None
        motor.price = None
        await db.commit()

    try:
        resp = await pos.client.post(
            "/api/pos/transactions/manual",
            json={"police_number": _plate(), "vehicle_id": 1},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["total"] == 2000
    finally:
        async with pos.db() as db:
            motor = await db.scalar(select(VehicleType).where(VehicleType.code == "MOTOR"))
            assert motor is not None
            motor.price = 2000
            await db.commit()


# -- admin-defined vehicle classes (vehicle_type_id) ---------------------------


async def _custom_vehicle_type(db, *, price=5000, status=VehicleStatus.ACTIVE):
    """A vehicle class the admin invented — outside the 4-class wire contract."""
    vt = VehicleType(
        code=f"GEN{_suffix()[:6].upper()}",
        name="Kendaraan Khusus",
        price=price,
        status=status,
    )
    db.add(vt)
    await db.commit()
    await db.refresh(vt)
    return vt


async def _cleanup_custom_type(db, type_id, ticket_codes):
    """Remove rows created by a custom-type test (FK order matters)."""
    for code in ticket_codes:
        tx = await db.scalar(
            select(ParkTransaction).where(ParkTransaction.ticket_number == code)
        )
        if tx is not None:
            await db.delete(tx)
    vt = await db.get(VehicleType, type_id)
    if vt is not None:
        await db.delete(vt)
    await db.commit()


async def test_manual_ticket_accepts_admin_defined_vehicle_type(pos):
    token, _session, _operator = await _open_session(pos)
    headers = {"Authorization": f"Bearer {token}"}
    async with pos.db() as db:
        vt = await _custom_vehicle_type(db, price=9999)
        vt_id = vt.id

    codes: list[str] = []
    try:
        resp = await pos.client.post(
            "/api/pos/transactions/manual",
            json={"police_number": _plate(), "vehicle_type_id": str(vt_id)},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["total"] == 9999
        assert data["payment_status"] == "lunas"
        codes.append(data["transaction_code"])

        async with pos.db() as db:
            tx = await db.scalar(
                select(ParkTransaction).where(
                    ParkTransaction.ticket_number == data["transaction_code"]
                )
            )
            assert tx is not None
            assert str(tx.vehicle_type_id) == str(vt_id)
    finally:
        async with pos.db() as db:
            await _cleanup_custom_type(db, vt_id, codes)


async def test_manual_ticket_rejects_unknown_vehicle_type(pos):
    token, _session, _operator = await _open_session(pos)
    resp = await pos.client.post(
        "/api/pos/transactions/manual",
        json={"police_number": _plate(), "vehicle_type_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "notfound"


async def test_lost_ticket_prices_an_admin_defined_vehicle_type(pos):
    token, _session, _operator = await _open_session(pos)
    async with pos.db() as db:
        vt = await _custom_vehicle_type(db, price=5000)
        vt_id = vt.id

    codes: list[str] = []
    try:
        resp = await pos.client.post(
            "/api/pos/transactions/settle",
            json={
                "lost_ticket": True,
                "police_number": _plate(),
                "vehicle_type_id": str(vt_id),
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "success"
        assert body["data"]["total"] == 5000
        codes.append(body["data"]["transaction_code"])
    finally:
        async with pos.db() as db:
            await _cleanup_custom_type(db, vt_id, codes)


async def test_quote_honors_a_vehicle_type_override(pos):
    token, _, _ = await _open_session(pos)
    code = await _enter(pos)
    async with pos.db() as db:
        await _backdate(db, code)
        mobil = await db.scalar(select(VehicleType).where(VehicleType.code == "MOBIL"))
        mobil_id = mobil.id

    resp = await pos.client.post(
        "/api/pos/transactions/quote",
        json={"transaction_code": code, "vehicle_type_id": str(mobil_id)},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    # The motor transaction is repriced at the Mobil flat rate.
    assert body["data"]["total"] == 4000
