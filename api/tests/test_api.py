from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis_fastapi import get_async_redis

from api import __version__
from api.main import create_app


@asynccontextmanager
async def no_services_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.mark.parametrize(
    ("redis_available", "postgres_available"),
    [(True, True), (False, True), (True, False), (False, False)],
)
def test_health_checks_both_dependencies(
    monkeypatch: MonkeyPatch, redis_available: bool, postgres_available: bool
) -> None:
    redis = AsyncMock()
    redis.ping.side_effect = None if redis_available else ConnectionError("unavailable")
    redis.ping.return_value = True
    connection = AsyncMock()
    connection.execute.side_effect = (
        None if postgres_available else ConnectionError("unavailable")
    )
    connection_context = MagicMock()
    connection_context.__aenter__ = AsyncMock(return_value=connection)
    connection_context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "api.main.engine", MagicMock(connect=MagicMock(return_value=connection_context))
    )

    async def redis_override() -> AsyncMock:
        return redis

    app = create_app(lifespan=no_services_lifespan)
    app.dependency_overrides[get_async_redis] = redis_override
    with TestClient(app) as client:
        response = client.get("/api/health")

    healthy = redis_available and postgres_available
    assert response.status_code == (200 if healthy else 503)
    assert response.json() == {
        "status": "ok" if healthy else "unavailable",
        "redis": {"client": "AsyncMock", "pong": redis_available},
        "postgres": {"connected": postgres_available},
        "version": __version__,
    }
    redis.ping.assert_awaited_once()
    connection.execute.assert_awaited_once()
    assert str(connection.execute.call_args.args[0]) == "SELECT 1"


def test_production_disables_configuration_and_docs() -> None:
    app = create_app(lifespan=no_services_lifespan)
    with TestClient(app) as client:
        assert client.get("/api/config").status_code == 404
        assert client.get("/docs").status_code == 404
