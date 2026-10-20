"""Fresh proofs and legacy deadlines must fail closed without adding lifetime."""

import pytest
from fastapi import HTTPException
from redis_fastapi.session_backend import SessionState
from test_redis_sdk_sessions import MemorySessionStore

from api.core import account_security as security


@pytest.mark.parametrize(
    "value", [None, "1000", True, float("nan"), float("inf"), 1001, 699]
)
def test_invalid_or_stale_proof_cannot_authorize_changes(
    value: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(security.time, "time", lambda: 1000)
    assert security.reauthentication_status({"authenticated_at": value}, 300).required
    with pytest.raises(HTTPException) as error:
        security.require_recent_authentication({"authenticated_at": value}, 300)
    assert error.value.status_code == 403


def test_legacy_session_adopts_remaining_server_ttl_not_new_configured_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(security.time, "time", lambda: 1000)
    state = SessionState(data={}, session_id="test", created=900, absolute_remaining=5)
    store = MemorySessionStore()
    assert security.login_deadline({}, state, store) == 1005
    assert security.login_deadline({"login_expires_at": 1002}, state, store) == 1002
