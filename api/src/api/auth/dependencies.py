import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from redis_fastapi import SessionDep, valid_session
from redis_fastapi.sessions import SessionRejected
from starlette.responses import JSONResponse

from api.auth.providers import get_auth_providers
from api.auth.schemas import AuthUser
from api.auth.users import PostgresUserRepository, UserRepository, public_user
from api.core.db import AsyncSessionLocal
from api.core.request_context import bind_identity
from api.deps import SettingsDep


def get_user_repository() -> UserRepository:
    return PostgresUserRepository(AsyncSessionLocal)


UsersDep = Annotated[UserRepository, Depends(get_user_repository)]


def _session_rejected(request: Request, reason: str) -> JSONResponse:
    return JSONResponse(
        {
            "detail": "Session storage is unavailable"
            if reason == "unavailable"
            else "Not authenticated"
        },
        status_code=503 if reason == "unavailable" else 401,
        headers={"Cache-Control": "no-store"},
    )


_valid_session = valid_session(on_reject=_session_rejected)


async def get_optional_auth_user(
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    users: UsersDep,
) -> AuthUser | None:
    # The public SDK gate distinguishes expired/anonymous sessions from outages.
    try:
        await _valid_session(request)
    except SessionRejected as exc:
        if exc.response.status_code == 503:
            raise HTTPException(503, "Session storage is unavailable") from exc
        return None
    user_id, provider = session.get("user_id"), session.get("provider")
    if not isinstance(user_id, str) or not isinstance(provider, str):
        return None
    if not any(
        item.id == provider and item.enabled
        for item in get_auth_providers(settings.auth)
    ):
        return None
    user = await users.get(user_id, provider)
    if (
        user is None
        or not user.is_active
        or user.auth_version != session.get("auth_version")
    ):
        return None
    if user.tenant_id != session.get("tenant_id"):
        return None
    # Incoming identity headers are optional assertions, never credentials.
    for name, expected in (
        (settings.request_context.user_id_header, user.id),
        (settings.request_context.tenant_id_header, user.tenant_id),
    ):
        claimed = request.headers.getlist(name)
        if claimed and claimed != [expected]:
            raise HTTPException(
                403, "Identity header does not match the authenticated session"
            )
    bind_identity(user.id, user.tenant_id)
    request.state.authenticated = True
    return public_user(user, provider)


OptionalUserDep = Annotated[AuthUser | None, Depends(get_optional_auth_user)]


def verify_csrf(
    request: Request, session: dict[str, object], settings: SettingsDep
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    expected, actual = (
        session.get("csrf_token"),
        request.headers.getlist("X-CSRF-Token"),
    )
    if (
        not isinstance(expected, str)
        or len(actual) != 1
        or not hmac.compare_digest(expected.encode(), actual[0].encode())
    ):
        raise HTTPException(403, "Invalid CSRF token")
    origins = request.headers.getlist("Origin")
    if origins and origins != [settings.auth.frontend_url]:
        raise HTTPException(403, "Invalid request origin")


async def require_auth_user(
    request: Request,
    user: OptionalUserDep,
    session: SessionDep,
    settings: SettingsDep,
) -> AuthUser:
    if user is None:
        raise HTTPException(
            401, "Not authenticated", headers={"Cache-Control": "no-store"}
        )
    verify_csrf(request, session, settings)
    return user


CurrentUserDep = Annotated[AuthUser, Depends(require_auth_user)]


async def authorize_resource(
    request: Request, user: CurrentUserDep, users: UsersDep
) -> None:
    for parameter, kind in (
        ("conversation_id", "conversation"),
        ("session_id", "agent_session"),
    ):
        resource_id = request.path_params.get(parameter)
        if resource_id and not await users.owns(kind, resource_id, user):
            raise HTTPException(404, "Resource not found")
