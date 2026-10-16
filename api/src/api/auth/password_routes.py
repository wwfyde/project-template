"""Password credentials create the same Redis session as OAuth providers."""

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from redis.exceptions import RedisError
from redis_fastapi import AsyncRedisDep, SessionDep, SessionStoreDep
from redis_fastapi.deps import SessionStateDep

from api.auth.passwords import PasswordRepository, normalize_username
from api.auth.providers import get_auth_providers
from api.auth.schemas import AuthSessionResponse, PasswordLoginRequest
from api.auth.session import establish_user_session
from api.auth.users import public_user
from api.core.db import AsyncSessionLocal
from api.deps import SettingsDep

password_router = APIRouter(prefix="/auth/password", tags=["auth"])

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


async def password_login_policy(request: Request, settings: SettingsDep) -> None:
    if "password" not in settings.auth.providers or not settings.auth.password.enabled:
        raise HTTPException(503, "Password authentication is unavailable")
    # A custom header cannot be attached by a cross-site HTML form. Same-origin
    # fetch and explicit CLI requests can supply it; no anonymous login CSRF.
    if request.headers.getlist("X-Requested-With") != ["XMLHttpRequest"]:
        raise HTTPException(403, "Login requires X-Requested-With: XMLHttpRequest")
    origins = request.headers.getlist("Origin")
    if origins and origins != [settings.auth.frontend_url]:
        raise HTTPException(403, "Invalid request origin")
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise HTTPException(403, "Cross-site login is not allowed")


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


@password_router.post(
    "/login",
    response_model=AuthSessionResponse,
    dependencies=[Depends(password_login_policy)],
)
async def password_login(
    payload: PasswordLoginRequest,
    request: Request,
    repository: PasswordRepositoryDep,
    redis: AsyncRedisDep,
    session: SessionDep,
    state: SessionStateDep,
    store: SessionStoreDep,
    settings: SettingsDep,
) -> AuthSessionResponse:
    await limit_password_attempts(request, payload.username, redis, settings)
    user = await repository.authenticate(
        payload.username, payload.password.get_secret_value()
    )
    if user is None:
        # Nonexistent, disabled and incorrect credentials have the same answer.
        raise HTTPException(401, "Incorrect username or password")
    await establish_user_session(user, "password", session, state, store, request)
    return AuthSessionResponse(
        authenticated=True,
        user=public_user(user, "password"),
        providers=get_auth_providers(settings.auth),
        csrf_token=session["csrf_token"],
    )
