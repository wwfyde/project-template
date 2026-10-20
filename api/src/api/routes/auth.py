import hashlib
import hmac
import logging
import secrets
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from redis.exceptions import RedisError
from redis_fastapi import AsyncRedisDep, SessionDep, SessionStoreDep
from redis_fastapi.deps import SessionStateDep
from redis_fastapi.session_backend import SessionStoreError

from api.dependencies.auth import OptionalUserDep, UsersDep, verify_csrf
from api.dependencies.account import AccountStoreDep
from api.services.auth_providers import (
    AuthProviderError,
    AuthProviderUnavailable,
    OAuthProvider,
    get_auth_providers,
    get_oauth_provider,
)
from api.schemas.auth import AuthSessionResponse, OAuthAttempt
from api.core.oauth import _redirect, _state_key, sanitize_return_to
from api.core.auth_session import establish_user_session
from api.deps import SettingsDep

logger = logging.getLogger(__name__)
auth_router = APIRouter(prefix="/auth", tags=["auth"])


def _provider(provider_id: str, settings: SettingsDep) -> OAuthProvider:
    try:
        return get_oauth_provider(provider_id, settings.auth)
    except AuthProviderUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@auth_router.get("/session", response_model=AuthSessionResponse)
async def session_status(
    user: OptionalUserDep,
    session: SessionDep,
    settings: SettingsDep,
    response: Response,
) -> AuthSessionResponse:
    response.headers["Cache-Control"] = "no-store"
    return AuthSessionResponse(
        authenticated=user is not None,
        user=user,
        providers=get_auth_providers(settings.auth),
        csrf_token=session.get("csrf_token") if user is not None else None,
    )


@auth_router.post("/logout", status_code=204)
async def logout(
    request: Request,
    user: OptionalUserDep,
    session: SessionDep,
    state: SessionStateDep,
    store: SessionStoreDep,
    settings: SettingsDep,
) -> Response:
    if session:
        verify_csrf(request, session, settings)
    try:
        await store.revoke(state)
    except SessionStoreError as exc:
        raise HTTPException(503, "Session revocation failed") from exc
    logger.info("Signed out", extra={"otel.event.name": "auth.logout"})
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@auth_router.get("/{provider_id}/start", include_in_schema=False)
@auth_router.get("/oauth/{provider_id}/start")
async def oauth_start(
    provider_id: str,
    session: SessionDep,
    settings: SettingsDep,
    redis: AsyncRedisDep,
    return_to: Annotated[str, Query(max_length=2048)] = "/",
) -> RedirectResponse:
    provider = _provider(provider_id, settings)
    browser = session.get("oauth_browser")
    if not isinstance(browser, str):
        browser = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)
    attempt = OAuthAttempt(
        provider=provider_id,
        browser_digest=hashlib.sha256(browser.encode()).hexdigest(),
        nonce=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(48),
        return_to=sanitize_return_to(return_to),
    )
    authorize_url = provider.build_authorize_url(
        state=state, nonce=attempt.nonce, code_verifier=attempt.code_verifier
    )
    try:
        await redis.set(
            _state_key(settings, state),
            attempt.model_dump_json(),
            ex=settings.auth.oauth_state_ttl_seconds,
        )
    except RedisError as exc:
        raise HTTPException(503, "Authentication storage is unavailable") from exc
    session["oauth_browser"] = browser
    return RedirectResponse(
        authorize_url,
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@auth_router.get("/{provider_id}/callback", include_in_schema=False)
@auth_router.get("/oauth/{provider_id}/callback")
async def oauth_callback(
    provider_id: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    redis: AsyncRedisDep,
    users: UsersDep,
    store: SessionStoreDep,
    session_state: SessionStateDep,
    accounts: AccountStoreDep,
    state: Annotated[str, Query(min_length=32, max_length=128)],
    code: Annotated[str | None, Query(max_length=4096)] = None,
    auth_code: Annotated[str | None, Query(alias="authCode", max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> RedirectResponse:
    provider = _provider(provider_id, settings)
    try:
        # GETDEL makes the attempt single-use even under concurrent callbacks.
        raw = await redis.getdel(_state_key(settings, state))
    except RedisError as exc:
        raise HTTPException(503, "Authentication storage is unavailable") from exc
    if raw is None:
        raise HTTPException(400, "Invalid or expired OAuth state")
    try:
        attempt = OAuthAttempt.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(400, "Invalid OAuth state") from exc
    browser = session.get("oauth_browser")
    if (
        attempt.provider != provider_id
        or not isinstance(browser, str)
        or not hmac.compare_digest(
            attempt.browser_digest, hashlib.sha256(browser.encode()).hexdigest()
        )
    ):
        raise HTTPException(400, "OAuth state browser binding mismatch")
    if attempt.intent != "login":
        # Account callbacks never use the ordinary signup/login resolution path.
        from api.services.account_oauth import complete_account_oauth

        return await complete_account_oauth(
            attempt,
            provider,
            request,
            session,
            settings,
            users,
            store,
            session_state,
            accounts,
            code or auth_code,
            error,
        )
    if error:
        return _redirect(
            settings,
            "/login?"
            + urlencode({"error": "oauth_denied", "redirect": attempt.return_to}),
        )
    authorization_code = code or auth_code
    if not authorization_code:
        raise HTTPException(400, "Missing OAuth authorization code")
    try:
        identity = await provider.authenticate(
            authorization_code, nonce=attempt.nonce, code_verifier=attempt.code_verifier
        )
        if identity.provider != provider_id:
            raise AuthProviderError("Provider identity mismatch")
    except AuthProviderError:
        # Neither provider response bodies nor callback URLs belong in logs.
        logger.warning(
            "OAuth authentication failed", extra={"auth.provider": provider_id}
        )
        return _redirect(
            settings,
            "/login?"
            + urlencode({"error": "oauth_failed", "redirect": attempt.return_to}),
        )
    user = await users.resolve(
        identity,
        allow_signup=settings.auth.allow_signup,
    )
    await establish_user_session(
        user, identity.provider, session, session_state, store, request
    )
    return _redirect(settings, attempt.return_to)
