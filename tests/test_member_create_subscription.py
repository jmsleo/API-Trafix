"""POST /members/ with an optional subscription (plan_id from /subscription-plans/).

The member's first subscription is created atomically in the same call that
creates the member, alongside any vehicle fields.
"""

import uuid

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.models.members import Member
from api_trafix.models.subscription_plans import SubscriptionPlan
from api_trafix.models.users import User, UserRole, UserStatus
from api_trafix.models.vehicle_types import VehicleType
from api_trafix.routes import member as member_routes
from api_trafix.services.seed import seed_reference_data


@pytest_asyncio.fixture(autouse=True)
async def _restore_db_tables(db_sessionmaker):
    async with db_sessionmaker() as db:
        members = set((await db.execute(select(Member.id))).scalars().all())
        plans = set((await db.execute(select(SubscriptionPlan.id))).scalars().all())
    yield
    async with db_sessionmaker() as db:
        for model, keep in (
            (Member, members),
            (SubscriptionPlan, plans),
        ):
            for row in (await db.execute(select(model))).scalars().all():
                if row.id not in keep:
                    await db.delete(row)
        await db.commit()


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def _plate() -> str:
    return f"H{uuid.uuid4().hex[:6].upper()}"


@pytest_asyncio.fixture(scope="session")
async def admin_user(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(
            name="Member Subscription Test Admin",
            username=f"member-sub-{_suffix()}",
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


async def _plan(db_sessionmaker, name=None, is_active=True) -> SubscriptionPlan:
    async with db_sessionmaker() as db:
        plan = SubscriptionPlan(
            name=name or f"Plan {_suffix()}",
            duration_in_days=30,
            price=100000,
            is_active=is_active,
        )
        db.add(plan)
        await db.commit()
        await db.refresh(plan)
        return plan


async def test_create_member_with_subscription(client, db_sessionmaker):
    plan = await _plan(db_sessionmaker)

    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "plan_id": str(plan.id),
        },
    )
    assert resp.status_code == 201, resp.text
    subscriptions = resp.json()["subscriptions"]
    assert len(subscriptions) == 1
    sub = subscriptions[0]
    assert sub["plan"]["id"] == str(plan.id)
    assert sub["status"] == "active"
    assert sub["start_date"] < sub["end_date"]


async def test_create_member_with_unknown_plan(client, db_sessionmaker):
    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "plan_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404


async def test_create_member_with_inactive_plan(client, db_sessionmaker):
    plan = await _plan(db_sessionmaker, is_active=False)

    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "plan_id": str(plan.id),
        },
    )
    assert resp.status_code == 400
    assert "tidak aktif" in resp.json()["detail"].lower()


async def test_create_inactive_member_with_plan(client, db_sessionmaker):
    plan = await _plan(db_sessionmaker)

    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "inactive",
            "plan_id": str(plan.id),
        },
    )
    assert resp.status_code == 400
    assert "member tidak aktif" in resp.json()["detail"].lower()


async def test_create_member_with_vehicle_and_subscription(client, db_sessionmaker):
    plan = await _plan(db_sessionmaker)
    async with db_sessionmaker() as db:
        vehicle_type = await db.scalar(select(VehicleType).limit(1))
        assert vehicle_type is not None
        vehicle_type_id = str(vehicle_type.id)

    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "police_number": _plate(),
            "vehicle_type_id": vehicle_type_id,
            "plan_id": str(plan.id),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["vehicles"]) == 1
    assert len(body["subscriptions"]) == 1
    assert body["subscriptions"][0]["plan"]["id"] == str(plan.id)


async def test_create_member_without_subscription(client):
    resp = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["subscriptions"] == []
