"""Tests for the daily scheduled backup feature."""

import asyncio
import datetime
import uuid

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from api_trafix.config.database import get_db
from api_trafix.config.settings import get_settings
from api_trafix.core import scheduler as sched
from api_trafix.core.dependencies import get_current_admin
from api_trafix.models.users import User, UserRole, UserStatus
from api_trafix.routes import audit_log as audit_router
from api_trafix.routes import backup


def test_parse_hhmm_valid():
    assert sched._parse_hhmm("00:00") == (0, 0)
    assert sched._parse_hhmm("23:59") == (23, 59)
    assert sched._parse_hhmm("07:30") == (7, 30)


def test_parse_hhmm_invalid_falls_back_to_midnight():
    assert sched._parse_hhmm("") == (0, 0)
    assert sched._parse_hhmm("24:00") == (0, 0)
    assert sched._parse_hhmm("12:99") == (0, 0)
    assert sched._parse_hhmm("junk") == (0, 0)
    assert sched._parse_hhmm(None) == (0, 0)


def test_next_run_dt_same_day_when_still_ahead():
    now = datetime.datetime(2026, 8, 19, 23, 30, tzinfo=datetime.timezone.utc)
    assert sched._next_run_dt(now, 0, 0) == datetime.datetime(
        2026, 8, 20, 0, 0, tzinfo=datetime.timezone.utc
    )


def test_next_run_dt_rolls_to_tomorrow_after_target():
    now = datetime.datetime(2026, 8, 19, 0, 1, tzinfo=datetime.timezone.utc)
    assert sched._next_run_dt(now, 0, 0) == datetime.datetime(
        2026, 8, 20, 0, 0, tzinfo=datetime.timezone.utc
    )


def test_next_run_dt_exact_match_rolls_to_tomorrow():
    now = datetime.datetime(2026, 8, 19, 0, 0, tzinfo=datetime.timezone.utc)
    assert sched._next_run_dt(now, 0, 0) == datetime.datetime(
        2026, 8, 20, 0, 0, tzinfo=datetime.timezone.utc
    )


def test_next_weekly_run_same_week_when_still_ahead():
    # 2026-08-19 is a Wednesday (weekday 2).
    now = datetime.datetime(2026, 8, 19, 10, 0, tzinfo=datetime.timezone.utc)
    assert sched._next_weekly_run(now, 6, 23, 59) == datetime.datetime(
        2026, 8, 23, 23, 59, tzinfo=datetime.timezone.utc
    )


def test_next_weekly_run_rolls_to_next_week_after_target():
    # Sunday 23:59 already passed -> next Sunday.
    now = datetime.datetime(2026, 8, 24, 0, 0, tzinfo=datetime.timezone.utc)
    assert sched._next_weekly_run(now, 6, 23, 59) == datetime.datetime(
        2026, 8, 30, 23, 59, tzinfo=datetime.timezone.utc
    )


def test_next_weekly_run_same_day_before_target():
    now = datetime.datetime(2026, 8, 23, 23, 58, tzinfo=datetime.timezone.utc)
    assert sched._next_weekly_run(now, 6, 23, 59) == datetime.datetime(
        2026, 8, 23, 23, 59, tzinfo=datetime.timezone.utc
    )


def _fake_clock_module(monkeypatch, start=None):
    """Patch ``sched.datetime`` with a controllable clock.

    ``now()`` returns the current fake time; ``timedelta`` delegates to the real
    stdlib implementation so the loop's arithmetic still works.
    """
    current = [
        start
        or datetime.datetime(2026, 8, 19, 23, 59, 0, tzinfo=datetime.timezone.utc)
    ]
    real_timedelta = datetime.timedelta

    class _FakeDateTimeType:
        @staticmethod
        def now(tz=None):
            return current[0]

    class _FakeMod:
        datetime = _FakeDateTimeType

        @staticmethod
        def timedelta(**kwargs):
            return real_timedelta(**kwargs)

    monkeypatch.setattr(sched, "datetime", _FakeMod)
    return current


async def _run_loop_with_clock(monkeypatch, cfg, advance_on_sleep, ticks=40):
    """Start the loop task; yield ``ticks`` times; cancel; return the loop task."""
    real_sleep = asyncio.sleep
    current = _fake_clock_module(monkeypatch)

    async def fake_sleep(delay):
        current[0] = current[0] + datetime.timedelta(seconds=delay)
        await real_sleep(0)

    async def fake_sleep_immediate(_delay):
        await real_sleep(0)

    async def fake_run():
        fired.append(True)

    monkeypatch.setattr(sched, "_effective_backup_config", cfg)
    monkeypatch.setattr(
        sched.asyncio, "sleep", fake_sleep if advance_on_sleep else fake_sleep_immediate
    )
    monkeypatch.setattr(sched.backup_service, "run_daily_backup", fake_run)

    task = asyncio.create_task(sched.run_daily_backup_loop())
    for _ in range(ticks):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    return task


async def test_run_daily_backup_loop_disabled_does_not_fire(monkeypatch):
    fired = []
    current = _fake_clock_module(monkeypatch)
    real_sleep = asyncio.sleep

    async def fake_sleep(_delay):
        current[0] = current[0] + datetime.timedelta(seconds=30)
        await real_sleep(0)

    async def fake_run():
        fired.append(True)

    async def disabled_cfg():
        return {"enabled": False, "time": "00:00", "timezone": "Asia/Jakarta"}

    monkeypatch.setattr(sched, "_effective_backup_config", disabled_cfg)
    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sched.backup_service, "run_daily_backup", fake_run)

    task = asyncio.create_task(sched.run_daily_backup_loop())
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fired == []


async def test_run_daily_backup_loop_fires_at_midnight(monkeypatch):
    fired = []
    current = _fake_clock_module(monkeypatch)
    real_sleep = asyncio.sleep

    async def fake_sleep(delay):
        current[0] = current[0] + datetime.timedelta(seconds=delay)
        await real_sleep(0)

    async def fake_run():
        fired.append(True)

    async def enabled_cfg():
        return {"enabled": True, "time": "00:00", "timezone": "Asia/Jakarta"}

    monkeypatch.setattr(sched, "_effective_backup_config", enabled_cfg)
    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sched.backup_service, "run_daily_backup", fake_run)

    task = asyncio.create_task(sched.run_daily_backup_loop())
    # Advance past midnight so the loop fires, then a few extra ticks.
    for _ in range(400):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fired, "daily backup should have been triggered at 00:00"


async def test_run_daily_backup_loop_skips_when_disabled_while_waiting(monkeypatch):
    fired = []
    current = _fake_clock_module(monkeypatch)
    real_sleep = asyncio.sleep
    flips = [False]

    async def fake_sleep(delay):
        current[0] = current[0] + datetime.timedelta(seconds=delay)
        await real_sleep(0)

    async def fake_run():
        fired.append(True)

    async def flaky_cfg():
        if flips[0]:
            return {"enabled": False, "time": "00:00", "timezone": "Asia/Jakarta"}
        flips[0] = True
        return {"enabled": True, "time": "00:00", "timezone": "Asia/Jakarta"}

    monkeypatch.setattr(sched, "_effective_backup_config", flaky_cfg)
    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sched.backup_service, "run_daily_backup", fake_run)

    task = asyncio.create_task(sched.run_daily_backup_loop())
    for _ in range(100):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fired == [], "backup must not run when disabled while waiting"


async def test_run_weekly_audit_cleanup_loop_disabled_does_not_clean(monkeypatch):
    cleaned = []
    real_sleep = asyncio.sleep

    async def fake_sleep(_delay):
        await real_sleep(0)

    async def fake_clean():
        cleaned.append(True)

    async def disabled_cfg():
        return {"enabled": False, "weekday": 6, "time": "23:59", "timezone": "Asia/Jakarta"}

    monkeypatch.setattr(sched, "_effective_audit_cleanup_config", disabled_cfg)
    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sched, "_run_audit_cleanup", fake_clean)

    task = asyncio.create_task(sched.run_weekly_audit_cleanup_loop())
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleaned == []


async def test_run_weekly_audit_cleanup_loop_fires_on_sunday(monkeypatch):
    cleaned = []
    real_sleep = asyncio.sleep
    # Sunday 2026-08-23 23:58 UTC (the target is 23:59).
    current = _fake_clock_module(
        monkeypatch,
        start=datetime.datetime(2026, 8, 23, 23, 58, 0, tzinfo=datetime.timezone.utc),
    )

    async def fake_sleep(delay):
        current[0] = current[0] + datetime.timedelta(seconds=delay)
        await real_sleep(0)

    async def fake_clean():
        cleaned.append(True)

    async def enabled_cfg():
        return {"enabled": True, "weekday": 6, "time": "23:59", "timezone": "Asia/Jakarta"}

    monkeypatch.setattr(sched, "_effective_audit_cleanup_config", enabled_cfg)
    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sched, "_run_audit_cleanup", fake_clean)

    task = asyncio.create_task(sched.run_weekly_audit_cleanup_loop())
    for _ in range(40):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleaned, "audit cleanup should have run on Sunday 23:59"


async def test_run_weekly_audit_cleanup_loop_skips_when_disabled_mid_wait(monkeypatch):
    cleaned = []
    real_sleep = asyncio.sleep
    current = _fake_clock_module(
        monkeypatch,
        start=datetime.datetime(2026, 8, 23, 23, 58, 0, tzinfo=datetime.timezone.utc),
    )
    flips = [False]

    async def fake_sleep(delay):
        current[0] = current[0] + datetime.timedelta(seconds=delay)
        await real_sleep(0)

    async def fake_clean():
        cleaned.append(True)

    async def flaky_cfg():
        if flips[0]:
            return {"enabled": False, "weekday": 6, "time": "23:59", "timezone": "Asia/Jakarta"}
        flips[0] = True
        return {"enabled": True, "weekday": 6, "time": "23:59", "timezone": "Asia/Jakarta"}

    monkeypatch.setattr(sched, "_effective_audit_cleanup_config", flaky_cfg)
    monkeypatch.setattr(sched.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(sched, "_run_audit_cleanup", fake_clean)

    task = asyncio.create_task(sched.run_weekly_audit_cleanup_loop())
    for _ in range(100):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cleaned == [], "audit cleanup must not run when disabled while waiting"


async def test_audit_cleanup_deletes_all_rows(db_sessionmaker, monkeypatch):
    from api_trafix.models import AuditLog

    # Point the cleanup at the test DB (its own async_session_maker targets the
    # runtime DATABASE_URL, i.e. the sim/dev database).
    monkeypatch.setattr(sched, "async_session_maker", db_sessionmaker)

    async with db_sessionmaker() as db:
        db.add(AuditLog(module="test", action="create", description="row-1"))
        db.add(AuditLog(module="test", action="create", description="row-2"))
        await db.commit()

    await sched._run_audit_cleanup()

    async with db_sessionmaker() as db:
        from sqlalchemy import select

        remaining = (await db.execute(select(AuditLog))).scalars().all()
        assert remaining == []


@pytest_asyncio.fixture(scope="session")
async def backup_admin_user(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(
            name="Route Test Admin",
            username=f"route-admin-{uuid.uuid4().hex[:8]}",
            password="unused",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest_asyncio.fixture
async def backup_client(db_sessionmaker, backup_admin_user):
    app = FastAPI()
    app.include_router(backup.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    async def override_auth():
        return backup_admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_auth

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_auto_backup_get_returns_env_defaults(backup_client):
    resp = await backup_client.get("/backups/auto-backup")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["time"] == "00:00"
    assert body["timezone"] == "Asia/Jakarta"


async def test_auto_backup_put_persists_and_returns(backup_client, db_sessionmaker):
    resp = await backup_client.put(
        "/backups/auto-backup",
        json={"enabled": False, "time": "03:15", "timezone": "Asia/Jakarta"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": False, "time": "03:15", "timezone": "Asia/Jakarta"}

    resp = await backup_client.get("/backups/auto-backup")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": False, "time": "03:15", "timezone": "Asia/Jakarta"}

    from sqlalchemy import delete

    from api_trafix.models.system_config import SystemConfig

    async with db_sessionmaker() as db:
        await db.execute(
            delete(SystemConfig).where(SystemConfig.section == "auto_backup")
        )
        await db.commit()


async def test_auto_backup_put_validates_time_and_timezone(backup_client):
    resp = await backup_client.put(
        "/backups/auto-backup",
        json={"enabled": True, "time": "25:99", "timezone": "Asia/Jakarta"},
    )
    assert resp.status_code == 422, resp.text

    resp = await backup_client.put(
        "/backups/auto-backup",
        json={"enabled": True, "time": "00:00", "timezone": "Not/AZone"},
    )
    assert resp.status_code == 422, resp.text


@pytest_asyncio.fixture
async def audit_cleanup_client(db_sessionmaker, backup_admin_user):
    app = FastAPI()
    app.include_router(audit_router.router)

    async def override_get_db():
        async with db_sessionmaker() as session:
            yield session

    async def override_auth():
        return backup_admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin] = override_auth

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _clear_audit_cleanup_section(db_sessionmaker):
    from sqlalchemy import delete

    from api_trafix.models.system_config import SystemConfig

    async with db_sessionmaker() as db:
        await db.execute(
            delete(SystemConfig).where(SystemConfig.section == "audit_cleanup")
        )
        await db.commit()


async def test_audit_cleanup_config_get_returns_env_defaults(audit_cleanup_client):
    resp = await audit_cleanup_client.get("/audit-logs/cleanup-config")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["weekday"] == 6
    assert body["time"] == "23:59"
    assert body["timezone"] == "Asia/Jakarta"


async def test_audit_cleanup_config_put_persists(
    audit_cleanup_client, db_sessionmaker
):
    try:
        resp = await audit_cleanup_client.put(
            "/audit-logs/cleanup-config",
            json={"enabled": False, "weekday": 0, "time": "03:15", "timezone": "Asia/Jakarta"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "enabled": False,
            "weekday": 0,
            "time": "03:15",
            "timezone": "Asia/Jakarta",
        }

        resp = await audit_cleanup_client.get("/audit-logs/cleanup-config")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "enabled": False,
            "weekday": 0,
            "time": "03:15",
            "timezone": "Asia/Jakarta",
        }
    finally:
        await _clear_audit_cleanup_section(db_sessionmaker)


async def test_audit_cleanup_config_put_validates(audit_cleanup_client):
    resp = await audit_cleanup_client.put(
        "/audit-logs/cleanup-config",
        json={"enabled": True, "weekday": 7, "time": "23:59", "timezone": "Asia/Jakarta"},
    )
    assert resp.status_code == 422, resp.text

    resp = await audit_cleanup_client.put(
        "/audit-logs/cleanup-config",
        json={"enabled": True, "weekday": 6, "time": "bad", "timezone": "Asia/Jakarta"},
    )
    assert resp.status_code == 422, resp.text

    resp = await audit_cleanup_client.put(
        "/audit-logs/cleanup-config",
        json={"enabled": True, "weekday": 6, "time": "23:59", "timezone": "Nope/Ah"},
    )
    assert resp.status_code == 422, resp.text