import json
from typing import Optional

import redis.asyncio as redis

from api_trafix.config.settings import get_settings

redis_client: Optional[redis.Redis] = None

settings = get_settings()

async def get_redis() -> redis.Redis:
    global redis_client
    if redis_client is None:
        redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=settings.redis_max_connections,
        )
    return redis_client


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


async def cache_set(key: str, value: dict, expire: int | None = None):
    r = await get_redis()
    expire = expire or settings.redis_cache_expire
    await r.setex(key, expire, json.dumps(value, default=str))


async def cache_get(key: str) -> Optional[dict]:
    r = await get_redis()
    data = await r.get(key)
    if data:
        return json.loads(data)
    return None


async def cache_delete(key:str):
    r = await get_redis()
    await r.delete(key)


async def cache_delete_pattern(pattern: str):
    r = await get_redis()
    cursor = 0
    while True:
        cursor, keys = await r.scan(cursor=cursor, match=pattern, count=100)
        if keys:
            await r.delete(*keys)
        if cursor == 0:
            break


async def session_set(token: str, user_data: dict, expire: int | None = None):
    r = await get_redis()
    expire = expire or settings.redis_session_expire
    await r.setex(f"session:{token}", expire, json.dumps(user_data, default=str))
    

async def session_get(token: str) -> Optional[dict]:
    r = await get_redis()
    data = await r.get(f"session:{token}")
    if data:
        return json.loads(data)
    return None

async def session_delete(token: str):
    r = await get_redis()
    await r.delete(f"session:{token}")