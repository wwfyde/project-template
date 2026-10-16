"""Use the SDK's dependencies, settings and app-scoped connection pools."""

from threading import Lock

import redis_fastapi.config as sdk_config
from redis_fastapi import AsyncRedisDep, RedisSettings, get_async_redis
from redis_fastapi import get_settings as get_sdk_settings
from redis_fastapi.telemetry import disable_telemetry

from api.core import settings

__all__ = ["AsyncRedisDep", "configure_redis_sdk", "get_async_redis"]

_configuration_lock = Lock()


def configure_redis_sdk(*, telemetry_enabled: bool | None = None) -> RedisSettings:
    """Apply resolved project settings before the SDK lifespan starts.

    The SDK's singleton is process-wide. All apps in a process must use the
    same Redis configuration; connection pools remain scoped to each app.
    """
    if settings.redis is None:
        raise ValueError("Redis is not configured")
    if telemetry_enabled is None:
        telemetry_enabled = settings.otel.active

    configured = settings.redis.model_copy(deep=True)
    configured.otel_enabled = telemetry_enabled and configured.otel_enabled
    configured.otel_redis_enabled = telemetry_enabled and configured.otel_redis_enabled

    with _configuration_lock:
        # SDK 0.9 has no settings setter. Seed its existing cached getter with
        # the validated object, avoiding a second environment-only parse that
        # would reject valid combinations of TOML and environment settings.
        # Restore the constructor immediately; all SDK getter references and
        # the public RedisSettings class retain their original identity.
        if get_sdk_settings.cache_info().currsize:
            sdk_settings = get_sdk_settings()
        else:
            constructor = sdk_config.RedisSettings
            try:
                setattr(sdk_config, "RedisSettings", lambda: configured)
                sdk_settings = get_sdk_settings()
            finally:
                sdk_config.RedisSettings = constructor

        for name in RedisSettings.model_fields:
            setattr(sdk_settings, name, getattr(configured, name))
        sdk_settings.__pydantic_fields_set__ = configured.model_fields_set.copy()
        if not sdk_settings.otel_enabled:
            disable_telemetry()

    return sdk_settings
