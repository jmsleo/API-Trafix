from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from api_trafix.config.redis import (
    cache_delete_pattern,
    cache_get,
    cache_set,
)

T = TypeVar("T")


def _jsonable(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


async def get_or_set(
    key: str,
    factory: Callable[[], Awaitable[T]],
    ttl: int | None = None,
) -> T:
    cached = await cache_get(key)
    if cached is not None:
        return cached
    value = await factory()
    await cache_set(key, _jsonable(value), expire=ttl)
    return value


async def invalidate(pattern: str) -> None:
    await cache_delete_pattern(pattern)
