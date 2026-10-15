import asyncio
from functools import lru_cache
from typing import Annotated, Any

import redis.asyncio as redis
from fastapi import Depends
from redis.asyncio.cluster import RedisCluster
from redis_fastapi import get_settings

from api.core import settings

RedisClient = redis.Redis | RedisCluster


def _connection_kwargs() -> dict[str, Any]:
    config = get_settings()
    kwargs: dict[str, Any] = {
        "decode_responses": True,
        "protocol": 3,
        "health_check_interval": 2,
    }
    if config.max_connections is not None:
        if config.max_connections < 1:
            raise ValueError("Redis max_connections must be positive")
        kwargs["max_connections"] = config.max_connections
    if not config.url:
        kwargs.update(host=config.host, port=config.port, db=config.db or 0)
        if config.password is not None:
            kwargs["password"] = config.password.get_secret_value()
    return kwargs


@lru_cache(maxsize=1)
def get_redis_pool() -> redis.ConnectionPool:
    """Return the shared standalone pool; Cluster owns its per-node pools."""
    config = get_settings()
    return redis.ConnectionPool.from_url(
        settings.redis_dsn,
        decode_responses=True,
        protocol=3,
    )


@lru_cache(maxsize=1)
def get_redis_client() -> RedisClient:
    """Create once on the application's event loop; prefer AsyncRedisDep in routes."""
    return redis.Redis(
        connection_pool=get_redis_pool(),
        decode_responses=True,
        protocol=3,
    )


async def get_async_redis() -> RedisClient:
    """Resolve on the event loop, not FastAPI's sync dependency thread pool."""
    return get_redis_client()


AsyncRedisDep = Annotated[RedisClient, Depends(get_async_redis)]


async def close_redis_cache() -> None:
    """Close existing resources without creating any during an unused shutdown."""
    client = get_redis_client() if get_redis_client.cache_info().currsize else None
    pool = get_redis_pool() if get_redis_pool.cache_info().currsize else None
    get_redis_client.cache_clear()
    get_redis_pool.cache_clear()
    try:
        if client is not None:
            await client.aclose()
    finally:
        # A Redis client with an externally supplied pool does not own that pool.
        if pool is not None:
            await pool.aclose()


async def main() -> None:
    redis_client = get_redis_client()

    # 不建议这样写
    async with await redis_client as r:
        await r.set("a", 60, 222)
        print(await r.get("a"))

    async with await redis_client as r:
        print(await r.get("a"))

    async with await redis_client as r:
        print(await r.get("a"))

    print(await redis_client.get("a"))


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
