"""Admin can edit an operator shift assignment (operator, shift, status)."""

import uuid
from datetime import time
from types import SimpleNamespace

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import delete as sa_delete

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.models import Shift, ShiftStatus, User, UserRole, UserStatus
from api_trafix.models.operator_shift_assignments import (
    OperatorShiftAssignment,
    OperatorShiftAssignmentStatus,
)
from api_trafix.routes import operator_shift_assignment as assignment_routes
from api_trafix.core.security import hash_password


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture
async def client(db_sessionmaker):
    app = FastAPI()
    app.include_router(assignment_routes.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    admin = User(
        name="Assignment Admin",
        username=f"asg-admin-{_suffix()}",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = lambda: admin

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield SimpleNamespace(client=c)
    from api_trafix.config.redis import close_redis

    await close_redis()


async def _create_operator(db_sessionmaker, *, suffix=None):
    suffix = suffix or _suffix()
    async with db_sessionmaker() as db:
        user = User(
            name=f"Op {suffix}",
            username=f"op-{suffix}",
            password=hash_password("secret123"),
            role=UserRole.OPERATOR,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _create_inactive_operator(db_sessionmaker, *, suffix=None):
    suffix = suffix or _suffix()
    async with db_sessionmaker() as db:
        user = User(
            name=f"Op Inactive {suffix}",
            username=f"op-inactive-{suffix}",
            password=hash_password("secret123"),
            role=UserRole.OPERATOR,
            status=UserStatus.INACTIVE,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _create_shift(db_sessionmaker, *, suffix=None):
    suffix = suffix or _suffix()
    async with db_sessionmaker() as db:
        shift = Shift(
            name=f"shift-{suffix}",
            start_time=time(8, 0),
            finish_time=time(12, 0),
            crosses_midnight=False,
            status=ShiftStatus.ACTIVE,
        )
        db.add(shift)
        await db.commit()
        await db.refresh(shift)
        return shift


async def _create_shift_time(db_sessionmaker, name, start, finish):
    async with db_sessionmaker() as db:
        shift = Shift(
            name=name,
            start_time=time(*start),
            finish_time=time(*finish),
            crosses_midnight=False,
            status=ShiftStatus.ACTIVE,
        )
        db.add(shift)
        await db.commit()
        await db.refresh(shift)
        return shift


async def _create_assignment(db_sessionmaker, operator, shift, *, status=OperatorShiftAssignmentStatus.ACTIVE):
    async with db_sessionmaker() as db:
        obj = OperatorShiftAssignment(
            operator_id=operator.id,
            shift_id=shift.id,
            status=status,
        )
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj


async def _clear(db_sessionmaker, assignment_ids=(), operator_ids=(), shift_ids=()):
    async with db_sessionmaker() as db:
        if assignment_ids:
            await db.execute(
                sa_delete(OperatorShiftAssignment).where(
                    OperatorShiftAssignment.id.in_(assignment_ids)
                )
            )
        if operator_ids:
            await db.execute(sa_delete(User).where(User.id.in_(operator_ids)))
        if shift_ids:
            await db.execute(sa_delete(Shift).where(Shift.id.in_(shift_ids)))
        await db.commit()


async def test_update_operator_shift_and_status(client, db_sessionmaker):
    op1 = await _create_operator(db_sessionmaker)
    op2 = await _create_operator(db_sessionmaker)
    shift1 = await _create_shift_time(db_sessionmaker, f"asg-shift-{_suffix()}", (8, 0), (12, 0))
    shift2 = await _create_shift_time(db_sessionmaker, f"asg-shift-{_suffix()}", (13, 0), (17, 0))

    asg = await _create_assignment(db_sessionmaker, op1, shift1)

    before = await client.client.get(f"/operator-shifts/{asg.id}")
    assert before.status_code == 200, before.text

    resp = await client.client.put(
        f"/operator-shifts/{asg.id}",
        json={
            "operator_id": str(op2.id),
            "shift_id": str(shift2.id),
            "status": "inactive",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(asg.id)
    assert body["operator_id"] == str(op2.id)
    assert body["shift_id"] == str(shift2.id)
    assert body["status"] == "inactive"
    assert body["operator"]["id"] == str(op2.id)
    assert body["shift"]["id"] == str(shift2.id)

    await _clear(db_sessionmaker, [asg.id], [op1.id, op2.id], [shift1.id, shift2.id])


async def test_update_preserves_updated_at(client, db_sessionmaker):
    op1 = await _create_operator(db_sessionmaker)
    shift1 = await _create_shift_time(db_sessionmaker, f"asg-shift-{_suffix()}", (8, 0), (12, 0))

    asg = await _create_assignment(db_sessionmaker, op1, shift1)

    before = await client.client.get(f"/operator-shifts/{asg.id}")
    assert before.status_code == 200, before.text

    resp = await client.client.put(
        f"/operator-shifts/{asg.id}",
        json={
            "operator_id": str(op1.id),
            "shift_id": str(shift1.id),
            "status": "inactive",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "inactive"

    await _clear(db_sessionmaker, [asg.id], [op1.id], [shift1.id])


async def test_update_not_found(client):
    resp = await client.client.put(
        f"/operator-shifts/{uuid.uuid4()}",
        json={"operator_id": str(uuid.uuid4()), "shift_id": str(uuid.uuid4()), "status": "active"},
    )
    assert resp.status_code == 404


async def test_update_rejects_inactive_operator(client, db_sessionmaker):
    op1 = await _create_operator(db_sessionmaker)
    inactive = await _create_inactive_operator(db_sessionmaker)
    shift1 = await _create_shift_time(db_sessionmaker, f"asg-shift-{_suffix()}", (8, 0), (12, 0))

    asg = await _create_assignment(db_sessionmaker, op1, shift1)

    resp = await client.client.put(
        f"/operator-shifts/{asg.id}",
        json={"operator_id": str(inactive.id), "shift_id": str(shift1.id), "status": "active"},
    )
    assert resp.status_code == 400

    await _clear(db_sessionmaker, [asg.id], [op1.id, inactive.id], [shift1.id])


async def test_update_conflict_on_existing_pair(client, db_sessionmaker):
    op1 = await _create_operator(db_sessionmaker)
    op2 = await _create_operator(db_sessionmaker)
    shift1 = await _create_shift_time(db_sessionmaker, f"asg-shift-{_suffix()}", (8, 0), (12, 0))

    asg1 = await _create_assignment(db_sessionmaker, op1, shift1)
    asg2 = await _create_assignment(db_sessionmaker, op2, shift1)

    resp = await client.client.put(
        f"/operator-shifts/{asg1.id}",
        json={"operator_id": str(op2.id), "shift_id": str(shift1.id), "status": "active"},
    )
    assert resp.status_code == 409

    await _clear(db_sessionmaker, [asg1.id, asg2.id], [op1.id, op2.id], [shift1.id])


async def test_create_rejects_shift_assigned_to_other_operator(client, db_sessionmaker):
    op1 = await _create_operator(db_sessionmaker)
    op2 = await _create_operator(db_sessionmaker)
    shift1 = await _create_shift_time(db_sessionmaker, f"asg-shift-{_suffix()}", (8, 0), (12, 0))

    asg1 = await _create_assignment(db_sessionmaker, op1, shift1)

    resp = await client.client.post(
        "/operator-shifts/",
        json={"operator_id": str(op2.id), "shift_id": str(shift1.id)},
    )
    assert resp.status_code == 409
    assert "operator lain" in resp.json()["detail"]

    await _clear(db_sessionmaker, [asg1.id], [op1.id, op2.id], [shift1.id])


async def test_update_rejects_shift_assigned_to_other_operator(client, db_sessionmaker):
    op1 = await _create_operator(db_sessionmaker)
    op2 = await _create_operator(db_sessionmaker)
    shift1 = await _create_shift_time(db_sessionmaker, f"asg-shift-{_suffix()}", (8, 0), (12, 0))
    shift2 = await _create_shift_time(db_sessionmaker, f"asg-shift-{_suffix()}", (13, 0), (17, 0))

    asg1 = await _create_assignment(db_sessionmaker, op1, shift1)
    asg2 = await _create_assignment(db_sessionmaker, op2, shift2)

    resp = await client.client.put(
        f"/operator-shifts/{asg1.id}",
        json={"operator_id": str(op1.id), "shift_id": str(shift2.id), "status": "active"},
    )
    assert resp.status_code == 409
    assert "operator lain" in resp.json()["detail"]

    await _clear(
        db_sessionmaker, [asg1.id, asg2.id], [op1.id, op2.id], [shift1.id, shift2.id]
    )
