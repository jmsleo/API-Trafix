"""Reproduction: change a member's package via PUT /members/{id}."""

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
async def _restore(db_sessionmaker):
    async with db_sessionmaker() as db:
        members = set((await db.execute(select(Member.id))).scalars().all())
        plans = set((await db.execute(select(SubscriptionPlan.id))).scalars().all())
    yield
    async with db_sessionmaker() as db:
        for model, keep in ((Member, members), (SubscriptionPlan, plans)):
            for row in (await db.execute(select(model))).scalars().all():
                if row.id not in keep:
                    await db.delete(row)
        await db.commit()


def _suffix():
    return uuid.uuid4().hex[:8]


def _plate():
    return f"H{uuid.uuid4().hex[:6].upper()}"


def _base(name=None):
    return {
        "name": name or f"Member {_suffix()}",
        "status": "active",
        "email": f"m{_suffix()}@example.com",
        "phone_number": "081234567890",
        "card_number": f"{uuid.uuid4().int % 10**8:08d}",
    }


@pytest_asyncio.fixture(scope="session")
async def admin_user(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(
            name="Repro Admin",
            username=f"repro-{_suffix()}",
            password="unused",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.commit()
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


async def _plan(db_sessionmaker, name=None, is_active=True):
    async with db_sessionmaker() as db:
        vehicle_type = await db.scalar(select(VehicleType).limit(1))
        plan = SubscriptionPlan(
            name=name or f"Plan {_suffix()}",
            duration_in_days=30,
            price=100000,
            vehicle_type_id=vehicle_type.id,
            is_active=is_active,
        )
        db.add(plan)
        await db.commit()
        await db.refresh(plan)
        return plan


async def test_change_plan(client, db_sessionmaker):
    plan_bulanan = await _plan(db_sessionmaker, name="bulanan")
    plan_tenant = await _plan(db_sessionmaker, name="tenant")

    async with db_sessionmaker() as db:
        vt = await db.scalar(select(VehicleType).limit(1))
        vt_id = str(vt.id)

    created = await client.post(
        "/members/",
        json={
            **_base("Angelo"),
            "police_number": _plate(),
            "vehicle_type_id": vt_id,
            "plan_id": str(plan_bulanan.id),
        },
    )
    assert created.status_code == 201, created.text
    member_id = created.json()["id"]
    assert created.json()["subscriptions"][0]["plan"]["id"] == str(plan_bulanan.id)

    # Now change the plan from bulanan -> tenant via the SAME member+vehicle+plan payload
    # the frontend sends on edit.
    update = await client.put(
        f"/members/{member_id}",
        json={
            "name": "Angelo",
            "email": created.json()["email"],
            "phone_number": created.json()["phone_number"],
            "card_number": created.json()["card_number"],
            "status": "active",
            "plan_id": str(plan_tenant.id),
            "police_number": created.json()["vehicles"][0]["police_number"],
            "vehicle_type_id": created.json()["vehicles"][0]["vehicle_type"]["id"],
        },
    )
    print("UPDATE STATUS:", update.status_code)
    print("UPDATE BODY:", update.text)
    assert update.status_code == 200, update.text

    body = update.json()
    active_subs = [s for s in body["subscriptions"] if s["status"] == "active"]
    print("ACTIVE SUBS:", [(s["plan"]["name"], s["status"]) for s in body["subscriptions"]])
    assert any(s["plan"]["id"] == str(plan_tenant.id) and s["status"] == "active"
               for s in body["subscriptions"]), "tenant plan not active after update"
    assert body["subscriptions"] and body["subscriptions"][0]["status"] == "active", (
        "subscriptions[0] should be the active subscription (deterministic ordering)"
    )
    assert body["subscriptions"][0]["plan"]["id"] == str(plan_tenant.id), (
        "subscriptions[0] should be the tenant plan"
    )
