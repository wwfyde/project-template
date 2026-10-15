"""Exercise SDK dependencies and real HTTP cache middleware without services."""

import json
import time
from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis_fastapi import (
    CacheBackend,
    FastAPIRedis,
    RateLimitResult,
    RedisSessionStore,
    get_async_redis,
    get_cache_backend,
    get_rate_limit_backend,
    get_session_store,
)

from api.deps import get_db
from api.routes.examples import cache

SDK_PREFIX = "/api/examples/cache/sdk"
CONVERSATION_ID = str(UUID(int=1))
MODEL_URL = f"{SDK_PREFIX}/cache-backend/conversations/{CONVERSATION_ID}"


class MemoryPipeline:
    """Only the GET + TTL pipeline used by the SDK response cache."""

    def __init__(self, redis: MemoryRedis) -> None:
        self.redis = redis
        self.commands: list[tuple[str, str]] = []

    def get(self, key: str) -> MemoryPipeline:
        self.commands.append(("get", key))
        return self

    def ttl(self, key: str) -> MemoryPipeline:
        self.commands.append(("ttl", key))
        return self

    async def execute(self) -> list[str | int | None]:
        results: list[str | int | None] = []
        for command, key in self.commands:
            if command == "get":
                results.append(await self.redis.get(key))
            else:
                results.append(await self.redis.ttl(key))
        return results


class MemoryRedis:
    """A small storage fake; the tested SDK still serializes and captures responses."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.unavailable = False

    def _check_available(self) -> None:
        if self.unavailable:
            raise RedisConnectionError("test Redis unavailable")

    async def get(self, key: str) -> str | None:
        self._check_available()
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> bool:
        self._check_available()
        self.values[key] = value
        self.ttls[key] = ex if ex is not None else -1
        return True

    async def delete(self, key: str) -> int:
        self._check_available()
        existed = key in self.values
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return int(existed)

    async def ttl(self, key: str) -> int:
        self._check_available()
        return self.ttls.get(key, -2)

    def pipeline(self) -> MemoryPipeline:
        return MemoryPipeline(self)


class MemoryLimiter:
    """Simulate limiter outcomes while retaining SDK identity, headers and rejection."""

    def __init__(self) -> None:
        self.counts: dict[tuple[str, str | None], int] = {}
        self.calls = 0
        self.degraded = False

    async def hit(
        self,
        identifier: str,
        *,
        limit: int,
        window: int,
        scope: str | None = None,
        cost: int = 1,
        fail_closed: bool | None = None,
    ) -> RateLimitResult:
        self.calls += 1
        key = identifier, scope
        count = self.counts.get(key, 0)
        allowed = not fail_closed if self.degraded else count + cost <= limit
        if allowed and not self.degraded:
            count += cost
            self.counts[key] = count
        return RateLimitResult(
            allowed=allowed,
            limit=limit,
            remaining=max(0, limit - count),
            reset_after=window,
            reset_at=int(time.time()) + window,
            retry_after=window,
            backend="" if self.degraded else "lua",
            degraded=self.degraded,
        )


def snapshot() -> dict[str, str | bool]:
    return {
        "id": CONVERSATION_ID,
        "title": "SDK cache lesson",
        "is_archived": False,
        "updated_at": "2026-10-15T00:00:00Z",
    }


@pytest.fixture
def redis() -> MemoryRedis:
    return MemoryRedis()


@pytest.fixture
def limiter() -> MemoryLimiter:
    return MemoryLimiter()


@pytest.fixture
def db() -> MagicMock:
    result = MagicMock()
    result.mappings.return_value.one_or_none.return_value = snapshot()
    return MagicMock(execute=AsyncMock(return_value=result))


@pytest.fixture
def client(
    monkeypatch: MonkeyPatch,
    redis: MemoryRedis,
    limiter: MemoryLimiter,
    db: MagicMock,
) -> Iterator[TestClient]:
    monkeypatch.setattr(cache.settings.app, "env", "local")
    monkeypatch.setattr(cache.settings, "repo_type", "postgres")
    app = FastAPI()
    FastAPIRedis(app).caching()
    cache.configure_sdk_examples(app)
    app.include_router(cache.cache_router, prefix="/api/examples")

    async def redis_override() -> MemoryRedis:
        return redis

    async def backend_override() -> CacheBackend:
        return CacheBackend(cast(Redis, redis))

    async def limiter_override() -> MemoryLimiter:
        return limiter

    async def db_override() -> MagicMock:
        return db

    # Unlike the cache/limiter backend factories, the session store factory
    # explicitly consults this override when called directly by middleware.
    async def session_store_override(request: Request) -> RedisSessionStore:
        return RedisSessionStore(cast(Redis, redis))

    app.dependency_overrides[get_async_redis] = redis_override
    app.dependency_overrides[get_cache_backend] = backend_override
    app.dependency_overrides[get_rate_limit_backend] = limiter_override
    app.dependency_overrides[get_session_store] = session_store_override
    app.dependency_overrides[get_db] = db_override
    with TestClient(app) as test_client:
        yield test_client


def test_http_cache_hit_refresh_and_eviction(
    client: TestClient, limiter: MemoryLimiter
) -> None:
    url = f"{SDK_PREFIX}/cache"
    first = client.get(url)
    second = client.get(url)
    assert first.status_code == second.status_code == 200
    assert first.headers["X-Redis-Cache"] == "MISS"
    assert second.headers["X-Redis-Cache"] == "HIT"
    assert first.json() == second.json()
    assert first.headers["X-RateLimit-Remaining"] == "4"
    assert second.headers["X-RateLimit-Remaining"] == "3"
    assert limiter.calls == 2

    refreshed = client.post(f"{url}/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["nonce"] != first.json()["nonce"]
    warm = client.get(url)
    assert warm.headers["X-Redis-Cache"] == "HIT"
    assert warm.json() == refreshed.json()

    evicted = client.delete(url)
    assert evicted.status_code == 204
    cold = client.get(url)
    assert cold.headers["X-Redis-Cache"] == "MISS"
    assert cold.json()["nonce"] != refreshed.json()["nonce"]


def test_warm_cache_does_not_bypass_rate_limit(client: TestClient) -> None:
    url = f"{SDK_PREFIX}/cache"
    for _ in range(5):
        assert client.get(url).status_code == 200
    blocked = client.get(url)
    assert blocked.status_code == 429
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert int(blocked.headers["Retry-After"]) > 0


def test_http_cache_supports_conditional_request(client: TestClient) -> None:
    first = client.get(f"{SDK_PREFIX}/cache")
    conditional = client.get(
        f"{SDK_PREFIX}/cache", headers={"If-None-Match": first.headers["ETag"]}
    )
    assert conditional.status_code == 304
    assert conditional.content == b""
    assert conditional.headers["X-Redis-Cache"] == "HIT"


def test_rate_limit_rejection_includes_retry_headers(client: TestClient) -> None:
    url = f"{SDK_PREFIX}/rate-limit"
    for _ in range(5):
        assert client.get(url).status_code == 200
    blocked = client.get(url)
    assert blocked.status_code == 429
    assert blocked.headers["X-RateLimit-Limit"] == "5"
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert int(blocked.headers["Retry-After"]) > 0


def test_rate_limit_outage_returns_503(
    client: TestClient, limiter: MemoryLimiter
) -> None:
    limiter.degraded = True
    response = client.get(f"{SDK_PREFIX}/rate-limit")
    assert response.status_code == 503
    assert int(response.headers["Retry-After"]) > 0


def test_backend_cache_serializes_projection_and_skips_second_query(
    client: TestClient, redis: MemoryRedis, db: MagicMock
) -> None:
    first = client.get(MODEL_URL)
    second = client.get(MODEL_URL)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json() == snapshot()
    db.execute.assert_awaited_once()
    assert len(redis.values) == 1
    assert json.loads(next(iter(redis.values.values()))) == snapshot()
    assert next(iter(redis.ttls.values())) == 60


def test_backend_delete_forces_database_reload(
    client: TestClient, db: MagicMock
) -> None:
    assert client.get(MODEL_URL).status_code == 200
    deleted = client.delete(MODEL_URL)
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert client.get(MODEL_URL).status_code == 200
    assert db.execute.await_count == 2


@pytest.mark.parametrize("raw", ["invalid-json", '{"title":"old schema"}'])
def test_backend_corrupt_value_is_reloaded_and_replaced(
    client: TestClient, redis: MemoryRedis, db: MagicMock, raw: str
) -> None:
    assert client.get(MODEL_URL).status_code == 200
    key = next(iter(redis.values))
    redis.values[key] = raw
    db.execute.reset_mock()

    response = client.get(MODEL_URL)
    assert response.status_code == 200
    assert response.json() == snapshot()
    db.execute.assert_awaited_once()
    assert json.loads(redis.values[key]) == snapshot()


def test_backend_outage_falls_back_to_database(
    client: TestClient, redis: MemoryRedis, db: MagicMock
) -> None:
    redis.unavailable = True
    response = client.get(MODEL_URL)
    assert response.status_code == 200
    assert response.json() == snapshot()
    db.execute.assert_awaited_once()


def test_database_failure_does_not_write_backend_cache(
    client: TestClient, redis: MemoryRedis, db: MagicMock
) -> None:
    db.execute.side_effect = RuntimeError("database unavailable")
    with pytest.raises(RuntimeError, match="database unavailable"):
        client.get(MODEL_URL)
    assert not redis.values


def test_prod_guard_applies_even_to_warm_sdk_cache(
    client: TestClient, monkeypatch: MonkeyPatch, limiter: MemoryLimiter
) -> None:
    assert client.get(f"{SDK_PREFIX}/cache").status_code == 200
    monkeypatch.setattr(cache.settings.app, "env", "prod")
    response = client.get(f"{SDK_PREFIX}/cache")
    assert response.status_code == 404
    assert limiter.calls == 1
