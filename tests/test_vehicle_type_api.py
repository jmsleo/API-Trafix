"""Admin CRUD for /vehicle-types."""

import uuid
from types import SimpleNamespace

import httpx
import pytest_asyncio
from fastapi import FastAPI

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.models import User, UserRole, UserStatus
from api_trafix.routes import vehicle_type as vehicle_type_routes


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture
async def client(db_sessionmaker):
    app = FastAPI()
    app.include_router(vehicle_type_routes.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    admin = User(
        name="Vehicle Type Admin",
        username=f"vt-admin-{_suffix()}",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = lambda: admin

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield SimpleNamespace(client=c)
    # The module-level Redis client is bound to this test's event loop.
    from api_trafix.config.redis import close_redis

    await close_redis()


async def _delete_vehicle_type(db_sessionmaker, vehicle_type_id: str) -> None:
    from sqlalchemy import delete as sa_delete

    from api_trafix.models import VehicleType

    async with db_sessionmaker() as db:
        await db.execute(
            sa_delete(VehicleType).where(VehicleType.id == uuid.UUID(vehicle_type_id))
        )
        await db.commit()


async def test_create_and_update_it(client, db_sessionmaker):
    code = f"PRC{_suffix()}"
    resp = await client.client.post(
        "/vehicle-types/",
        json={"code": code, "name": "Mobil Test", "status": "active"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "price" not in body
    vehicle_type_id = body["id"]

    resp = await client.client.put(
        f"/vehicle-types/{vehicle_type_id}",
        json={"name": "Mobil A"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Mobil A"

    await _delete_vehicle_type(db_sessionmaker, vehicle_type_id)


async def test_create_ignores_removed_price_field(client, db_sessionmaker):
    code = f"NEG{_suffix()}"
    resp = await client.client.post(
        "/vehicle-types/",
        json={"code": code, "name": "Tidak Valid", "price": 4000, "status": "active"},
    )
    assert resp.status_code == 201, resp.text
    assert "price" not in resp.json()
    await _delete_vehicle_type(db_sessionmaker, resp.json()["id"])
