import asyncio
import logging

from api_trafix.config.database import async_session_maker
from api_trafix.config.settings import get_settings
from api_trafix.services import subscriptions

logger = logging.getLogger(__name__)


async def _run_auto_expire() -> None:
    async with async_session_maker() as db:
        count = await subscriptions.auto_expire(db)
        if count:
            logger.info("auto_expire: expired %d subscription(s)", count)


async def run_periodic_tasks() -> None:
    settings = get_settings()
    while True:
        try:
            await _run_auto_expire()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("periodic auto_expire failed")
        await asyncio.sleep(settings.subscription_auto_expire_interval_seconds)
