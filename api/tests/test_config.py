import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch
from redis_fastapi import RedisSettings
from sqlalchemy.engine import make_url

from api.core.config import RedisConfig, Settings


def configure_database(monkeypatch: MonkeyPatch) -> None:
    for name, value in {
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USERNAME": "api",
        "POSTGRES_PASSWORD": "test-only-password",
        "POSTGRES_DATABASE": "api",
    }.items():
        monkeypatch.setenv(name, value)


def test_environment_only_settings(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    configure_database(monkeypatch)
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("APP_DEBUG", "false")
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_PASSWORD", "redis-password")

    settings = Settings(_env_file=None)

    assert settings.app.env == "prod"
    assert settings.app.debug is False
    assert settings.postgres.host == "postgres"
    assert settings.redis is not None
    assert settings.redis.host == "redis"
    assert settings.redis.password.get_secret_value() == "redis-password"
    assert settings.providers.model_dump(exclude_none=True) == {}
    assert settings.proxy_url is None


def test_environment_overrides_toml(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    configure_database(monkeypatch)
    (tmp_path / "config.toml").write_text(
        '[postgres]\nhost = "local-database"\n', encoding="utf-8"
    )

    settings = Settings(_env_file=None)

    assert settings.postgres.host == "postgres"


def test_connection_passwords_are_url_encoded(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_database(monkeypatch)
    password = "p@ss:/?#%$ with spaces"
    monkeypatch.setenv("POSTGRES_PASSWORD", password)
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_PASSWORD", password)

    settings = Settings(_env_file=None)

    assert make_url(settings.postgres_dsn).password == password
    assert unquote(urlparse(settings.redis_dsn).password) == password


def test_redis_url_takes_precedence(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    configure_database(monkeypatch)
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6379")
    monkeypatch.setenv("REDIS_URL", "redis://cache.example:6379/2")

    with pytest.warns(UserWarning, match="KV fields are ignored"):
        assert Settings(_env_file=None).redis_dsn == "redis://cache.example:6379/2"


@pytest.mark.parametrize("source", ["environment", "dotenv", "toml"])
def test_sentinel_settings_sources(
    monkeypatch: MonkeyPatch, tmp_path: Path, source: str
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_database(monkeypatch)
    for name in list(os.environ):
        if name.startswith("REDIS_") or name == "REDIS":
            monkeypatch.delenv(name)
    values = {
        "sentinel": True,
        "cluster": False,
        "sentinel_nodes": ["sentinel-a", "sentinel-b:26380", "sentinel-c:26379"],
        "sentinel_master_name": "cache-primary",
        "sentinel_username": "sentinel-user",
        "sentinel_password": "sentinel-secret",
        "password": "data-secret",
    }
    if source == "toml":
        (tmp_path / "config.toml").write_text(
            "[redis]\n"
            + "\n".join(
                f"{key} = {json.dumps(value)}" for key, value in values.items()
            ),
            encoding="utf-8",
        )
    else:
        environment = {
            f"REDIS_{key.upper()}": ",".join(value)
            if isinstance(value, list)
            else json.dumps(value)
            if not isinstance(value, str)
            else value
            for key, value in values.items()
        }
        if source == "environment":
            for key, value in environment.items():
                monkeypatch.setenv(key, value)
        else:
            (tmp_path / ".env").write_text(
                "\n".join(f"{key}={value}" for key, value in environment.items()),
                encoding="utf-8",
            )

    settings = Settings()

    assert settings.redis is not None
    assert settings.redis.sentinel is True
    assert settings.redis.cluster is False
    assert settings.redis.sentinel_master_name == "cache-primary"
    assert settings.redis.sentinel_addresses() == [
        ("sentinel-a", 26379),
        ("sentinel-b", 26380),
        ("sentinel-c", 26379),
    ]
    assert settings.redis.sentinel_username == "sentinel-user"
    assert settings.redis.sentinel_password.get_secret_value() == "sentinel-secret"
    assert settings.redis.password.get_secret_value() == "data-secret"
    assert settings.redis_dsn == ""  # Sentinel has no single connection URL.
    assert "sentinel-secret" not in settings.redis.model_dump_json()
    assert "data-secret" not in settings.redis.model_dump_json()


def test_redis_configuration_uses_sdk_defaults() -> None:
    config = RedisConfig(
        sentinel=True,
        sentinel_nodes=["sentinel-a", "sentinel-b:26380"],
    )

    assert isinstance(config, RedisSettings)
    assert config.sentinel_master_name == "mymaster"
    assert config.sentinel_addresses() == [
        ("sentinel-a", 26379),
        ("sentinel-b", 26380),
    ]


@pytest.mark.parametrize(
    "node",
    [
        "",
        ":26379",
        "host:",
        "host:0",
        "host:65536",
        "host:abc",
    ],
)
def test_invalid_sentinel_addresses_are_rejected(node: str) -> None:
    with pytest.raises(ValidationError):
        RedisConfig(sentinel=True, sentinel_nodes=[node])


def test_conflicting_redis_modes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="mutually exclusive"):
        RedisConfig(sentinel=True, cluster=True, sentinel_nodes=["sentinel-a"])
    with pytest.raises(ValidationError, match="not supported in sentinel mode"):
        RedisConfig(
            sentinel=True, sentinel_nodes=["sentinel-a"], url="redis://old-host"
        )
    with pytest.raises(ValidationError, match="at least one"):
        RedisConfig(sentinel=True)
    with pytest.raises(ValidationError):
        RedisConfig(
            sentinel=True, sentinel_nodes=["sentinel-a"], sentinel_master_name=""
        )


def test_url_only_redis_configuration() -> None:
    assert (
        RedisConfig(url="redis://cache.example:6379/2").url
        == "redis://cache.example:6379/2"
    )


def test_redis_config_does_not_reload_environment(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REDIS_HOST", "environment-host")
    (tmp_path / ".env").write_text("REDIS_HOST=dotenv-host\n", encoding="utf-8")

    assert RedisConfig().host == "localhost"
    assert RedisConfig(host="resolved-host").host == "resolved-host"


@pytest.mark.parametrize("source", ["environment", "dotenv", "toml"])
def test_redis_telemetry_configuration_sources(
    monkeypatch: MonkeyPatch, tmp_path: Path, source: str
) -> None:
    monkeypatch.chdir(tmp_path)
    configure_database(monkeypatch)
    for name in list(os.environ):
        if name.startswith("REDIS_") or name == "REDIS":
            monkeypatch.delenv(name)
    if source == "environment":
        monkeypatch.setenv("REDIS_OTEL_ENABLED", "true")
        monkeypatch.setenv("REDIS_OTEL_REDIS_ENABLED", "true")
    elif source == "dotenv":
        (tmp_path / ".env").write_text(
            "REDIS_OTEL_ENABLED=true\nREDIS_OTEL_REDIS_ENABLED=true\n",
            encoding="utf-8",
        )
    else:
        (tmp_path / "config.toml").write_text(
            "[redis]\notel_enabled = true\notel_redis_enabled = true\n",
            encoding="utf-8",
        )

    configured = Settings()

    assert configured.redis.otel_enabled is True
    assert configured.redis.otel_redis_enabled is True
