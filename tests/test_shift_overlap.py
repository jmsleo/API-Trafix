"""Admin CRUD for /shifts enforcing no overlapping ACTIVE shifts.

Two active shifts must not time-overlap. Inactive shifts are ignored, a shift
is never compared against itself on update, and shifts that merely touch
(finish == start) are allowed. Crossing-midnight shifts wrap around the clock.
"""

import uuid
from types import SimpleNamespace

import httpx
import pytest_asyncio
from fastapi import FastAPI

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.models import User, UserRole, UserStatus
from api_trafix.routes import shift as shift_routes


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture(autouse=True)
async def _clear_shifts(db_sessionmaker):
    """Start each overlap test from an empty shifts table.

    Other test modules (e.g. POS) leave active shifts behind in the shared
    session database, which would otherwise make these overlap assertions
    non-deterministic depending on the real clock time.
    """
    from sqlalchemy import delete as sa_delete

    from api_trafix.models.operator_sessions import OperatorSession
    from api_trafix.models.operator_shift_assignments import OperatorShiftAssignment
    from api_trafix.models.shifts import Shift

    async with db_sessionmaker() as db:
        # operator_sessions / operator_shift_assignments FK into shifts and must
        # be cleared first.
        await db.execute(sa_delete(OperatorSession))
        await db.execute(sa_delete(OperatorShiftAssignment))
        await db.execute(sa_delete(Shift))
        await db.commit()
    yield


def _shift_payload(name: str, start: str, finish: str, status: str = "active", crosses: bool = False) -> dict:
    return {
        "name": name,
        "start_time": start,
        "finish_time": finish,
        "crosses_midnight": crosses,
        "status": status,
    }


@pytest_asyncio.fixture
async def client(db_sessionmaker):
    app = FastAPI()
    app.include_router(shift_routes.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    admin = User(
        name="Shift Admin",
        username=f"shift-admin-{_suffix()}",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = lambda: admin

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield SimpleNamespace(client=c)


async def _cleanup_shift(db_sessionmaker, shift_id: str) -> None:
    from sqlalchemy import delete as sa_delete

    from api_trafix.models.shifts import Shift

    async with db_sessionmaker() as db:
        await db.execute(sa_delete(Shift).where(Shift.id == uuid.UUID(shift_id)))
        await db.commit()


async def test_create_overlapping_active_shift_rejected(client, db_sessionmaker):
    first = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Pagi {_suffix()}", "07:00", "15:00"),
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    resp = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Pagi2 {_suffix()}", "14:00", "17:00"),
    )
    assert resp.status_code == 409, resp.text

    await _cleanup_shift(db_sessionmaker, first_id)


async def test_create_non_overlapping_active_shift_allowed(client, db_sessionmaker):
    first = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Pagi {_suffix()}", "07:00", "15:00"),
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    second = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Malam {_suffix()}", "17:00", "23:59"),
    )
    assert second.status_code == 201, second.text

    await _cleanup_shift(db_sessionmaker, first_id)
    await _cleanup_shift(db_sessionmaker, second.json()["id"])


async def test_touching_shifts_do_not_overlap(client, db_sessionmaker):
    first = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Pagi {_suffix()}", "07:00", "15:00"),
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]

    second = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Sore {_suffix()}", "15:00", "22:00"),
    )
    assert second.status_code == 201, second.text

    await _cleanup_shift(db_sessionmaker, first_id)
    await _cleanup_shift(db_sessionmaker, second.json()["id"])


async def test_overlap_with_inactive_shift_allowed(client, db_sessionmaker):
    inactive = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Lama {_suffix()}", "07:00", "15:00", status="inactive"),
    )
    assert inactive.status_code == 201, inactive.text
    inactive_id = inactive.json()["id"]

    active = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Baru {_suffix()}", "08:00", "14:00"),
    )
    assert active.status_code == 201, active.text

    await _cleanup_shift(db_sessionmaker, inactive_id)
    await _cleanup_shift(db_sessionmaker, active.json()["id"])


async def test_update_overlap_rejected_excluding_self(client, db_sessionmaker):
    a = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"A {_suffix()}", "07:00", "15:00"),
    )
    b = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"B {_suffix()}", "17:00", "22:00"),
    )
    a_id = a.json()["id"]
    b_id = b.json()["id"]

    # B overlaps A -> rejected.
    resp = await client.client.put(
        f"/shifts/{b_id}",
        json={"start_time": "14:00", "finish_time": "18:00"},
    )
    assert resp.status_code == 409, resp.text

    # B changes to non-overlapping -> allowed.
    resp2 = await client.client.put(
        f"/shifts/{b_id}",
        json={"start_time": "16:00", "finish_time": "22:00"},
    )
    assert resp2.status_code == 200, resp2.text

    # A keeps overlapping itself -> still allowed on update of unrelated field.
    resp3 = await client.client.put(
        f"/shifts/{a_id}",
        json={"finish_time": "15:00"},
    )
    assert resp3.status_code == 200, resp3.text

    await _cleanup_shift(db_sessionmaker, a_id)
    await _cleanup_shift(db_sessionmaker, b_id)


async def test_crossing_midnight_overlap_rejected(client, db_sessionmaker):
    a = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Night {_suffix()}", "22:00", "06:00", crosses=True),
    )
    assert a.status_code == 201, a.text
    a_id = a.json()["id"]

    # 05:00-07:00 overlaps the overnight shift's 00:00-06:00 wrap.
    resp = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"Dawn {_suffix()}", "05:00", "07:00"),
    )
    assert resp.status_code == 409, resp.text

    await _cleanup_shift(db_sessionmaker, a_id)


async def test_two_crossing_midnight_same_time_rejected(client, db_sessionmaker):
    a = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"NightA {_suffix()}", "22:00", "06:00", crosses=True),
    )
    assert a.status_code == 201, a.text
    a_id = a.json()["id"]

    resp = await client.client.post(
        "/shifts/",
        json=_shift_payload(f"NightB {_suffix()}", "22:00", "06:00", crosses=True),
    )
    assert resp.status_code == 409, resp.text

    await _cleanup_shift(db_sessionmaker, a_id)
