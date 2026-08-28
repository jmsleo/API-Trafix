"""Member "No. Member" = RFID card number.

Admin can register a member with an optional ``card_number`` (digits only,
leading zeros preserved), edit it later, or clear it. Duplicates are rejected.
"""

import uuid

import httpx
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.models.members import Member
from api_trafix.models.users import User, UserRole, UserStatus
from api_trafix.routes import member as member_routes
from api_trafix.services.seed import seed_reference_data


@pytest_asyncio.fixture(autouse=True)
async def _restore_db_tables(db_sessionmaker):
    async with db_sessionmaker() as db:
        members = set((await db.execute(select(Member.id))).scalars().all())
    yield
    async with db_sessionmaker() as db:
        for row in (await db.execute(select(Member))).scalars().all():
            if row.id not in members:
                await db.delete(row)
        await db.commit()


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture(scope="session")
async def admin_user(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(
            name="Member Card Test Admin",
            username=f"member-card-{_suffix()}",
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


async def test_create_member_with_card_number(client):
    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "card_number": "0006248873",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["card_number"] == "0006248873"


async def test_create_member_without_card_number(client):
    resp = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["card_number"] is None


async def test_create_member_empty_card_becomes_none(client):
    resp = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active", "card_number": "   "},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["card_number"] is None


async def test_create_member_non_digit_card_rejected(client):
    resp = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "card_number": "00-ABC",
        },
    )
    assert resp.status_code == 422


async def test_create_member_duplicate_card_rejected(client):
    card = f"00{uuid.uuid4().int % 10**8:08d}"

    first = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active", "card_number": card},
    )
    assert first.status_code == 201, first.text

    second = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active", "card_number": card},
    )
    assert second.status_code == 400
    assert "sudah terdaftar" in second.json()["detail"].lower()


async def test_update_member_assigns_card(client):
    created = await client.post(
        "/members/", json={"name": f"Member {_suffix()}", "status": "active"}
    )
    member_id = created.json()["id"]

    resp = await client.put(
        f"/members/{member_id}",
        json={"card_number": "0006248873"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["card_number"] == "0006248873"


async def test_update_member_replaces_card(client):
    created = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "card_number": "11112222",
        },
    )
    member_id = created.json()["id"]

    resp = await client.put(f"/members/{member_id}", json={"card_number": "33334444"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["card_number"] == "33334444"


async def test_update_member_clears_card_with_null(client):
    created = await client.post(
        "/members/",
        json={
            "name": f"Member {_suffix()}",
            "status": "active",
            "card_number": "11112222",
        },
    )
    member_id = created.json()["id"]

    resp = await client.put(f"/members/{member_id}", json={"card_number": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["card_number"] is None


async def test_update_member_card_conflict_rejected(client):
    card = f"00{uuid.uuid4().int % 10**8:08d}"
    holder = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active", "card_number": card},
    )
    assert holder.status_code == 201

    other = await client.post(
        "/members/", json={"name": f"Member {_suffix()}", "status": "active"}
    )
    assert other.status_code == 201

    resp = await client.put(
        f"/members/{other.json()['id']}", json={"card_number": card}
    )
    assert resp.status_code == 400
    assert "sudah terdaftar" in resp.json()["detail"].lower()


async def test_update_member_same_card_is_idempotent(client):
    card = f"00{uuid.uuid4().int % 10**8:08d}"
    created = await client.post(
        "/members/",
        json={"name": f"Member {_suffix()}", "status": "active", "card_number": card},
    )
    member_id = created.json()["id"]

    resp = await client.put(
        f"/members/{member_id}",
        json={"card_number": card, "phone_number": "081234567890"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["card_number"] == card
