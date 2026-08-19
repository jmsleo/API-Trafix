import asyncio
import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo

from api_trafix.config.database import async_session_maker
from api_trafix.config.settings import get_settings
from api_trafix.crud import system_config as config_crud
from api_trafix.models import AuditLog
from api_trafix.services import backup as backup_service
from api_trafix.services import signage_broadcast, subscriptions
from sqlalchemy import delete as sa_delete

logger = logging.getLogger(__name__)

_BACKUP_SECTION = "auto_backup"
_AUDIT_CLEANUP_SECTION = "audit_cleanup"
_CHECK_INTERVAL = 30  # seconds between config re-reads while waiting for the run time


async def _run_auto_expire() -> None:
    async with async_session_maker() as db:
        count = await subscriptions.auto_expire(db)
        if count:
            logger.info("auto_expire: expired %d subscription(s)", count)


async def _run_signage_broadcast() -> None:
    async with async_session_maker() as db:
        changed = await signage_broadcast.sync_broadcast_windows(db)
        if changed:
            logger.info("signage_broadcast: flipped %d content(s)", changed)


async def _run_signage_sync(signage: Any) -> None:
    async with async_session_maker() as db:
        await signage.sync_from_db(db)


def _parse_hhmm(value: str) -> tuple[int, int]:
    """Parse "HH:MM" into (hour, minute); fall back to midnight on bad input."""
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (ValueError, AttributeError):
        return 0, 0
    if not (0 <= hour < 24 and 0 <= minute < 60):
        return 0, 0
    return hour, minute


def _next_run_dt(now: datetime.datetime, hour: int, minute: int) -> datetime.datetime:
    """Next occurrence of ``HH:MM`` (same day if still ahead, else tomorrow)."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += datetime.timedelta(days=1)
    return candidate


def _next_weekly_run(
    now: datetime.datetime, weekday: int, hour: int, minute: int
) -> datetime.datetime:
    """Next occurrence of weekday at ``HH:MM`` (same week if still ahead, else next week).

    ``weekday`` follows Python's convention: 0=Monday .. 6=Sunday.
    """
    days_ahead = (weekday - now.weekday()) % 7
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + datetime.timedelta(
        days=days_ahead
    )
    if candidate <= now:
        candidate += datetime.timedelta(days=7)
    return candidate


async def _run_audit_cleanup() -> None:
    """Delete every row from the audit log."""
    async with async_session_maker() as db:
        result = await db.execute(sa_delete(AuditLog))
        await db.commit()
        logger.info("audit_cleanup: deleted %d audit log row(s)", result.rowcount)


async def _effective_audit_cleanup_config() -> dict:
    """Audit-cleanup config: DB ``audit_cleanup`` section overrides env defaults."""
    base = get_settings()
    try:
        async with async_session_maker() as db:
            values = await config_crud.get_section(db, _AUDIT_CLEANUP_SECTION)
    except Exception:  # noqa: BLE001  (table missing / DB down: fall back to env)
        values = {}

    def _v(key: str, fallback):
        entry = values.get(key)
        return entry.get("value", fallback) if isinstance(entry, dict) else fallback

    return {
        "enabled": bool(_v("enabled", base.audit_cleanup_enabled)),
        "weekday": int(_v("weekday", base.audit_cleanup_weekday)),
        "time": str(_v("time", base.audit_cleanup_time)),
        "timezone": str(_v("timezone", base.audit_cleanup_timezone)),
    }


async def run_weekly_audit_cleanup_loop() -> None:
    """Delete all audit logs every configured weekday at the configured time
    (default: every Sunday 23:59 WIB).

    Re-reads the persisted ``audit_cleanup`` config every ``_CHECK_INTERVAL``
    seconds so an admin toggle from the web UI takes effect within seconds.
    """
    logger.info("audit_cleanup: scheduler started")
    while True:
        try:
            cfg = await _effective_audit_cleanup_config()
            enabled = cfg["enabled"]
        except Exception:  # noqa: BLE001  (DB unreachable: fall back to env)
            enabled = get_settings().audit_cleanup_enabled
            cfg = None

        if not enabled:
            await asyncio.sleep(_CHECK_INTERVAL)
            continue

        try:
            zone = ZoneInfo(cfg["timezone"])
        except Exception:  # noqa: BLE001  (bad zone config: fall back to WIB)
            zone = ZoneInfo("Asia/Jakarta")
        hour, minute = _parse_hhmm(cfg["time"])
        weekday = int(cfg["weekday"]) % 7
        now = datetime.datetime.now(zone)
        next_run = _next_weekly_run(now, weekday, hour, minute)
        logger.info("audit_cleanup: next run at %s", next_run.isoformat())

        skip_run = False
        while True:
            delay = (next_run - datetime.datetime.now(zone)).total_seconds()
            if delay <= 0:
                break
            await asyncio.sleep(min(_CHECK_INTERVAL, delay))
            try:
                if not (await _effective_audit_cleanup_config())["enabled"]:
                    logger.info("audit_cleanup: disabled while waiting, skipping this run")
                    skip_run = True
                    break
            except Exception:  # noqa: BLE001
                pass

        if skip_run:
            continue

        try:
            await _run_audit_cleanup()
        except Exception:  # noqa: BLE001  (a failed run must not kill the loop)
            logger.exception("audit_cleanup: run failed")


async def _effective_backup_config() -> dict:
    """Auto-backup config: DB ``auto_backup`` section overrides env defaults."""
    base = get_settings()
    try:
        async with async_session_maker() as db:
            values = await config_crud.get_section(db, _BACKUP_SECTION)
    except Exception:  # noqa: BLE001  (table missing / DB down: fall back to env)
        values = {}

    def _v(key: str, fallback):
        entry = values.get(key)
        return entry.get("value", fallback) if isinstance(entry, dict) else fallback

    return {
        "enabled": bool(_v("enabled", base.daily_backup_enabled)),
        "time": str(_v("time", base.daily_backup_time)),
        "timezone": str(_v("timezone", base.daily_backup_timezone)),
    }


async def run_daily_backup_loop() -> None:
    """Run a database backup once per day at the configured time (WIB by default).

    Re-reads the persisted ``auto_backup`` config every ``_CHECK_INTERVAL`` seconds
    so an admin toggle from the web UI takes effect within seconds.
    """
    logger.info("daily_backup: scheduler started")
    while True:
        try:
            cfg = await _effective_backup_config()
            enabled = cfg["enabled"]
        except Exception:  # noqa: BLE001  (DB unreachable: fall back to env)
            enabled = get_settings().daily_backup_enabled
            cfg = None

        if not enabled:
            await asyncio.sleep(_CHECK_INTERVAL)
            continue

        try:
            zone = ZoneInfo(cfg["timezone"])
        except Exception:  # noqa: BLE001  (bad zone config: fall back to WIB)
            zone = ZoneInfo("Asia/Jakarta")
        hour, minute = _parse_hhmm(cfg["time"])
        now = datetime.datetime.now(zone)
        next_run = _next_run_dt(now, hour, minute)
        logger.info("daily_backup: next run at %s", next_run.isoformat())

        skip_run = False
        while True:
            delay = (next_run - datetime.datetime.now(zone)).total_seconds()
            if delay <= 0:
                break
            await asyncio.sleep(min(_CHECK_INTERVAL, delay))
            try:
                if not (await _effective_backup_config())["enabled"]:
                    logger.info("daily_backup: disabled while waiting, skipping this run")
                    skip_run = True
                    break
            except Exception:  # noqa: BLE001
                pass

        if skip_run:
            continue

        try:
            await backup_service.run_daily_backup()
        except Exception:  # noqa: BLE001  (a failed run must not kill the loop)
            logger.exception("daily_backup: run failed")


async def run_periodic_tasks(signage: Any = None) -> None:
    settings = get_settings()
    loop = asyncio.get_running_loop()
    last_auto = last_broadcast = loop.time()
    last_signage = loop.time() if signage is not None else None
    step = min(
        settings.subscription_auto_expire_interval_seconds,
        settings.signage_sync_interval_seconds,
    )
    while True:
        try:
            now = loop.time()
            if now - last_auto >= settings.subscription_auto_expire_interval_seconds:
                await _run_auto_expire()
                last_auto = now
            if now - last_broadcast >= settings.subscription_auto_expire_interval_seconds:
                await _run_signage_broadcast()
                last_broadcast = now
            if signage is not None and now - last_signage >= settings.signage_sync_interval_seconds:
                await _run_signage_sync(signage)
                last_signage = now
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("periodic task failed")
        await asyncio.sleep(step)
