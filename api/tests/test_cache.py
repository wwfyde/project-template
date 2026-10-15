import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pytest import MonkeyPatch
from redis.asyncio import Redis
from redis.asyncio.cluster import RedisCluster
from redis.asyncio.connection import AbstractConnection, SSLConnection
from redis.asyncio.sentinel import SentinelConnectionPool, SentinelManagedSSLConnection
from redis_fastapi import AsyncRedisDep, get_async_redis
from redis_fastapi import get_settings as get_sdk_settings

from api.core import cache
from api.core.config import RedisConfig, Settings
from api.core.lifespan import lifespan


@pytest.fixture(autouse=True)
def isolated_redis(monkeypatch: MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name.startswith(("REDIS_", "POSTGRES_")) or name == "REDIS":
            monkeypatch.delenv(name)
    for name, value in {
        "POSTGRES_HOST": "postgres.example",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USERNAME": "test-user",
        "POSTGRES_PASSWORD": "test-password",
        "POSTGRES_DATABASE": "test-db",
        "PROVIDERS": "{}",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cache.settings, "redis", RedisConfig())
    monkeypatch.setattr(
        AbstractConnection,
        "connect_check_health",
        AsyncMock(side_effect=AssertionError("Redis unit tests must not connect")),
    )
    monkeypatch.setattr("api.core.lifespan.engine", AsyncMock())
    get_sdk_settings.cache_clear()
    try:
        yield
    finally:
        get_sdk_settings.cache_clear()


def test_dependencies_are_the_sdk_dependencies() -> None:
    from api.main import AsyncRedisDep as AppRedisDep

    assert cache.AsyncRedisDep is AsyncRedisDep
    assert AppRedisDep is AsyncRedisDep
    assert cache.get_async_redis is get_async_redis


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["standalone", "cluster", "sentinel"])
async def test_application_lifespan_uses_sdk_clients_and_closes_resources(
    monkeypatch: MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(
        cache.settings,
        "redis",
        RedisConfig(
            host="data.example",
            port=6380,
            username="data-user",
            password=SecretStr("test-data-password"),
            cluster=mode == "cluster",
            sentinel=mode == "sentinel",
            sentinel_nodes=["sentinel-a:26379", "sentinel-b:26379", "sentinel-c:26379"]
            if mode == "sentinel"
            else [],
            sentinel_master_name="orders",
            sentinel_username="sentinel-user",
            sentinel_password=SecretStr("test-sentinel-password"),
        ),
    )
    app = FastAPI(lifespan=lifespan)
    request = Request({"type": "http", "app": app})
    resource_closers = []

    async with app.router.lifespan_context(app):
        client = await get_async_redis(request)
        assert await get_async_redis(request) is client
        if mode == "cluster":
            assert isinstance(client, RedisCluster)
            assert (client.startup_nodes[0].host, client.startup_nodes[0].port) == (
                "data.example",
                6380,
            )
            kwargs = client.connection_kwargs
            closer = AsyncMock(wraps=client.aclose)
            monkeypatch.setattr(RedisCluster, "aclose", closer)
        else:
            assert isinstance(client, Redis)
            pool = client.connection_pool
            kwargs = pool.connection_kwargs
            closer = AsyncMock(wraps=pool.aclose)
            monkeypatch.setattr(pool, "aclose", closer)
            assert pool.get_encoder().decode_responses is False
            if mode == "sentinel":
                assert isinstance(pool, SentinelConnectionPool)
                assert pool.service_name == "orders"
                for node in pool.sentinel_manager.sentinels:
                    node_kwargs = node.connection_pool.connection_kwargs
                    assert node_kwargs["username"] == "sentinel-user"
                    assert node_kwargs["password"] == "test-sentinel-password"
                    close_node = AsyncMock(wraps=node.connection_pool.aclose)
                    monkeypatch.setattr(node.connection_pool, "aclose", close_node)
                    resource_closers.append(close_node)
                assert len(resource_closers) == 3
            else:
                assert not isinstance(pool, SentinelConnectionPool)
                assert (kwargs["host"], kwargs["port"]) == ("data.example", 6380)
        assert kwargs["username"] == "data-user"
        assert kwargs["password"] == "test-data-password"
        assert kwargs["socket_connect_timeout"] == 5
        assert kwargs["socket_timeout"] == 5
        resource_closers.append(closer)

    for close_resource in resource_closers:
        close_resource.assert_awaited_once()
    with pytest.raises(RuntimeError):
        await get_async_redis(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["standalone", "cluster", "sentinel"])
async def test_application_configuration_enables_sdk_tls(
    monkeypatch: MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(
        cache.settings,
        "redis",
        RedisConfig(
            ssl=mode != "cluster",
            url="rediss://cluster.example:6380/0" if mode == "cluster" else None,
            cluster=mode == "cluster",
            sentinel=mode == "sentinel",
            sentinel_nodes=["sentinel.example:26379"] if mode == "sentinel" else [],
        ),
    )
    app = FastAPI(lifespan=lifespan)

    async with app.router.lifespan_context(app):
        client = await get_async_redis(Request({"type": "http", "app": app}))
        if isinstance(client, RedisCluster):
            assert client.connection_kwargs["connection_class"] is SSLConnection
        else:
            expected = (
                SentinelManagedSSLConnection if mode == "sentinel" else SSLConnection
            )
            assert client.connection_pool.connection_class is expected
            # This catches unsupported TLS kwargs without connecting to Redis.
            client.connection_pool.make_connection()


@pytest.mark.asyncio
async def test_apps_with_same_configuration_have_independent_pools() -> None:
    first = FastAPI(lifespan=lifespan)
    second = FastAPI(lifespan=lifespan)

    async with (
        first.router.lifespan_context(first),
        second.router.lifespan_context(second),
    ):
        first_client = await get_async_redis(Request({"type": "http", "app": first}))
        second_client = await get_async_redis(Request({"type": "http", "app": second}))

        assert first_client is not second_client
        assert first_client.connection_pool is not second_client.connection_pool


def test_configuration_bridge_replaces_stale_sdk_settings(
    monkeypatch: MonkeyPatch,
) -> None:
    sdk = get_sdk_settings()
    sdk.cluster = True
    sdk.host = "old.example"
    sdk.password = SecretStr("old-test-password")
    sdk.prefix = "old-prefix"
    monkeypatch.setattr(
        cache.settings,
        "redis",
        RedisConfig(host="current.example", prefix="current-prefix"),
    )

    configured = cache.configure_redis_sdk()

    assert configured is sdk
    assert configured.cluster is False
    assert configured.host == "current.example"
    assert configured.password is None
    assert configured.prefix == "current-prefix"
    assert "REDIS_SENTINEL" not in os.environ


def test_configuration_bridge_combines_sentinel_environment_and_toml(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REDIS_SENTINEL", "true")
    (tmp_path / "config.toml").write_text(
        '[redis]\nsentinel_nodes = ["sentinel.example:26379"]\n'
        'sentinel_master_name = "orders"\n',
        encoding="utf-8",
    )
    project_settings = Settings(_env_file=None)
    monkeypatch.setattr(cache.settings, "redis", project_settings.redis)
    assert get_sdk_settings.cache_info().currsize == 0

    configured = cache.configure_redis_sdk()

    assert configured.sentinel is True
    assert configured.sentinel_nodes == ["sentinel.example:26379"]
    assert configured.sentinel_master_name == "orders"
    assert os.environ["REDIS_SENTINEL"] == "true"


@pytest.mark.parametrize("mode", ["standalone", "cluster", "sentinel"])
def test_route_dependency_uses_toml_without_redis_environment(
    monkeypatch: MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    from api.main import create_app

    (tmp_path / "config.toml").write_text(
        "[redis]\n"
        'host = "toml-data.example"\n'
        "port = 6381\n"
        'username = "toml-data-user"\n'
        'password = "toml-data-password"\n'
        f"db = {0 if mode == 'cluster' else 4}\n"
        f"cluster = {str(mode == 'cluster').lower()}\n"
        f"sentinel = {str(mode == 'sentinel').lower()}\n"
        'sentinel_nodes = ["toml-sentinel-a", "toml-sentinel-b:26380"]\n'
        'sentinel_master_name = "toml-primary"\n'
        'sentinel_username = "toml-sentinel-user"\n'
        'sentinel_password = "toml-sentinel-password"\n',
        encoding="utf-8",
    )
    assert not any(name.startswith("REDIS_") for name in os.environ)
    # Load the real project settings source, then run the real app lifespan and
    # FastAPI dependency resolver. Neither the SDK getter nor DI is overridden.
    project_settings = Settings(_env_file=None)
    monkeypatch.setattr(cache.settings, "redis", project_settings.redis)
    assert get_sdk_settings().host == "localhost"
    app = create_app()

    @app.get("/redis-configuration-test")
    async def inspect_redis(redis: AsyncRedisDep) -> dict[str, str]:
        if isinstance(redis, RedisCluster):
            kwargs = redis.connection_kwargs
            assert (redis.startup_nodes[0].host, redis.startup_nodes[0].port) == (
                "toml-data.example",
                6381,
            )
            actual_mode = "cluster"
        else:
            pool = redis.connection_pool
            kwargs = pool.connection_kwargs
            assert kwargs["db"] == 4
            if isinstance(pool, SentinelConnectionPool):
                assert pool.service_name == "toml-primary"
                nodes = pool.sentinel_manager.sentinels
                assert [
                    (
                        node.connection_pool.connection_kwargs["host"],
                        node.connection_pool.connection_kwargs["port"],
                    )
                    for node in nodes
                ] == [("toml-sentinel-a", 26379), ("toml-sentinel-b", 26380)]
                for node in nodes:
                    auth = node.connection_pool.connection_kwargs
                    assert auth["username"] == "toml-sentinel-user"
                    assert auth["password"] == "toml-sentinel-password"
                actual_mode = "sentinel"
            else:
                assert (kwargs["host"], kwargs["port"]) == ("toml-data.example", 6381)
                actual_mode = "standalone"
        assert kwargs["username"] == "toml-data-user"
        assert kwargs["password"] == "toml-data-password"
        return {"mode": actual_mode}

    with TestClient(app) as client:
        response = client.get("/redis-configuration-test")

    assert response.status_code == 200
    assert response.json() == {"mode": mode}
    assert "REDIS_SENTINEL" not in os.environ


@pytest.mark.asyncio
async def test_missing_redis_configuration_fails_before_sdk_initialization(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cache.settings, "redis", None)
    app = FastAPI(lifespan=lifespan)

    with pytest.raises(ValueError, match="not configured"):
        async with app.router.lifespan_context(app):
            pytest.fail("Application must reject missing Redis configuration")

    assert get_sdk_settings.cache_info().currsize == 0
    assert not hasattr(app.state, "_redis")
