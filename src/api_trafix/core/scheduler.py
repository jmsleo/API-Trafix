import asyncio
import logging
from typing import Any

from api_trafix.config.database import async_session_maker
from api_trafix.config.settings import get_settings
from api_trafix.services import signage_broadcast, subscriptions

logger = logging.getLogger(__name__)


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
