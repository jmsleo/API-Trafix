"""Admin CRUD for /subscription-plans with the required ``vehicle_type_id``.

Each package must belong to a vehicle type. This covers create/update/list
validation of the ``vehicle_type_id`` link and the nested ``vehicle_type`` brief
returned to the client.
"""

import uuid
from types import SimpleNamespace

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.models import User, UserRole, UserStatus
from api_trafix.models.vehicle_types import VehicleType
from api_trafix.routes import subscription_plan as subscription_plan_routes
from api_trafix.services.seed import seed_reference_data


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture
async def client(db_sessionmaker):
    async with db_sessionmaker() as db:
        await seed_reference_data(db)

    app = FastAPI()
    app.include_router(subscription_plan_routes.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    admin = User(
        name="Package Admin",
        username=f"pkg-admin-{_suffix()}",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = lambda: admin

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield SimpleNamespace(client=c)


async def _vehicle_type_id(db_sessionmaker) -> str:
    async with db_sessionmaker() as db:
        vt = await db.scalar(select(VehicleType).limit(1))
        assert vt is not None
        return str(vt.id)


async def _cleanup_plan(db_sessionmaker, plan_id: str) -> None:
    from sqlalchemy import delete as sa_delete

    from api_trafix.models.subscription_plans import SubscriptionPlan

    async with db_sessionmaker() as db:
        await db.execute(sa_delete(SubscriptionPlan).where(SubscriptionPlan.id == uuid.UUID(plan_id)))
        await db.commit()


async def test_create_plan_with_vehicle_type(client, db_sessionmaker):
    vt_id = await _vehicle_type_id(db_sessionmaker)
    resp = await client.client.post(
        "/subscription-plans/",
        json={
            "name": f"Package {_suffix()}",
            "duration_in_days": 30,
            "price": 100000,
            "vehicle_type_id": vt_id,
            "is_active": True,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["vehicle_type_id"] == vt_id
    assert body["vehicle_type"]["id"] == vt_id
    assert "name" in body["vehicle_type"]
    assert "updated_at" in body
    await _cleanup_plan(db_sessionmaker, body["id"])


async def test_create_plan_rejects_unknown_vehicle_type(client):
    resp = await client.client.post(
        "/subscription-plans/",
        json={
            "name": f"Package {_suffix()}",
            "duration_in_days": 30,
            "price": 100000,
            "vehicle_type_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404, resp.text


async def test_create_plan_requires_vehicle_type(client):
    resp = await client.client.post(
        "/subscription-plans/",
        json={"name": f"Package {_suffix()}", "duration_in_days": 30, "price": 100000},
    )
    assert resp.status_code == 422, resp.text


async def test_update_plan_rejects_unknown_vehicle_type(client, db_sessionmaker):
    vt_id = await _vehicle_type_id(db_sessionmaker)
    created = await client.client.post(
        "/subscription-plans/",
        json={
            "name": f"Package {_suffix()}",
            "duration_in_days": 30,
            "price": 100000,
            "vehicle_type_id": vt_id,
        },
    )
    assert created.status_code == 201, created.text
    plan_id = created.json()["id"]

    resp = await client.client.put(
        f"/subscription-plans/{plan_id}",
        json={"vehicle_type_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404, resp.text

    await _cleanup_plan(db_sessionmaker, plan_id)


async def test_list_plans_includes_vehicle_type(client, db_sessionmaker):
    from sqlalchemy import delete as sa_delete

    from api_trafix.models.subscription_plans import SubscriptionPlan

    vt_id = await _vehicle_type_id(db_sessionmaker)
    created = await client.client.post(
        "/subscription-plans/",
        json={
            "name": f"Package {_suffix()}",
            "duration_in_days": 30,
            "price": 100000,
            "vehicle_type_id": vt_id,
        },
    )
    assert created.status_code == 201, created.text

    listed = await client.client.get("/subscription-plans/")
    assert listed.status_code == 200, listed.text
    items = [it for it in listed.json()["items"] if it["id"] == created.json()["id"]]
    assert len(items) == 1
    assert items[0]["vehicle_type"]["id"] == vt_id

    async with db_sessionmaker() as db:
        await db.execute(
            sa_delete(SubscriptionPlan).where(SubscriptionPlan.id == uuid.UUID(created.json()["id"]))
        )
        await db.commit()
