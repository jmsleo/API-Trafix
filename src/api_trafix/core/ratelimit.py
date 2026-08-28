import logging

import redis.exceptions
from fastapi import HTTPException, Request, status

from api_trafix.config.redis import get_redis
from api_trafix.config.settings import get_settings

log = logging.getLogger(__name__)

RATE_LIMITED = HTTPException(
    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    detail="Terlalu banyak percobaan login. Silakan coba lagi nanti.",
)


def _client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host


async def _count_and_limit(r, key: str, max_count: int, window_seconds: int) -> bool:
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, window_seconds)
    return count > max_count


async def enforce_login_throttle(request: Request, username: str) -> None:
    settings = get_settings()
    r = await get_redis()

    try:
        if await r.get(f"login_lock:{username.lower()}") is not None:
            raise RATE_LIMITED

        over_ip = await _count_and_limit(
            r,
            f"login_ip:{_client_ip(request)}",
            settings.login_ip_rate_limit,
            60,
        )
        if over_ip:
            raise RATE_LIMITED
    except (redis.exceptions.RedisError, OSError) as exc:
        # Throttling is best-effort: a Redis outage or an exhausted pool must
        # not turn /auth/login into a 500. Fail open and let credential
        # verification proceed unthrottled.
        log.warning("login throttle unavailable, failing open: %s", exc)


async def record_failed_login(username: str) -> None:
    settings = get_settings()
    r = await get_redis()
    try:
        key = f"login_fail:{username.lower()}"
        count = await r.incr(key)
        if count == 1:
            await r.expire(key, settings.login_lockout_seconds)
        if count > settings.login_max_attempts:
            await r.delete(key)
            await r.setex(f"login_lock:{username.lower()}", settings.login_lockout_seconds, "1")
            raise RATE_LIMITED
    except (redis.exceptions.RedisError, OSError) as exc:
        log.warning("failed-login counter unavailable, failing open: %s", exc)


async def clear_login_throttle(username: str) -> None:
    r = await get_redis()
    key = username.lower()
    try:
        await r.delete(f"login_lock:{key}", f"login_fail:{key}")
    except (redis.exceptions.RedisError, OSError) as exc:
        log.warning("could not clear login throttle state: %s", exc)
