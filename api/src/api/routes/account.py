"""Self-service account management; every mutation uses session CSRF checks."""

import hashlib
import logging
import secrets
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from redis.exceptions import RedisError
from redis_fastapi import AsyncRedisDep, SessionDep, SessionStoreDep
from redis_fastapi.deps import SessionStateDep
from redis_fastapi.session_backend import SessionStoreError

from api.dependencies.account import AccountStoreDep, account_http_error
from api.schemas.account import (
    AccountIdentity,
    AccountMutationResponse,
    AccountRead,
    AccountSummary,
    AuthorizationStart,
    PasswordReauthentication,
    PasswordUpdate,
    ProfileUpdate,
)
from api.core.account_security import (
    login_deadline,
    reauthentication_status,
    require_recent_authentication,
    require_live_session,
    session_digest,
)
from api.repositories.user_security import AccountError
from api.dependencies.auth import CurrentUserDep
from api.dependencies.password import PasswordRepositoryDep, limit_password_attempts
from api.services.auth_providers import (
    AuthProviderUnavailable,
    get_auth_providers,
    get_oauth_provider,
)
from api.core.oauth import _state_key
from api.schemas.auth import OAuthAttempt
from api.schemas.auth import AuthSessionResponse, AuthUser
from api.core.auth_session import establish_user_session
from api.repositories.user import public_user
from api.deps import SettingsDep

logger = logging.getLogger(__name__)
account_router = APIRouter(prefix="/account", tags=["account"])


def _version(session: SessionDep) -> int:
    value = session.get("auth_version")
    if type(value) is not int or value < 1:
        raise HTTPException(401, "Not authenticated")
    return value


def _password_enabled(settings: SettingsDep) -> None:
    if not any(
        item.id == "password" and item.enabled
        for item in get_auth_providers(settings.auth)
    ):
        raise HTTPException(
            503,
            {
                "code": "provider_unavailable",
                "message": "Password authentication is unavailable",
            },
        )


async def _read_account(
    user: AuthUser,
    session: SessionDep,
    settings: SettingsDep,
    accounts: AccountStoreDep,
) -> AccountRead:
    try:
        snapshot = await accounts.snapshot(user.id, user.account_id)
    except AccountError as exc:
        raise account_http_error(exc) from exc
    if snapshot.user.auth_version != _version(session):
        raise HTTPException(
            409,
            {"code": "account_changed", "message": "Account changed; sign in again"},
        )
    providers = get_auth_providers(settings.auth)
    enabled = {item.id for item in providers if item.enabled}
    usable = [
        item
        for item in snapshot.identities
        if item.provider in enabled
        and (item.provider != "password" or snapshot.username is not None)
    ]
    return AccountRead(
        account=AccountSummary.model_validate(snapshot.account),
        user=public_user(snapshot.user, user.provider, snapshot.account),
        providers=providers,
        identities=[
            AccountIdentity(
                id=item.id,
                provider=item.provider,
                username=snapshot.username if item.provider == "password" else None,
                enabled=item in usable,
                current=item.provider == user.provider,
                can_unlink=any(other.id != item.id for other in usable),
            )
            for item in snapshot.identities
        ],
        reauthentication=reauthentication_status(
            session, settings.auth.reauth_max_age_seconds
        ),
    )


@account_router.get("", response_model=AccountRead)
async def account(
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    accounts: AccountStoreDep,
) -> AccountRead:
    return await _read_account(user, session, settings, accounts)


@account_router.patch("/profile", response_model=AccountRead)
async def update_profile(
    payload: ProfileUpdate,
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    accounts: AccountStoreDep,
) -> AccountRead:
    try:
        await accounts.profile(
            user.id,
            user.account_id,
            _version(session),
            payload.model_dump(exclude_unset=True),
        )
    except AccountError as exc:
        raise account_http_error(exc) from exc
    logger.info(
        "Account profile updated", extra={"otel.event.name": "account.profile_updated"}
    )
    return await _read_account(user, session, settings, accounts)


async def _start_oauth(
    intent: Literal["link", "reauth"],
    provider_id: str,
    user: CurrentUserDep,
    session: SessionDep,
    state: SessionStateDep,
    settings: SettingsDep,
    accounts: AccountStoreDep,
    redis: AsyncRedisDep,
) -> AuthorizationStart:
    if intent == "link":
        require_recent_authentication(session, settings.auth.reauth_max_age_seconds)
    current = await _read_account(user, session, settings, accounts)
    linked = any(item.provider == provider_id for item in current.identities)
    if intent == "link" and linked:
        raise HTTPException(
            409,
            {
                "code": "provider_already_linked",
                "message": "This login provider is already linked",
            },
        )
    if intent == "reauth" and not linked:
        raise HTTPException(
            403,
            {
                "code": "identity_not_linked",
                "message": "Verify an existing login method",
            },
        )
    try:
        provider = get_oauth_provider(provider_id, settings.auth)
    except AuthProviderUnavailable as exc:
        raise HTTPException(
            503, {"code": "provider_unavailable", "message": str(exc)}
        ) from exc
    browser = session.get("oauth_browser")
    if not isinstance(browser, str):
        browser = secrets.token_urlsafe(32)
    token = secrets.token_urlsafe(32)
    attempt = OAuthAttempt(
        provider=provider_id,
        browser_digest=hashlib.sha256(browser.encode()).hexdigest(),
        nonce=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(48),
        return_to="/account",
        intent=intent,
        user_id=user.id,
        account_id=user.account_id,
        auth_version=_version(session),
        session_digest=session_digest(state),
        current_provider=user.provider,
    )
    url = provider.build_authorize_url(
        state=token,
        nonce=attempt.nonce,
        code_verifier=attempt.code_verifier,
        interactive=True,
    )
    try:
        await redis.set(
            _state_key(settings, token),
            attempt.model_dump_json(),
            ex=settings.auth.oauth_state_ttl_seconds,
        )
    except RedisError as exc:
        raise HTTPException(503, "Authentication storage is unavailable") from exc
    session["oauth_browser"] = browser
    return AuthorizationStart(authorization_url=url)


@account_router.post(
    "/identities/{provider_id}/start", response_model=AuthorizationStart
)
async def link_start(
    provider_id: str,
    user: CurrentUserDep,
    session: SessionDep,
    state: SessionStateDep,
    settings: SettingsDep,
    accounts: AccountStoreDep,
    redis: AsyncRedisDep,
) -> AuthorizationStart:
    return await _start_oauth(
        "link", provider_id, user, session, state, settings, accounts, redis
    )


@account_router.post(
    "/reauth/oauth/{provider_id}/start", response_model=AuthorizationStart
)
async def reauthenticate_oauth(
    provider_id: str,
    user: CurrentUserDep,
    session: SessionDep,
    state: SessionStateDep,
    settings: SettingsDep,
    accounts: AccountStoreDep,
    redis: AsyncRedisDep,
) -> AuthorizationStart:
    return await _start_oauth(
        "reauth", provider_id, user, session, state, settings, accounts, redis
    )


@account_router.post("/reauth/password", response_model=AuthSessionResponse)
async def reauthenticate_password(
    payload: PasswordReauthentication,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    state: SessionStateDep,
    store: SessionStoreDep,
    settings: SettingsDep,
    accounts: AccountStoreDep,
    passwords: PasswordRepositoryDep,
    redis: AsyncRedisDep,
) -> AuthSessionResponse:
    _password_enabled(settings)
    current = await _read_account(user, session, settings, accounts)
    credential = next(
        (item for item in current.identities if item.provider == "password"), None
    )
    if credential is None or credential.username is None:
        raise HTTPException(
            403,
            {"code": "identity_not_linked", "message": "Password login is not linked"},
        )
    await limit_password_attempts(request, credential.username, redis, settings)
    verified = await passwords.authenticate(
        credential.username, payload.password.get_secret_value()
    )
    if (
        verified is None
        or verified.id != user.id
        or verified.auth_version != _version(session)
    ):
        raise HTTPException(
            403,
            {
                "code": "reauthentication_failed",
                "message": "Could not verify your password",
            },
        )
    deadline = login_deadline(session, state, store)
    await require_live_session(session, state, store, deadline)
    # Password hashing can outlive membership or account revocation.
    current = await _read_account(user, session, settings, accounts)
    await establish_user_session(
        verified,
        "password",
        session,
        state,
        store,
        request,
        login_expires_at=deadline,
        account_id=user.account_id,
    )
    return AuthSessionResponse(
        authenticated=True,
        user=current.user.model_copy(update={"provider": "password"}),
        providers=get_auth_providers(settings.auth),
        csrf_token=session["csrf_token"],
    )


@account_router.put("/password", response_model=AccountMutationResponse)
async def update_password(
    payload: PasswordUpdate,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    state: SessionStateDep,
    store: SessionStoreDep,
    settings: SettingsDep,
    accounts: AccountStoreDep,
    redis: AsyncRedisDep,
) -> AccountMutationResponse:
    _password_enabled(settings)
    require_recent_authentication(session, settings.auth.reauth_max_age_seconds)
    current = await _read_account(user, session, settings, accounts)
    username = next(
        (item.username for item in current.identities if item.provider == "password"),
        None,
    )
    await limit_password_attempts(
        request, username or payload.username or user.id, redis, settings
    )
    deadline = login_deadline(session, state, store)
    verified_at = session["authenticated_at"]
    try:
        updated = await accounts.set_password(
            user.id,
            user.account_id,
            _version(session),
            username=payload.username,
            password=payload.password.get_secret_value(),
            current_password=payload.current_password.get_secret_value()
            if payload.current_password
            else None,
        )
    except AccountError as exc:
        raise account_http_error(exc) from exc
    await require_live_session(session, state, store, deadline)
    await establish_user_session(
        updated,
        user.provider,
        session,
        state,
        store,
        request,
        authenticated_at=verified_at,
        login_expires_at=deadline,
        account_id=user.account_id,
    )
    logger.info(
        "Account password updated",
        extra={"otel.event.name": "account.password_updated"},
    )
    return AccountMutationResponse()


@account_router.delete(
    "/identities/{identity_id}", response_model=AccountMutationResponse
)
async def unlink_identity(
    identity_id: str,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    state: SessionStateDep,
    store: SessionStoreDep,
    settings: SettingsDep,
    accounts: AccountStoreDep,
) -> AccountMutationResponse:
    require_recent_authentication(session, settings.auth.reauth_max_age_seconds)
    current = await _read_account(user, session, settings, accounts)
    identity = next(
        (item for item in current.identities if item.id == identity_id), None
    )
    if identity is None:
        raise HTTPException(
            404, {"code": "identity_not_linked", "message": "Identity was not found"}
        )
    deadline, verified_at = (
        login_deadline(session, state, store),
        session["authenticated_at"],
    )
    try:
        updated = await accounts.unlink_identity(
            user.id,
            user.account_id,
            _version(session),
            identity_id,
            {item.id for item in current.providers if item.enabled},
        )
    except AccountError as exc:
        raise account_http_error(exc) from exc
    if identity.current:
        try:
            await store.revoke(state)
        except SessionStoreError as exc:
            raise HTTPException(
                503,
                {
                    "code": "session_changed",
                    "message": "Account updated; sign in again",
                },
            ) from exc
    else:
        await require_live_session(session, state, store, deadline)
        await establish_user_session(
            updated,
            user.provider,
            session,
            state,
            store,
            request,
            authenticated_at=verified_at,
            login_expires_at=deadline,
            account_id=user.account_id,
        )
    logger.info(
        "Account identity unlinked",
        extra={
            "otel.event.name": "account.identity_unlinked",
            "auth.provider": identity.provider,
        },
    )
    return AccountMutationResponse(requires_login=identity.current)
