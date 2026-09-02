"""Parking rate name uniqueness route tests.

These exercise the FastAPI layer (routers + schemas + crud) against the real
``trafix_test`` database, mirroring the gate-route test pattern in
``test_admin_routes.py``. The ``get_current_admin`` dependency is overridden so
requests hit the crud/validation logic without authentication.
"""

import uuid

import httpx
import pytest_asyncio
from fastapi import FastAPI

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.models.users import User, UserRole, UserStatus
from api_trafix.models.vehicle_types import VehicleStatus, VehicleType
from api_trafix.routes import parking_rate


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture(scope="session")
async def admin_user(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(
            name="Parking Rate Test Admin",
            username=f"pr-admin-{_suffix()}",
            password="unused",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest_asyncio.fixture
async def client(db_sessionmaker, admin_user):
    app = FastAPI()
    app.include_router(parking_rate.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    async def override_admin():
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_admin

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def vehicle_type_id(db_sessionmaker):
    async with db_sessionmaker() as db:
        vt = VehicleType(
            code=f"vt-{_suffix()}", name="Test Vehicle", status=VehicleStatus.ACTIVE
        )
        db.add(vt)
        await db.commit()
        await db.refresh(vt)
        vt_id = str(vt.id)
    yield vt_id
    async with db_sessionmaker() as db:
        obj = await db.get(VehicleType, uuid.UUID(vt_id))
        if obj is not None:
            await db.delete(obj)
            await db.commit()


def _rate_payload(vehicle_type_id: str, name: str) -> dict:
    return {
        "name": name,
        "vehicle_type_id": vehicle_type_id,
        "base_price": 10000,
        "fee_category": "flat",
        "status": "active",
    }


async def test_create_rejects_duplicate_name(client, db_sessionmaker, vehicle_type_id):
    name = f"Reguler {_suffix()}"
    resp = await client.post("/parking-rates/", json=_rate_payload(vehicle_type_id, name))
    assert resp.status_code == 201
    rate_id = resp.json()["id"]

    resp = await client.post("/parking-rates/", json=_rate_payload(vehicle_type_id, name))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Nama sudah digunakan"

    async with db_sessionmaker() as db:
        from api_trafix.models.parking_rates import ParkingRate

        obj = await db.get(ParkingRate, uuid.UUID(rate_id))
        if obj is not None:
            await db.delete(obj)
            await db.commit()


async def test_create_allows_unique_names_case_and_trimmed(client, db_sessionmaker, vehicle_type_id):
    resp = await client.post(
        "/parking-rates/", json=_rate_payload(vehicle_type_id, f"Motor {_suffix()}")
    )
    assert resp.status_code == 201
    rate_id = resp.json()["id"]

    resp = await client.post(
        "/parking-rates/", json=_rate_payload(vehicle_type_id, f"Lain-{_suffix()}")
    )
    assert resp.status_code == 201

    async with db_sessionmaker() as db:
        from api_trafix.models.parking_rates import ParkingRate

        obj = await db.get(ParkingRate, uuid.UUID(rate_id))
        if obj is not None:
            await db.delete(obj)
            await db.commit()


async def test_update_rejects_duplicate_name(client, db_sessionmaker, vehicle_type_id):
    name_a = f"A-{_suffix()}"
    name_b = f"B-{_suffix()}"
    a = await client.post("/parking-rates/", json=_rate_payload(vehicle_type_id, name_a))
    b = await client.post("/parking-rates/", json=_rate_payload(vehicle_type_id, name_b))
    assert a.status_code == 201 and b.status_code == 201
    a_id, b_id = a.json()["id"], b.json()["id"]

    resp = await client.put(f"/parking-rates/{a_id}", json={"name": name_b})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Nama sudah digunakan"

    async with db_sessionmaker() as db:
        from api_trafix.models.parking_rates import ParkingRate

        for rid in (a_id, b_id):
            obj = await db.get(ParkingRate, uuid.UUID(rid))
            if obj is not None:
                await db.delete(obj)
        await db.commit()


async def test_update_ignores_own_name(client, db_sessionmaker, vehicle_type_id):
    name = f"Self-{_suffix()}"
    resp = await client.post("/parking-rates/", json=_rate_payload(vehicle_type_id, name))
    assert resp.status_code == 201
    rate_id = resp.json()["id"]

    resp = await client.put(f"/parking-rates/{rate_id}", json={"name": name})
    assert resp.status_code == 200
    assert resp.json()["name"] == name

    async with db_sessionmaker() as db:
        from api_trafix.models.parking_rates import ParkingRate

        obj = await db.get(ParkingRate, uuid.UUID(rate_id))
        if obj is not None:
            await db.delete(obj)
            await db.commit()
