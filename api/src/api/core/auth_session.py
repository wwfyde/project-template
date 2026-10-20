"""Configure one SDK session middleware for the whole API."""

import logging
import secrets
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from redis_fastapi import FastAPIRedis, Session, SessionStore
from redis_fastapi.session_backend import SessionState, SessionStoreError
from starlette.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.core.config import Settings
from api.core.request_context import bind_identity
from api.models.user import User
from api.core.header_auth import HEADER_EXAMPLE_PREFIX

logger = logging.getLogger(__name__)


async def establish_user_session(
    user: User,
    provider: str,
    session: Session,
    state: SessionState,
    store: SessionStore,
    request: Request,
    *,
    authenticated_at: float | None = None,
    login_expires_at: float | None = None,
    account_id: str | None = None,
) -> None:
    """All credential channels share identity rotation and the same payload."""
    if account_id is None:
        account = user.personal_account
        if account is None or not account.is_active:
            raise HTTPException(403, "Personal account is unavailable")
        account_id = account.id
    session.clear()
    session.update(
        {
            "user_id": user.id,
            "account_id": account_id,
            "provider": provider,
            "auth_version": user.auth_version,
            "csrf_token": secrets.token_urlsafe(32),
            "authenticated_at": time.time()
            if authenticated_at is None
            else authenticated_at,
            "login_expires_at": time.time() + store.absolute_seconds
            if login_expires_at is None
            else login_expires_at,
        }
    )
    try:
        await store.rotate(state, subject=user.id)
    except SessionStoreError as exc:
        raise HTTPException(503, "Could not establish a login session") from exc
    bind_identity(user.id, account_id)
    request.state.authenticated = True
    logger.info(
        "Signed in", extra={"otel.event.name": "auth.login", "auth.provider": provider}
    )


async def auth_validation_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise exc
    if request.url.path.startswith(("/api/auth/", "/api/account/")):
        # FastAPI normally includes rejected input in its validation response.
        # Never reflect passwords, credentials or an entire login request body.
        errors = [
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ]
        return JSONResponse(
            {"detail": errors}, status_code=422, headers={"Cache-Control": "no-store"}
        )
    return await request_validation_exception_handler(request, exc)


class SessionAvailabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                if scope.get("path", "") == "/api/account" or scope.get(
                    "path", ""
                ).startswith(("/api/auth/", "/api/account/")):
                    headers = MutableHeaders(scope=message)
                    headers["Cache-Control"] = "no-store"
                    headers["Referrer-Policy"] = "no-referrer"
                elif scope.get("path", "") == HEADER_EXAMPLE_PREFIX or scope.get(
                    "path", ""
                ).startswith(f"{HEADER_EXAMPLE_PREFIX}/"):
                    MutableHeaders(scope=message)["Cache-Control"] = "no-store"
                elif scope.get("state", {}).get("authenticated"):
                    # Cache protection is authentication policy, independent of
                    # whether request correlation headers are enabled.
                    MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except SessionStoreError:
            if started or scope["type"] != "http":
                raise
            await JSONResponse(
                {"detail": "Session storage is unavailable"},
                status_code=503,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)


def configure_auth_sessions(app: FastAPI, settings: Settings) -> None:
    redis = settings.redis
    if redis is None:
        raise ValueError("Authentication requires Redis")
    if redis.session_idle_ttl <= 0 or redis.session_absolute_ttl <= 0:
        raise ValueError(
            "Authentication requires positive idle and absolute session TTLs"
        )
    if settings.app.env == "prod" and not redis.session_cookie_https_only:
        raise ValueError("Production authentication requires Secure session cookies")
    if redis.session_cookie_same_site != "lax":
        raise ValueError("OAuth authentication requires SameSite=lax session cookies")
    if redis.session_cookie_path not in {"/", "/api"}:
        raise ValueError("Session cookie path must cover all API routes")

    def skip(request: Request) -> bool:
        # Header-only service examples must work even with an expired browser
        # cookie or an unavailable session store. User routes are never exempt.
        if request.url.path == HEADER_EXAMPLE_PREFIX or request.url.path.startswith(
            f"{HEADER_EXAMPLE_PREFIX}/"
        ):
            return True
        return not request.url.path.startswith("/api/") or request.url.path in {
            "/api/health",
            "/api/hello",
        }

    FastAPIRedis(app).sessions(
        principal_keys=["user_id", "account_id", "auth_version"],
        subject_of=lambda session: session.get("user_id"),
        key_prefix=f"{settings.auth.session_key_prefix}:{settings.app.env}:sessions",
        skip=skip,
    )
    app.add_middleware(SessionAvailabilityMiddleware)
    app.add_exception_handler(RequestValidationError, auth_validation_error)
