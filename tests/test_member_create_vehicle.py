"""POST /members/ with an optional vehicle (police_number + vehicle_type_id).

The /member-vehicles endpoints are gone; the member's first vehicle is stored
in the same call that creates the member.
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
from api_trafix.models.vehicle_types import VehicleStatus, VehicleType
from api_trafix.routes import member as member_routes
from api_trafix.services.seed import seed_reference_data


@pytest_asyncio.fixture(autouse=True)
async def _restore_db_tables(db_sessionmaker):
    async with db_sessionmaker() as db:
        members = set((await db.execute(select(Member.id))).scalars().all())
        vehicle_types = set((await db.execute(select(VehicleType.id))).scalars().all())
        plans = set((await db.execute(select(SubscriptionPlan.id))).scalars().all())
    yield
    async with db_sessionmaker() as db:
        for model, keep in (
            (Member, members),
            (VehicleType, vehicle_types),
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
            name="Member Vehicle Test Admin",
            username=f"member-veh-{_suffix()}",
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


async def _vehicle_type(db_sessionmaker, code="MOBIL", status="active") -> VehicleType:
    async with db_sessionmaker() as db:
        vehicle_type = await db.scalar(
            select(VehicleType).where(VehicleType.code == code)
        )
        if vehicle_type is None:
            vehicle_type = VehicleType(
                code=code,
                name=code,
                status=VehicleStatus.ACTIVE
                if status == "active"
                else VehicleStatus.INACTIVE,
            )
            db.add(vehicle_type)
            await db.commit()
            await db.refresh(vehicle_type)
        return vehicle_type


async def test_create_member_without_vehicle(client):
    resp = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active", "phone_number": "081234567890"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["vehicles"] == []
    assert resp.json()["subscriptions"] == []


async def test_create_member_without_phone_rejected(client):
    resp = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active"},
    )
    assert resp.status_code == 422


async def test_create_member_with_blank_phone_rejected(client):
    resp = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active", "phone_number": "   "},
    )
    assert resp.status_code == 422


async def test_create_member_with_vehicle(client, db_sessionmaker):
    vehicle_type = await _vehicle_type(db_sessionmaker)
    raw_plate = f"b {_plate()[1:]}"  # lowercase + space to prove normalization

    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "phone_number": "081234567890",
            "police_number": raw_plate,
            "vehicle_type_id": str(vehicle_type.id),
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["vehicles"]) == 1
    vehicle = body["vehicles"][0]
    assert vehicle["police_number"] == raw_plate.strip().upper()
    assert vehicle["vehicle_type"]["id"] == str(vehicle_type.id)


async def test_create_member_with_unknown_vehicle_type(client, db_sessionmaker):
    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "phone_number": "081234567890",
            "police_number": _plate(),
            "vehicle_type_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 404


async def test_create_member_with_inactive_vehicle_type(client, db_sessionmaker):
    vehicle_type = await _vehicle_type(db_sessionmaker, code=f"SEP{_suffix()}", status="inactive")

    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "phone_number": "081234567890",
            "police_number": _plate(),
            "vehicle_type_id": str(vehicle_type.id),
        },
    )
    assert resp.status_code == 400
    assert "tidak aktif" in resp.json()["detail"].lower()


async def test_create_member_with_duplicate_police_number(client, db_sessionmaker):
    vehicle_type = await _vehicle_type(db_sessionmaker)
    plate = _plate()

    first = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "phone_number": "081234567890",
            "police_number": plate,
            "vehicle_type_id": str(vehicle_type.id),
        },
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "phone_number": "081234567890",
            "police_number": plate,
            "vehicle_type_id": str(vehicle_type.id),
        },
    )
    assert second.status_code == 400
    assert "sudah terdaftar" in second.json()["detail"].lower()


async def test_create_member_with_only_police_number(client, db_sessionmaker):
    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "phone_number": "081234567890",
            "police_number": _plate(),
        },
    )
    assert resp.status_code == 422


async def test_create_member_with_only_vehicle_type(client, db_sessionmaker):
    vehicle_type = await _vehicle_type(db_sessionmaker)

    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "phone_number": "081234567890",
            "vehicle_type_id": str(vehicle_type.id),
        },
    )
    assert resp.status_code == 422
