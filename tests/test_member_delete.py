"""Regression test for deleting a member that owns vehicles/subscriptions.

Deleting a member must cascade its ``member_vehicles`` and
``member_subscriptions`` rows instead of trying to NULL their NOT NULL
``member_id`` columns (which raised a 500).
"""

import uuid

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.models.member_vehicles import MemberVehicle
from api_trafix.models.members import Member
from api_trafix.models.subscription_plans import SubscriptionPlan
from api_trafix.models.users import User, UserRole, UserStatus
from api_trafix.models.vehicle_types import VehicleType
from api_trafix.routes import member as member_routes
from api_trafix.routes import member_subscription as member_subscription_routes
from api_trafix.services.seed import seed_reference_data


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _plate() -> str:
    return f"H{uuid.uuid4().hex[:6].upper()}"


@pytest_asyncio.fixture(scope="session")
async def admin_user(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(
            name="Member Delete Test Admin",
            username=f"member-del-{_suffix()}",
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
    async with db_sessionmaker() as db:
        await seed_reference_data(db)

    app = FastAPI()
    app.include_router(member_routes.router)
    app.include_router(member_subscription_routes.router)

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


async def _create_member(client) -> str:
    resp = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_delete_member_cascades_owned_vehicles(client, db_sessionmaker):
    async with db_sessionmaker() as db:
        vehicle_type = await db.scalar(
            select(VehicleType).where(VehicleType.code == "MOBIL")
        )
        assert vehicle_type is not None
        vehicle_type_id = str(vehicle_type.id)

    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "police_number": _plate(),
            "vehicle_type_id": vehicle_type_id,
        },
    )
    assert resp.status_code == 201, resp.text
    member_id = resp.json()["id"]
    assert resp.json()["vehicles"][0]["police_number"] is not None

    resp = await client.delete(f"/members/{member_id}")
    assert resp.status_code == 204, resp.text

    async with db_sessionmaker() as db:
        member = await db.get(Member, uuid.UUID(member_id))
        vehicles = (
            await db.execute(
                select(MemberVehicle).where(MemberVehicle.member_id == member_id)
            )
        ).scalars().all()
    assert member is None
    assert vehicles == []


async def test_delete_member_cascades_owned_subscriptions(client, db_sessionmaker):
    member_id = await _create_member(client)

    async with db_sessionmaker() as db:
        plan = await db.scalar(select(SubscriptionPlan).limit(1))
        if plan is None:
            plan = SubscriptionPlan(
                name=f"Plan {_suffix()}",
                duration_in_days=30,
                price=10000,
                is_active=True,
            )
            db.add(plan)
            await db.commit()
            await db.refresh(plan)
        plan_id = str(plan.id)

    resp = await client.post(
        "/member-subscriptions/",
        json={"member_id": member_id, "plan_id": plan_id},
    )
    assert resp.status_code == 201, resp.text

    resp = await client.delete(f"/members/{member_id}")
    assert resp.status_code == 204, resp.text

    async with db_sessionmaker() as db:
        member = await db.get(Member, uuid.UUID(member_id))
    assert member is None
