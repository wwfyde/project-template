"""Exercise auth HTTP flows using the real SDK session lifecycle and middleware.

Only Redis primitives, the user repository and external identity providers are
replaced. No database, Redis server, or identity-provider account is required.
"""

import hashlib
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from threading import Barrier, Lock
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis.exceptions import ConnectionError as RedisConnectionError
from redis_fastapi import SessionStore, get_async_redis, get_session_store
from redis_fastapi import get_settings as get_sdk_settings

from api.auth import routes
from api.auth.config import AuthConfig
from api.auth.dependencies import CurrentUserDep, get_user_repository
from api.auth.providers import AuthProviderError, OAuthProvider, get_oauth_provider
from api.auth.schemas import AuthUser, ProviderIdentity
from api.auth.session import configure_auth_sessions
from api.core.config import Settings, get_settings, settings
from api.core.request_context import RequestContextMiddleware
from api.models.user import User
from test_redis_sdk_sessions import MemorySessionStore

COOKIE_NAME = "auth_integration_test"
SESSION_PATH = "/api/auth/session"
PROTECTED_PATH = "/api/private"
USER_ID = "40b3beef-13ca-49ca-96d8-b34e7b4a0001"
TENANT_ID = "test-tenant"


class MemoryOAuthRedis:
    """Atomic GETDEL plus a controllable clock for OAuth state expiration."""

    def __init__(self) -> None:
        self.records: dict[str, tuple[str, int]] = {}
        self.now = 0
        self.lock = Lock()

    async def set(self, key: str, value: str, *, ex: int) -> None:
        with self.lock:
            self.records[key] = (value, self.now + ex)

    async def getdel(self, key: str) -> str | None:
        with self.lock:
            record = self.records.pop(key, None)
        return record[0] if record is not None and record[1] > self.now else None


class FakeUsers:
    def __init__(self) -> None:
        self.user = User(
            id=USER_ID,
            tenant_id=TENANT_ID,
            display_name="Test User",
            email="user@example.com",
            avatar_url=None,
            phone=None,
            is_active=True,
            auth_version=1,
        )
        self.deleted = False
        self.resolutions = 0

    async def resolve(
        self, identity: ProviderIdentity, *, tenant_id: str, allow_signup: bool
    ) -> User:
        assert tenant_id == TENANT_ID
        if not self.user.is_active:
            raise HTTPException(403, "Account is disabled")
        self.resolutions += 1
        return self.user

    async def get(self, user_id: str, provider: str) -> User | None:
        return self.user if user_id == USER_ID and not self.deleted else None

    async def own(self, kind: str, resource_id: str, user: AuthUser) -> None:
        pass

    async def owns(self, kind: str, resource_id: str, user: AuthUser) -> bool:
        return False

    async def owned_ids(self, kind: str, user: AuthUser) -> set[str]:
        return set()


class FakeOAuthProvider:
    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        self.calls: list[tuple[str, str, str]] = []
        self.fail = False

    def build_authorize_url(self, *, state: str, nonce: str, code_verifier: str) -> str:
        return f"https://identity.example/authorize?{urlencode({'state': state, 'nonce': nonce})}"

    async def authenticate(
        self, code: str, *, nonce: str, code_verifier: str
    ) -> ProviderIdentity:
        self.calls.append((code, nonce, code_verifier))
        if self.fail:
            raise AuthProviderError("External provider unavailable")
        return ProviderIdentity(
            provider=self.provider_id,
            subject="external-subject",
            display_name="Test User",
            email="user@example.com",
        )


@dataclass
class AuthTestEnvironment:
    app: FastAPI
    settings: Settings
    store: MemorySessionStore
    redis: MemoryOAuthRedis
    users: FakeUsers
    providers: dict[str, FakeOAuthProvider]


@pytest.fixture
def auth_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> AuthTestEnvironment:
    monkeypatch.chdir(tmp_path)
    config = settings.model_copy(deep=True)
    config.app.env = "local"
    config.auth = AuthConfig.model_validate(
        {
            "default_tenant_id": TENANT_ID,
            "google": {"client_id": "test-google", "client_secret": "test-secret"},
            "dingtalk": {
                "enabled": True,
                "client_id": "test-dingtalk",
                "client_secret": "test-secret",
            },
        }
    )
    assert config.redis is not None
    config.redis.session_cookie_name = COOKIE_NAME
    config.redis.session_cookie_path = "/"
    config.redis.session_cookie_https_only = True
    config.redis.session_cookie_same_site = "lax"
    sdk_settings = get_sdk_settings()
    for name, value in {
        "session_cookie_name": COOKIE_NAME,
        "session_cookie_path": "/",
        "session_cookie_domain": None,
        "session_cookie_https_only": True,
        "session_cookie_same_site": "lax",
        "session_refresh_on_load": True,
        "session_always_save": False,
        "session_fail_closed": False,
        "session_principal_keys": ["user_id", "tenant_id", "auth_version"],
        "rate_limit_default_limit": 0,
    }.items():
        monkeypatch.setattr(sdk_settings, name, value)

    store = MemorySessionStore()
    redis = MemoryOAuthRedis()
    users = FakeUsers()
    providers = {key: FakeOAuthProvider(key) for key in ("google", "dingtalk")}

    def provider_override(provider_id: str, auth_config: AuthConfig) -> OAuthProvider:
        # Preserve production availability/configuration validation.
        get_oauth_provider(provider_id, auth_config)
        return providers[provider_id]

    monkeypatch.setattr(routes, "get_oauth_provider", provider_override)
    app = FastAPI()
    configure_auth_sessions(app, config)
    app.add_middleware(RequestContextMiddleware, config=config.request_context)
    app.include_router(routes.auth_router, prefix="/api")

    async def session_store_override(request: Request) -> SessionStore:
        store.resolutions += 1
        return store

    app.dependency_overrides[get_session_store] = session_store_override
    app.dependency_overrides[get_async_redis] = lambda: redis
    app.dependency_overrides[get_user_repository] = lambda: users
    app.dependency_overrides[get_settings] = lambda: config

    @app.get(PROTECTED_PATH)
    async def private_get(user: CurrentUserDep) -> dict[str, str]:
        return {"id": user.id, "tenant_id": user.tenant_id}

    @app.post(PROTECTED_PATH)
    async def private_post(user: CurrentUserDep) -> dict[str, str]:
        return {"id": user.id, "tenant_id": user.tenant_id}

    return AuthTestEnvironment(app, config, store, redis, users, providers)


@pytest.fixture
def auth_client(auth_env: AuthTestEnvironment) -> Iterator[TestClient]:
    with TestClient(auth_env.app, base_url="https://testserver") as client:
        yield client


def start(client: TestClient, provider_id: str = "google", return_to: str = "/") -> str:
    response = client.get(
        f"/api/auth/oauth/{provider_id}/start",
        params={"return_to": return_to},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "no-store" in response.headers["cache-control"]
    return parse_qs(urlsplit(response.headers["location"]).query)["state"][0]


def login(client: TestClient, provider_id: str = "google") -> dict[str, object]:
    state = start(client, provider_id)
    response = client.get(
        f"/api/auth/oauth/{provider_id}/callback",
        params={"state": state, "code": "test-authorization-code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client.get(SESSION_PATH).json()


def test_legacy_dingtalk_start_and_callback_use_the_same_session_security(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    start_response = auth_client.get("/api/auth/dingtalk/start", follow_redirects=False)
    assert start_response.status_code == 303
    state = parse_qs(urlsplit(start_response.headers["location"]).query)["state"][0]
    old_id = auth_client.cookies[COOKIE_NAME]
    callback = auth_client.get(
        "/api/auth/dingtalk/callback",
        params={"state": state, "authCode": "test-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert old_id not in auth_env.store.records
    assert auth_client.cookies[COOKIE_NAME] != old_id
    assert auth_client.get(SESSION_PATH).json()["user"]["provider"] == "dingtalk"
    assert (
        auth_client.get(
            "/api/auth/dingtalk/callback",
            params={"state": state, "authCode": "test-code"},
            follow_redirects=False,
        ).status_code
        == 400
    )


def test_anonymous_session_ignores_forged_identity_headers(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    headers = {
        "User-ID": USER_ID,
        "Tenant-ID": TENANT_ID,
        "Request-ID": "test-anonymous",
    }
    response = auth_client.get(SESSION_PATH, headers=headers)
    assert response.status_code == 200
    assert response.json()["authenticated"] is False
    assert response.json()["csrf_token"] is None
    assert response.json()["user"] is None
    assert response.headers["request-id"] == "test-anonymous"
    assert "user-id" not in response.headers
    assert "tenant-id" not in response.headers
    assert "set-cookie" not in response.headers
    assert "no-store" in response.headers["cache-control"]
    assert auth_client.get(PROTECTED_PATH, headers=headers).status_code == 401
    assert not auth_env.store.records


def test_start_binds_browser_and_keeps_verifier_out_of_authorization_url(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    response = auth_client.get(
        "/api/auth/oauth/google/start",
        params={"return_to": "/assets?q=1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie = SimpleCookie(response.headers["set-cookie"])[COOKIE_NAME]
    assert cookie["httponly"]
    assert cookie["secure"]
    assert cookie["samesite"].lower() == "lax"
    assert cookie["path"] == "/"
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    key, (payload, expiry) = next(iter(auth_env.redis.records.items()))
    attempt = json.loads(payload)
    assert key.endswith(hashlib.sha256(state.encode()).hexdigest())
    assert state not in key
    assert expiry == auth_env.settings.auth.oauth_state_ttl_seconds
    assert attempt["return_to"] == "/assets?q=1"
    assert len(attempt["nonce"]) >= 32
    assert len(attempt["code_verifier"]) >= 43
    assert attempt["code_verifier"] not in response.headers["location"]
    assert response.headers["referrer-policy"] == "no-referrer"


def test_callback_rotates_session_and_returns_csrf_with_trusted_ids(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    state = start(auth_client, return_to="/assets?view=grid")
    old_id = auth_client.cookies[COOKIE_NAME]
    attempt = json.loads(next(iter(auth_env.redis.records.values()))[0])
    response = auth_client.get(
        "/api/auth/oauth/google/callback",
        params={"state": state, "code": "test-code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "http://localhost:5173/assets?view=grid"
    assert response.headers["user-id"] == USER_ID
    assert response.headers["tenant-id"] == TENANT_ID
    assert "no-store" in response.headers["cache-control"]
    new_id = auth_client.cookies[COOKIE_NAME]
    assert new_id != old_id
    assert old_id not in auth_env.store.records
    assert set(auth_env.store.records) == {new_id}
    assert auth_env.providers["google"].calls == [
        ("test-code", attempt["nonce"], attempt["code_verifier"])
    ]
    session = auth_client.get(
        SESSION_PATH, headers={"User-ID": USER_ID, "Tenant-ID": TENANT_ID}
    )
    assert session.json()["authenticated"] is True
    assert session.json()["user"]["id"] == USER_ID
    assert session.json()["user"]["tenant_id"] == TENANT_ID
    assert len(session.json()["csrf_token"]) >= 32
    assert session.headers["user-id"] == USER_ID
    assert session.headers["tenant-id"] == TENANT_ID
    assert auth_client.get(PROTECTED_PATH).status_code == 200
    payload = auth_env.store.records[new_id][0]
    assert "test-code" not in payload
    assert "access_token" not in payload
    assert "oauth_browser" not in payload
    with TestClient(auth_env.app, base_url="https://testserver") as stale:
        response = stale.get(
            PROTECTED_PATH, headers={"Cookie": f"{COOKIE_NAME}={old_id}"}
        )
    assert response.status_code == 401


def test_foreign_browser_cannot_redeem_state(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    state = start(auth_client)
    with TestClient(auth_env.app, base_url="https://testserver") as other:
        response = other.get(
            "/api/auth/oauth/google/callback",
            params={"state": state, "code": "code"},
            follow_redirects=False,
        )
    assert response.status_code == 400
    assert "browser binding" in response.json()["detail"]
    assert auth_env.users.resolutions == 0
    assert not auth_env.providers["google"].calls
    # Consumed even on a failed browser check; it cannot later be replayed.
    assert (
        auth_client.get(
            "/api/auth/oauth/google/callback", params={"state": state, "code": "code"}
        ).status_code
        == 400
    )


@pytest.mark.parametrize("expired", [True, False])
def test_expired_and_replayed_state_cannot_create_another_session(
    auth_client: TestClient, auth_env: AuthTestEnvironment, expired: bool
) -> None:
    state = start(auth_client)
    if expired:
        auth_env.redis.now += auth_env.settings.auth.oauth_state_ttl_seconds
    else:
        assert (
            auth_client.get(
                "/api/auth/oauth/google/callback",
                params={"state": state, "code": "code"},
                follow_redirects=False,
            ).status_code
            == 303
        )
    before = auth_env.users.resolutions
    response = auth_client.get(
        "/api/auth/oauth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert auth_env.users.resolutions == before


def test_concurrent_callbacks_consume_state_exactly_once(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    state = start(auth_client)
    old_cookie = auth_client.cookies[COOKIE_NAME]
    barrier = Barrier(2)

    def callback() -> int:
        with TestClient(auth_env.app, base_url="https://testserver") as client:
            barrier.wait(timeout=10)
            response = client.get(
                "/api/auth/oauth/google/callback",
                params={"state": state, "code": "concurrent-code"},
                headers={"Cookie": f"{COOKIE_NAME}={old_cookie}"},
                follow_redirects=False,
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: callback(), range(2)))
    assert sorted(results) == [303, 400]
    assert len(auth_env.providers["google"].calls) == 1
    assert auth_env.users.resolutions == 1
    assert old_cookie not in auth_env.store.records


@pytest.mark.parametrize("provider_id", ["phone", "unknown"])
def test_unimplemented_or_unknown_provider_has_no_login_entry(
    auth_client: TestClient, auth_env: AuthTestEnvironment, provider_id: str
) -> None:
    response = auth_client.get(
        f"/api/auth/oauth/{provider_id}/start", follow_redirects=False
    )
    assert response.status_code == 503
    assert not auth_env.redis.records
    assert not auth_env.store.records


@pytest.mark.parametrize("removed", [True, False])
def test_provider_removal_or_disable_invalidates_existing_login(
    auth_client: TestClient, auth_env: AuthTestEnvironment, removed: bool
) -> None:
    login(auth_client, "dingtalk")
    if removed:
        auth_env.settings.auth.providers = ["google"]
    else:
        auth_env.settings.auth.dingtalk.enabled = False
    response = auth_client.get(SESSION_PATH)
    assert response.json()["authenticated"] is False
    assert response.json()["csrf_token"] is None
    assert "user-id" not in response.headers
    assert auth_client.get(PROTECTED_PATH).status_code == 401


@pytest.mark.parametrize("change", ["disabled", "deleted", "version", "tenant"])
def test_authoritative_user_changes_invalidate_session(
    auth_client: TestClient, auth_env: AuthTestEnvironment, change: str
) -> None:
    login(auth_client)
    if change == "disabled":
        auth_env.users.user.is_active = False
    elif change == "deleted":
        auth_env.users.deleted = True
    elif change == "version":
        auth_env.users.user.auth_version += 1
    else:
        auth_env.users.user.tenant_id = "another-tenant"
    response = auth_client.get(SESSION_PATH)
    assert response.json()["authenticated"] is False
    assert response.json()["user"] is None
    assert response.json()["csrf_token"] is None
    assert "user-id" not in response.headers
    assert "tenant-id" not in response.headers
    assert auth_client.get(PROTECTED_PATH).status_code == 401


@pytest.mark.parametrize(
    "headers", [{"User-ID": "other-user"}, {"Tenant-ID": "other-tenant"}]
)
def test_authenticated_identity_header_mismatch_is_rejected(
    auth_client: TestClient, headers: dict[str, str]
) -> None:
    login(auth_client)
    response = auth_client.get(PROTECTED_PATH, headers=headers)
    assert response.status_code == 403
    assert "user-id" not in response.headers
    assert "tenant-id" not in response.headers


@pytest.mark.parametrize("headers", [{}, {"X-CSRF-Token": "wrong-token"}])
def test_logout_rejects_missing_or_wrong_csrf_without_revoking(
    auth_client: TestClient, auth_env: AuthTestEnvironment, headers: dict[str, str]
) -> None:
    login(auth_client)
    old_id = auth_client.cookies[COOKIE_NAME]
    response = auth_client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 403
    assert old_id in auth_env.store.records
    assert "set-cookie" not in response.headers
    assert auth_client.get(PROTECTED_PATH).status_code == 200


def test_logout_revokes_session_and_clears_cookie(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    session = login(auth_client)
    old_id = auth_client.cookies[COOKIE_NAME]
    response = auth_client.post(
        "/api/auth/logout",
        headers={
            "X-CSRF-Token": str(session["csrf_token"]),
            "Origin": auth_env.settings.auth.frontend_url,
        },
    )
    assert response.status_code == 204
    assert not response.content
    assert old_id not in auth_env.store.records
    assert COOKIE_NAME not in auth_client.cookies
    cookie = SimpleCookie(response.headers["set-cookie"])[COOKIE_NAME]
    assert cookie["max-age"] == "0"
    assert "no-store" in response.headers["cache-control"]
    assert auth_client.get(PROTECTED_PATH).status_code == 401
    assert auth_client.get(SESSION_PATH).json()["authenticated"] is False


def test_csrf_token_cannot_be_used_from_another_origin(auth_client: TestClient) -> None:
    session = login(auth_client)
    response = auth_client.post(
        "/api/auth/logout",
        headers={
            "X-CSRF-Token": str(session["csrf_token"]),
            "Origin": "https://attacker.example",
        },
    )
    assert response.status_code == 403
    assert auth_client.get(PROTECTED_PATH).status_code == 200


def test_write_requires_csrf_and_accepts_current_session_token(
    auth_client: TestClient,
) -> None:
    session = login(auth_client)
    assert auth_client.post(PROTECTED_PATH).status_code == 403
    assert (
        auth_client.post(
            PROTECTED_PATH, headers={"X-CSRF-Token": str(session["csrf_token"])}
        ).status_code
        == 200
    )


def test_logout_storage_failure_does_not_report_success(
    auth_client: TestClient, auth_env: AuthTestEnvironment, monkeypatch: MonkeyPatch
) -> None:
    session = login(auth_client)
    old_id = auth_client.cookies[COOKIE_NAME]
    monkeypatch.setattr(
        auth_env.store,
        "_delete",
        AsyncMock(side_effect=RedisConnectionError("test outage")),
    )
    response = auth_client.post(
        "/api/auth/logout", headers={"X-CSRF-Token": str(session["csrf_token"])}
    )
    assert response.status_code == 503
    assert old_id in auth_env.store.records
    assert auth_client.cookies[COOKIE_NAME] == old_id
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("fail_closed", [True, False])
def test_session_load_failure_fails_closed(
    auth_client: TestClient,
    auth_env: AuthTestEnvironment,
    monkeypatch: MonkeyPatch,
    fail_closed: bool,
) -> None:
    login(auth_client)
    monkeypatch.setattr(get_sdk_settings(), "session_fail_closed", fail_closed)
    monkeypatch.setattr(
        auth_env.store,
        "_read",
        AsyncMock(side_effect=RedisConnectionError("test outage")),
    )
    for path in (SESSION_PATH, PROTECTED_PATH):
        response = auth_client.get(path)
        assert response.status_code == 503
        assert "user-id" not in response.headers
        assert "set-cookie" not in response.headers


def test_disabling_correlation_does_not_disable_private_response_cache_policy(
    auth_client: TestClient,
    auth_env: AuthTestEnvironment,
) -> None:
    auth_env.settings.request_context.enabled = False
    login(auth_client)
    response = auth_client.get(PROTECTED_PATH)
    assert response.status_code == 200
    assert "request-id" not in response.headers
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("operation", ["set", "getdel"])
def test_oauth_storage_failure_cannot_establish_login(
    auth_client: TestClient,
    auth_env: AuthTestEnvironment,
    monkeypatch: MonkeyPatch,
    operation: str,
) -> None:
    state = start(auth_client) if operation == "getdel" else None
    monkeypatch.setattr(
        auth_env.redis,
        operation,
        AsyncMock(side_effect=RedisConnectionError("test outage")),
    )
    path = (
        "/api/auth/oauth/google/callback" if state else "/api/auth/oauth/google/start"
    )
    response = auth_client.get(
        path,
        params={"state": state, "code": "code"} if state else {},
        follow_redirects=False,
    )
    assert response.status_code == 503
    assert not auth_env.providers["google"].calls
    assert "user-id" not in response.headers


def test_callback_session_rotation_failure_cannot_establish_login(
    auth_client: TestClient, auth_env: AuthTestEnvironment, monkeypatch: MonkeyPatch
) -> None:
    state = start(auth_client)
    old_id = auth_client.cookies[COOKIE_NAME]
    monkeypatch.setattr(
        auth_env.store,
        "_write",
        AsyncMock(side_effect=RedisConnectionError("test outage")),
    )
    response = auth_client.get(
        "/api/auth/oauth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 503
    assert old_id not in auth_env.store.records
    assert "user-id" not in response.headers
    assert "set-cookie" not in response.headers


def test_callback_provider_failure_returns_safe_login_error(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    state = start(auth_client, return_to="/assets")
    auth_env.providers["google"].fail = True
    response = auth_client.get(
        "/api/auth/oauth/google/callback",
        params={"state": state, "code": "private-code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    target = urlsplit(response.headers["location"])
    assert target.path == "/login"
    assert parse_qs(target.query) == {
        "error": ["oauth_failed"],
        "redirect": ["/assets"],
    }
    assert "private-code" not in response.headers["location"]
    assert auth_client.get(SESSION_PATH).json()["authenticated"] is False


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/oauth/phone/start",
        "/api/auth/oauth/google/callback?state=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&code=code",
    ],
)
def test_authentication_error_responses_are_not_cacheable(
    auth_client: TestClient, path: str
) -> None:
    response = auth_client.get(path, follow_redirects=False)
    assert response.status_code in {400, 503}
    assert "no-store" in response.headers.get("cache-control", "")


def test_duplicate_identity_and_csrf_headers_are_rejected(
    auth_client: TestClient,
) -> None:
    session = login(auth_client)
    token = str(session["csrf_token"])
    response = auth_client.get(
        PROTECTED_PATH, headers=[("User-ID", USER_ID), ("User-ID", USER_ID)]
    )
    assert response.status_code == 403
    response = auth_client.post(
        "/api/auth/logout", headers=[("X-CSRF-Token", token), ("X-CSRF-Token", token)]
    )
    assert response.status_code == 403
    assert auth_client.get(PROTECTED_PATH).status_code == 200


def test_non_ascii_csrf_is_rejected_without_internal_error(
    auth_client: TestClient,
) -> None:
    login(auth_client)
    response = auth_client.post(
        "/api/auth/logout", headers=[(b"X-CSRF-Token", b"\xff")]
    )
    assert response.status_code == 403


def test_state_cannot_be_redeemed_by_another_provider(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    state = start(auth_client)
    response = auth_client.get(
        "/api/auth/oauth/dingtalk/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert not auth_env.providers["google"].calls
    assert not auth_env.providers["dingtalk"].calls


def test_provider_denial_redirects_to_login_without_authenticating(
    auth_client: TestClient, auth_env: AuthTestEnvironment
) -> None:
    state = start(auth_client, return_to="/assets")
    response = auth_client.get(
        "/api/auth/oauth/google/callback",
        params={"state": state, "error": "access_denied"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers["location"]).query) == {
        "error": ["oauth_denied"],
        "redirect": ["/assets"],
    }
    assert not auth_env.providers["google"].calls
    assert auth_client.get(SESSION_PATH).json()["authenticated"] is False


def test_anonymous_session_save_failure_cannot_start_oauth(
    auth_env: AuthTestEnvironment, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(
        auth_env.store,
        "_write",
        AsyncMock(side_effect=RedisConnectionError("test outage")),
    )
    with TestClient(
        auth_env.app, base_url="https://testserver", raise_server_exceptions=False
    ) as client:
        response = client.get("/api/auth/oauth/google/start", follow_redirects=False)
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    assert "location" not in response.headers
    assert "no-store" in response.headers["cache-control"]
    assert not auth_env.store.records


def test_transient_rotation_failure_does_not_later_save_authenticated_session(
    auth_client: TestClient, auth_env: AuthTestEnvironment, monkeypatch: MonkeyPatch
) -> None:
    state = start(auth_client)
    original_write = auth_env.store._write
    calls = 0

    async def fail_once(
        session_id: str, payload: str, *, idle: int, absolute: int | None
    ) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RedisConnectionError("single transient failure")
        await original_write(session_id, payload, idle=idle, absolute=absolute)

    monkeypatch.setattr(auth_env.store, "_write", fail_once)
    response = auth_client.get(
        "/api/auth/oauth/google/callback",
        params={"state": state, "code": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 503
    assert auth_client.get(SESSION_PATH).json()["authenticated"] is False
