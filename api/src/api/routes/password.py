"""Password credentials create the same Redis session as OAuth providers."""

from fastapi import APIRouter, Depends, HTTPException, Request
from redis_fastapi import AsyncRedisDep, SessionDep, SessionStoreDep
from redis_fastapi.deps import SessionStateDep

from api.dependencies.password import PasswordRepositoryDep, limit_password_attempts
from api.services.auth_providers import get_auth_providers
from api.schemas.auth import AuthSessionResponse, PasswordLoginRequest
from api.core.auth_session import establish_user_session
from api.repositories.user import public_user
from api.deps import SettingsDep

password_router = APIRouter(prefix="/auth/password", tags=["auth"])


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
