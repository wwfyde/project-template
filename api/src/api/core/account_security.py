"""Fresh account ownership proofs never derive from the identity being linked."""

import hashlib
import math
import time
from collections.abc import Mapping

from fastapi import HTTPException
from redis_fastapi.session_backend import SessionState, SessionStore, SessionStoreError

from api.schemas.account import ReauthenticationStatus


def reauthentication_status(
    session: Mapping[str, object], max_age: int
) -> ReauthenticationStatus:
    value = session.get("authenticated_at")
    now = time.time()
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value > now
    ):
        return ReauthenticationStatus(required=True, expires_in=0)
    remaining = max(0, int(value + max_age - now))
    return ReauthenticationStatus(required=remaining <= 0, expires_in=remaining)


def require_recent_authentication(session: Mapping[str, object], max_age: int) -> None:
    if reauthentication_status(session, max_age).required:
        raise HTTPException(
            403,
            {
                "code": "reauthentication_required",
                "message": "Verify an existing login method before changing account security",
            },
        )


def session_digest(state: SessionState) -> str:
    if not state.session_id:
        raise HTTPException(401, "Not authenticated")
    return hashlib.sha256(state.session_id.encode()).hexdigest()


def login_deadline(
    session: Mapping[str, object], state: SessionState, store: SessionStore
) -> float:
    value = session.get("login_expires_at")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ):
        return float(value)
    # Older sessions can reauthenticate without acquiring a fresh absolute TTL.
    if state.absolute_remaining is not None and state.absolute_remaining > 0:
        return time.time() + state.absolute_remaining
    if state.created is None:
        raise HTTPException(401, "Not authenticated")
    return state.created + store.absolute_seconds


async def require_live_session(
    session: Mapping[str, object],
    state: SessionState,
    store: SessionStore,
    deadline: float,
) -> None:
    """A completed credential check cannot revive a source login already ended."""
    if state.session_id is None or deadline <= time.time():
        raise HTTPException(
            401,
            {"code": "session_changed", "message": "Your session ended; sign in again"},
        )
    try:
        loaded, failed = await store.load_with_status(state.session_id, refresh=False)
    except SessionStoreError as exc:
        raise HTTPException(503, "Session storage is unavailable") from exc
    if failed:
        raise HTTPException(503, "Session storage is unavailable")
    if loaded is None or any(
        loaded.record.data.get(key) != session.get(key)
        for key in ("user_id", "account_id", "auth_version", "csrf_token")
    ):
        raise HTTPException(
            401,
            {
                "code": "session_changed",
                "message": "Your session changed; sign in again",
            },
        )
