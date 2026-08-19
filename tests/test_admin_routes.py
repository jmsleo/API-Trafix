"""Admin CRUD route tests for gates and devices.

These exercise the FastAPI layer (routers + schemas + crud) against the real
``trafix_test`` database. Authentication is short-circuited by overriding the
``get_current_admin`` dependency; each request gets its own session via the
``get_db`` override so route-level commits behave as in production.
"""

import uuid
from datetime import UTC, datetime

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin_or_teknisi
from api_trafix.models.devices import Device
from api_trafix.models.gates import Gate
from api_trafix.models.park_transactions import DetectionMethod, ParkTransaction
from api_trafix.models.users import User, UserRole, UserStatus
from api_trafix.models.vehicle_types import VehicleStatus, VehicleType
from api_trafix.routes import devices, gates


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture(scope="session")
async def admin_user(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(
            name="Route Test Admin",
            username=f"route-admin-{_suffix()}",
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
    app.include_router(gates.router)
    app.include_router(devices.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    async def override_admin():
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin_or_teknisi] = override_admin

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _delete_gate(db_sessionmaker, gate_id: str) -> None:
    async with db_sessionmaker() as db:
        obj = await db.get(Gate, uuid.UUID(gate_id))
        if obj is not None:
            await db.delete(obj)
            await db.commit()


async def test_create_gate_and_reject_duplicate_code(client, db_sessionmaker):
    code = _suffix()
    resp = await client.post(
        "/gates/",
        json={"name": "Entry Gate", "gate_code": code, "type": "gate_in", "status": "online"},
    )
    assert resp.status_code == 201
    body = resp.json()
    gate_id = body["id"]
    assert body["gate_code"] == code
    assert body["type"] == "gate_in"

    resp = await client.post(
        "/gates/",
        json={"name": "Clash", "gate_code": code, "type": "gate_out", "status": "offline"},
    )
    assert resp.status_code == 400

    await _delete_gate(db_sessionmaker, gate_id)


async def test_create_gate_without_gate_code(client, db_sessionmaker):
    resp = await client.post(
        "/gates/",
        json={"name": "Future Gate", "type": "gate_out", "status": "offline"},
    )
    assert resp.status_code == 201
    assert resp.json()["gate_code"] is None
    await _delete_gate(db_sessionmaker, resp.json()["id"])


async def test_list_and_filter_gates(client, db_sessionmaker):
    code = _suffix()
    first = await client.post(
        "/gates/",
        json={"name": "Filtered Gate", "gate_code": code, "type": "gate_in", "status": "online"},
    )
    assert first.status_code == 201

    resp = await client.get("/gates/", params={"search": code})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    assert all(item["gate_code"] == code for item in resp.json()["items"])

    resp = await client.get("/gates/", params={"search": code, "type": "gate_out"})
    assert resp.json()["total"] == 0

    resp = await client.get("/gates/", params={"page": 1, "page_size": 5})
    assert resp.status_code == 200
    assert resp.json()["page"] == 1

    await _delete_gate(db_sessionmaker, first.json()["id"])


async def test_get_gate_and_404(client, db_sessionmaker):
    resp = await client.get(f"/gates/{uuid.uuid4()}")
    assert resp.status_code == 404

    created = await client.post(
        "/gates/",
        json={"name": "Read Me", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = created.json()["id"]
    resp = await client.get(f"/gates/{gate_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Read Me"
    await _delete_gate(db_sessionmaker, gate_id)


async def test_update_gate_and_code_collision(client, db_sessionmaker):
    code1, code2 = _suffix(), _suffix()
    first = await client.post(
        "/gates/",
        json={"name": "Original", "gate_code": code1, "type": "gate_in", "status": "online"},
    )
    second = await client.post(
        "/gates/",
        json={"name": "Other", "gate_code": code2, "type": "gate_out", "status": "offline"},
    )
    id1 = first.json()["id"]

    resp = await client.put(f"/gates/{id1}", json={"gate_code": code2})
    assert resp.status_code == 400

    resp = await client.put(f"/gates/{id1}", json={"name": "Renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Renamed"
    assert resp.json()["gate_code"] == code1

    await _delete_gate(db_sessionmaker, id1)
    await _delete_gate(db_sessionmaker, second.json()["id"])


async def test_delete_gate(client):
    created = await client.post(
        "/gates/",
        json={"name": "Bye", "gate_code": _suffix(), "type": "gate_out", "status": "offline"},
    )
    gate_id = created.json()["id"]

    resp = await client.delete(f"/gates/{gate_id}")
    assert resp.status_code == 204
    resp = await client.get(f"/gates/{gate_id}")
    assert resp.status_code == 404


async def test_delete_gate_referenced_by_transaction_is_conflict(client, db_sessionmaker):
    created = await client.post(
        "/gates/",
        json={"name": "Busy", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = uuid.UUID(created.json()["id"])

    async with db_sessionmaker() as db:
        vehicle_type = VehicleType(
            code=f"vt-{_suffix()}", name="Test Vehicle", status=VehicleStatus.ACTIVE
        )
        db.add(vehicle_type)
        await db.flush()
        tx = ParkTransaction(
            vehicle_type_id=vehicle_type.id,
            entry_gate_id=gate_id,
            entry_time=datetime.now(UTC),
            detection_method=DetectionMethod.MANUAL,
        )
        db.add(tx)
        await db.commit()
        tx_id = tx.id
        vt_id = vehicle_type.id

    resp = await client.delete(f"/gates/{gate_id}")
    assert resp.status_code == 409

    async with db_sessionmaker() as db:
        for model, obj_id in [
            (ParkTransaction, tx_id),
            (VehicleType, vt_id),
            (Gate, gate_id),
        ]:
            obj = await db.get(model, obj_id)
            if obj is not None:
                await db.delete(obj)
        await db.commit()


async def test_device_crud_against_existing_gate(client, db_sessionmaker):
    created = await client.post(
        "/gates/",
        json={"name": "Device Host", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = created.json()["id"]

    payload = {
        "gate_id": gate_id,
        "name": "LPR Camera",
        "type": "lpr",
        "ip_address": "10.1.1.5",
        "config": {"base_url": "http://10.1.1.5"},
    }

    resp = await client.post("/devices/", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    device_id = body["id"]
    assert body["type"] == "lpr"
    assert body["status"] == "offline"

    resp = await client.post("/devices/", json={**payload, "gate_id": str(uuid.uuid4())})
    assert resp.status_code == 400

    resp = await client.get("/devices/", params={"gate_id": gate_id})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp = await client.put(f"/devices/{device_id}", json={"status": "online"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "online"

    resp = await client.get(f"/devices/{device_id}")
    assert resp.status_code == 200
    assert resp.json()["ip_address"] == "10.1.1.5"

    resp = await client.get(f"/devices/{uuid.uuid4()}")
    assert resp.status_code == 404

    resp = await client.delete(f"/devices/{device_id}")
    assert resp.status_code == 204

    await _delete_gate(db_sessionmaker, gate_id)


async def test_list_devices_by_type(client, db_sessionmaker):
    created = await client.post(
        "/gates/",
        json={"name": "Type Host", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = created.json()["id"]

    base = {
        "gate_id": gate_id,
        "name": "Controller",
        "type": "gate-controller",
        "ip_address": "10.1.1.9",
    }
    await client.post("/devices/", json=base)

    resp = await client.get("/devices/", params={"type": "controller"})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    assert all("controller" in item["type"] for item in resp.json()["items"])

    resp = await client.get("/devices/", params={"type": "camera"})
    assert resp.json()["total"] == 0

    async with db_sessionmaker() as db:
        devices_ = (
            await db.execute(select(Device).where(Device.gate_id == uuid.UUID(gate_id)))
        ).scalars().all()
        for device in devices_:
            await db.delete(device)
        await db.commit()
    await _delete_gate(db_sessionmaker, gate_id)
