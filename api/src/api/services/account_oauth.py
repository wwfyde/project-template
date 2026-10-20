"""OAuth account intents never create or switch the local account."""

import hmac
import logging
from urllib.parse import urlencode

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from redis_fastapi import SessionDep, SessionStoreDep
from redis_fastapi.deps import SessionStateDep

from api.dependencies.account import AccountStoreDep
from api.core.account_security import (
    login_deadline,
    require_recent_authentication,
    require_live_session,
    session_digest,
)
from api.repositories.user_security import AccountError
from api.dependencies.auth import UsersDep, get_optional_auth_user
from api.services.auth_providers import AuthProviderError, OAuthProvider
from api.core.oauth import _redirect
from api.schemas.auth import OAuthAttempt
from api.core.auth_session import establish_user_session
from api.deps import SettingsDep

logger = logging.getLogger(__name__)


def _failure(settings: SettingsDep, code: str) -> RedirectResponse:
    return _redirect(settings, "/account?" + urlencode({"account_error": code}))


async def complete_account_oauth(
    attempt: OAuthAttempt,
    provider: OAuthProvider,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    users: UsersDep,
    store: SessionStoreDep,
    state: SessionStateDep,
    accounts: AccountStoreDep,
    code: str | None,
    error: str | None,
) -> RedirectResponse:
    session_id, version = state.session_id, attempt.auth_version
    try:
        user = await get_optional_auth_user(request, session, settings, users)
        if (
            user is None
            or session_id is None
            or version is None
            or attempt.user_id != user.id
            or attempt.account_id != user.account_id
            or attempt.auth_version != session.get("auth_version")
            or attempt.current_provider != user.provider
            or not attempt.session_digest
            or not hmac.compare_digest(attempt.session_digest, session_digest(state))
        ):
            return _failure(settings, "session_changed")
        if attempt.intent == "link":
            require_recent_authentication(session, settings.auth.reauth_max_age_seconds)
        deadline = login_deadline(session, state, store)
    except HTTPException as exc:
        if exc.status_code == 503:
            raise
        return _failure(
            settings,
            "reauthentication_required"
            if isinstance(exc.detail, dict)
            and exc.detail.get("code") == "reauthentication_required"
            else "session_changed",
        )
    if error:
        return _failure(settings, "oauth_denied")
    if not code:
        return _failure(settings, "oauth_failed")
    try:
        identity = await provider.authenticate(
            code, nonce=attempt.nonce, code_verifier=attempt.code_verifier
        )
        if identity.provider != attempt.provider:
            raise AuthProviderError("Provider identity mismatch")
    except AuthProviderError:
        logger.warning(
            "Account OAuth verification failed",
            extra={"auth.provider": attempt.provider},
        )
        return _failure(settings, "oauth_failed")
    # Recheck the source session after the external round trip. Linking proof
    # from the target provider does not revive a revoked or expired source login.
    try:
        await require_live_session(session, state, store, deadline)
    except HTTPException as exc:
        if exc.status_code == 503:
            raise
        return _failure(settings, "session_changed")
    verified_at = session.get("authenticated_at")
    try:
        if attempt.intent == "link":
            require_recent_authentication(session, settings.auth.reauth_max_age_seconds)
            updated = await accounts.link_identity(
                user.id, user.account_id, version, identity
            )
        else:
            updated = await accounts.verify_identity(
                user.id, user.account_id, version, identity
            )
    except AccountError as exc:
        return _failure(settings, exc.code)
    except HTTPException:
        return _failure(settings, "reauthentication_required")
    try:
        await require_live_session(session, state, store, deadline)
    except HTTPException as exc:
        if exc.status_code == 503:
            raise
        return _failure(settings, "session_changed")
    await establish_user_session(
        updated,
        user.provider if attempt.intent == "link" else identity.provider,
        session,
        state,
        store,
        request,
        authenticated_at=verified_at if attempt.intent == "link" else None,
        login_expires_at=deadline,
        account_id=user.account_id,
    )
    logger.info(
        "Account OAuth operation completed",
        extra={
            "otel.event.name": f"account.{attempt.intent}",
            "auth.provider": identity.provider,
        },
    )
    return _redirect(
        settings,
        "/account?"
        + urlencode(
            {
                "account_action": "linked"
                if attempt.intent == "link"
                else "reauthenticated"
            }
        ),
    )
