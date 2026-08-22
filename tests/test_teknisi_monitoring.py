"""Tests for the Teknisi monitoring endpoints.

Covers: teknisi-role access to gates/devices CRUD, the consolidated device
monitoring list, test connection, restart device, and MQTT config
GET/PUT persistence.  ``get_current_admin_or_teknisi`` is overridden with a
teknisi user to prove the teknisi role is accepted.
"""

import json
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin_or_teknisi
from api_trafix.models.users import User, UserRole, UserStatus
from api_trafix.routes import devices, gates, monitoring, system


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


@pytest_asyncio.fixture(scope="session")
async def teknisi_user(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(
            name="Route Test Teknisi",
            username=f"route-teknisi-{_suffix()}",
            password="unused",
            role=UserRole.TEKNISI,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest_asyncio.fixture
async def client(db_sessionmaker, teknisi_user):
    app = FastAPI()
    app.include_router(gates.router)
    app.include_router(devices.router)
    app.include_router(monitoring.router)
    app.include_router(system.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    async def override_auth():
        return teknisi_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin_or_teknisi] = override_auth

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _cleanup(db_sessionmaker, model, obj_id):
    async with db_sessionmaker() as db:
        obj = await db.get(model, uuid.UUID(obj_id))
        if obj is not None:
            await db.delete(obj)
            await db.commit()


async def test_teknisi_can_create_and_update_gate(client, db_sessionmaker):
    from api_trafix.models.gates import Gate

    resp = await client.post(
        "/gates/",
        json={"name": "Teknisi Gate", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    assert resp.status_code == 201, resp.text
    gate_id = resp.json()["id"]

    resp = await client.put(f"/gates/{gate_id}", json={"name": "Teknisi Gate Renamed"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Teknisi Gate Renamed"

    await _cleanup(db_sessionmaker, Gate, gate_id)


async def test_teknisi_can_manage_devices(client, db_sessionmaker):
    from api_trafix.models.devices import Device
    from api_trafix.models.gates import Gate

    created = await client.post(
        "/gates/",
        json={"name": "Dev Host", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = created.json()["id"]

    resp = await client.post(
        "/devices/",
        json={
            "gate_id": gate_id,
            "name": "Teknisi Controller",
            "type": "gate-controller",
            "ip_address": "10.0.0.9",
            "config": {"connection_type": "mqtt", "serial_no": "SER123"},
        },
    )
    assert resp.status_code == 201, resp.text
    device_id = resp.json()["id"]

    resp = await client.get("/devices/", params={"gate_id": gate_id})
    assert resp.json()["total"] == 1

    await _cleanup(db_sessionmaker, Device, device_id)
    await _cleanup(db_sessionmaker, Gate, gate_id)


async def test_monitoring_devices_lists_controller(client, db_sessionmaker):
    from api_trafix.models.devices import Device
    from api_trafix.models.gates import Gate

    created = await client.post(
        "/gates/",
        json={"name": "Mon Gate", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = created.json()["id"]

    resp = await client.post(
        "/devices/",
        json={
            "gate_id": gate_id,
            "name": "Mon Controller",
            "type": "gate-controller",
            "ip_address": "10.0.0.10",
        },
    )
    device_id = resp.json()["id"]

    resp = await client.get("/api/monitoring/devices", params={"kind": "controller"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    mon = next((i for i in body["items"] if i["id"] == device_id), None)
    assert mon is not None
    assert mon["kind"] == "controller"
    assert mon["status"] in ("online", "offline")

    await _cleanup(db_sessionmaker, Device, device_id)
    await _cleanup(db_sessionmaker, Gate, gate_id)


async def test_monitoring_devices_filter_by_type(client, db_sessionmaker):
    from api_trafix.models.devices import Device
    from api_trafix.models.gates import Gate

    created = await client.post(
        "/gates/",
        json={"name": "Mon2 Gate", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = created.json()["id"]

    resp = await client.post(
        "/devices/",
        json={
            "gate_id": gate_id,
            "name": "Mon LPR",
            "type": "camera lpr",
            "ip_address": "10.0.0.11",
            "config": {"serves_http": False},
        },
    )
    device_id = resp.json()["id"]

    resp = await client.get("/api/monitoring/devices", params={"kind": "lpr"})
    assert resp.status_code == 200
    assert any(i["id"] == device_id for i in resp.json()["items"])

    await _cleanup(db_sessionmaker, Device, device_id)
    await _cleanup(db_sessionmaker, Gate, gate_id)


async def test_test_connection_controller(client, db_sessionmaker):
    from api_trafix.models.devices import Device
    from api_trafix.models.gates import Gate

    created = await client.post(
        "/gates/",
        json={"name": "Test Gate", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = created.json()["id"]

    resp = await client.post(
        "/devices/",
        json={
            "gate_id": gate_id,
            "name": "Test Controller",
            "type": "gate-controller",
            "ip_address": "10.0.0.12",
        },
    )
    device_id = resp.json()["id"]

    resp = await client.post(f"/api/monitoring/devices/{device_id}/test")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["device_id"] == device_id
    assert body["kind"] == "controller"
    assert body["status"] in ("online", "offline")

    resp = await client.post(f"/api/monitoring/devices/{uuid.uuid4()}/test")
    assert resp.status_code == 404

    await _cleanup(db_sessionmaker, Device, device_id)
    await _cleanup(db_sessionmaker, Gate, gate_id)


async def test_restart_controller_is_not_supported(client, db_sessionmaker):
    from api_trafix.models.devices import Device
    from api_trafix.models.gates import Gate

    created = await client.post(
        "/gates/",
        json={"name": "Restart Gate", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = created.json()["id"]

    resp = await client.post(
        "/devices/",
        json={
            "gate_id": gate_id,
            "name": "Restart Controller",
            "type": "gate-controller",
            "ip_address": "10.0.0.13",
        },
    )
    device_id = resp.json()["id"]

    resp = await client.post(f"/api/monitoring/devices/{device_id}/restart")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "not_supported"

    await _cleanup(db_sessionmaker, Device, device_id)
    await _cleanup(db_sessionmaker, Gate, gate_id)


async def test_mqtt_config_roundtrip(client, db_sessionmaker):
    from api_trafix.models.system_config import SystemConfig

    config = {
        "host": "10.20.30.40",
        "port": 1884,
        "keepalive": 45,
        "username": "teknisi-user",
        "password": "secret",
        "client_id_prefix": "api-trafix-test",
    }

    resp = await client.put("/api/system/mqtt/config", json=config)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["host"] == "10.20.30.40"
    assert body["port"] == 1884
    assert body["username"] == "teknisi-user"

    resp = await client.get("/api/system/mqtt/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["host"] == "10.20.30.40"
    assert body["port"] == 1884

    # Cleanup persisted rows.
    async with db_sessionmaker() as db:
        rows = (
            await db.execute(
                SystemConfig.__table__.select().where(SystemConfig.section == "mqtt")
            )
        ).all()
        for row in rows:
            obj = await db.get(SystemConfig, row.id)
            await db.delete(obj)
        await db.commit()


async def test_monitoring_stream_yields_snapshot(client, db_sessionmaker):
    from starlette.requests import Request

    from api_trafix.routes import monitoring as monitoring_router

    from api_trafix.models.devices import Device
    from api_trafix.models.gates import Gate

    created = await client.post(
        "/gates/",
        json={"name": "SSE Gate", "gate_code": _suffix(), "type": "gate_in", "status": "online"},
    )
    gate_id = created.json()["id"]

    resp = await client.post(
        "/devices/",
        json={
            "gate_id": gate_id,
            "name": "SSE Controller",
            "type": "gate-controller",
            "ip_address": "10.0.0.99",
        },
    )
    device_id = resp.json()["id"]

    async def _receive():
        return {"type": "http.disconnect"}

    stream_app = FastAPI()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 0),
            "root_path": "",
            "http_version": "1.1",
            "app": stream_app,
            "path": "/api/monitoring/stream",
            "headers": [],
            "query_string": b"",
        },
        receive=_receive,
    )

    class FakePubSub:
        def __init__(self):
            self.unsubscribed = False
            self.closed = False

        async def get_message(self, ignore_subscribe_messages=True, timeout=None):
            return None

        async def unsubscribe(self, *channels):
            self.unsubscribed = True

        async def aclose(self):
            self.closed = True

    pubsub = FakePubSub()
    async with db_sessionmaker() as db:
        gen = monitoring_router._monitoring_stream_iter(request, db, pubsub)
        frame = await anext(gen)
        assert frame.startswith("event: snapshot")
        payload = json.loads(frame.split("data: ", 1)[1])
        assert "devices" in payload
        assert "mqtt" in payload
        assert any(i["id"] == device_id for i in payload["devices"]["items"])

        with pytest.raises(StopAsyncIteration):
            await anext(gen)

    # The dedicated pubsub connection must be released back to the pool,
    # otherwise every SSE client permanently leaks a pool slot.
    assert pubsub.unsubscribed
    assert pubsub.closed

    await _cleanup(db_sessionmaker, Device, device_id)
    await _cleanup(db_sessionmaker, Gate, gate_id)