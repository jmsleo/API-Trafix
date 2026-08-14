import asyncio
import logging

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


async def run_periodic_tasks() -> None:
    settings = get_settings()
    while True:
        try:
            await _run_auto_expire()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("periodic auto_expire failed")
        try:
            await _run_signage_broadcast()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("periodic signage_broadcast failed")
        await asyncio.sleep(settings.subscription_auto_expire_interval_seconds)
