"""Opt-in SDK lifecycle tests against disposable Redis >=7.4.

TEST_AUTH_REDIS_URL=redis://127.0.0.1:16389/0 uv run --no-sync pytest
api/tests/test_auth_redis_integration.py -q
Only keys under a random test prefix are created/deleted; never FLUSHDB.
"""

import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis_fastapi.session_backend import RedisSessionStore, SessionState

REDIS_URL = os.getenv("TEST_AUTH_REDIS_URL")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not REDIS_URL, reason="Set TEST_AUTH_REDIS_URL to an isolated Redis >=7.4"
    ),
]


async def test_real_redis_rotation_revocation_and_idle_expiration() -> None:
    prefix = f"test:auth:{uuid4().hex}"
    async with Redis.from_url(REDIS_URL) as redis:
        store = RedisSessionStore(redis, key_prefix=prefix, idle_ttl=1, absolute_ttl=10)
        try:
            state = SessionState(data={"user_id": "user-a", "tenant_id": "tenant-a"})
            old_id = await store.rotate(state, subject="user-a")
            assert (await store.load(old_id)).record.data["user_id"] == "user-a"
            new_id = await store.rotate(state, subject="user-a")
            assert new_id != old_id
            assert await store.load(old_id) is None
            assert await store.load(new_id) is not None
            await store.revoke(state)
            assert await store.load(new_id) is None
            idle = SessionState(data={"user_id": "user-a"})
            idle_id = await store.rotate(idle, subject="user-a")
            await asyncio.sleep(1.2)
            assert await store.load(idle_id) is None
        finally:
            keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
            if keys:
                await redis.delete(*keys)


async def test_real_redis_refresh_never_extends_absolute_deadline() -> None:
    prefix = f"test:auth:{uuid4().hex}"
    async with Redis.from_url(REDIS_URL) as redis:
        store = RedisSessionStore(redis, key_prefix=prefix, idle_ttl=2, absolute_ttl=3)
        try:
            state = SessionState(data={"user_id": "user-a"})
            session_id = await store.rotate(state, subject="user-a")
            for _ in range(4):
                await asyncio.sleep(0.5)
                assert await store.load(session_id, refresh=True) is not None
            await asyncio.sleep(1.2)
            assert await store.load(session_id, refresh=True) is None
        finally:
            keys = [key async for key in redis.scan_iter(match=f"{prefix}:*")]
            if keys:
                await redis.delete(*keys)
