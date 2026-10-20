"""Password repository dependency and shared authentication rate limiting."""

import hashlib
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from redis.exceptions import RedisError
from redis_fastapi import AsyncRedisDep

from api.core.db import AsyncSessionLocal
from api.deps import SettingsDep
from api.repositories.password import PasswordRepository, normalize_username

_ATTEMPT_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
    ttl = tonumber(ARGV[1])
end
return {count, ttl}
"""


def get_password_repository() -> PasswordRepository:
    return PasswordRepository(AsyncSessionLocal)


PasswordRepositoryDep = Annotated[PasswordRepository, Depends(get_password_repository)]


async def limit_password_attempts(
    request: Request, username: str, redis: AsyncRedisDep, settings: SettingsDep
) -> None:
    config = settings.auth.password
    try:
        normalized = normalize_username(username)
    except ValueError:
        normalized = username.strip().lower()
    client = request.client.host if request.client is not None else "unknown"
    # Independent single-key scripts work with standalone, Sentinel and Cluster.
    # Never use caller-supplied X-Forwarded-For as an independent identity source.
    for kind, value, limit in (
        ("client", client, config.ip_rate_limit_attempts),
        ("username", normalized, config.rate_limit_attempts),
    ):
        digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
        key = f"{settings.auth.session_key_prefix}:{settings.app.env}:password:{kind}:{digest}"
        try:
            count, remaining = await redis.eval(
                _ATTEMPT_SCRIPT, 1, key, config.rate_limit_window_seconds
            )
        except RedisError as exc:
            raise HTTPException(503, "Authentication storage is unavailable") from exc
        if int(count) > limit:
            raise HTTPException(
                429,
                "Too many login attempts",
                headers={"Retry-After": str(max(1, int(remaining)))},
            )
