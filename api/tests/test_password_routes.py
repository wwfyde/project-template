"""Password HTTP flows use the real SDK session lifecycle, with fake storage."""

import hashlib
import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx2 import Response
from pytest import LogCaptureFixture, MonkeyPatch
from redis.exceptions import ConnectionError as RedisConnectionError
from redis_fastapi import (
    RedisSettings,
    SessionStore,
    get_async_redis,
    get_session_store,
)

from api.core.auth_config import AuthConfig
from api.dependencies.auth import CurrentUserDep, get_user_repository
from api.dependencies.password import get_password_repository
from api.routes.password import password_router
from api.repositories.password import normalize_username
from api.routes.auth import auth_router
from api.core.auth_session import configure_auth_sessions
from api.core.config import Settings, get_settings, settings
from api.core.request_context import RequestContextMiddleware
from api.models import Account, User
from test_redis_sdk_sessions import MemorySessionStore
from test_redis_sdk_sessions import sdk_settings as sdk_settings

LOGIN_PATH = "/api/auth/password/login"
SESSION_PATH = "/api/auth/session"
PRIVATE_PATH = "/api/private"
USERNAME = "alice@example.com"
PASSWORD = "test-only-Password-25!"
USER_ID = "31b8b701-c495-4c48-a418-fb82826b785b"
TENANT_ID = "password-tenant"
LOGIN_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


class MemoryAttemptRedis:
    """A controllable fixed-window counter implementing the route's Lua result."""

    def __init__(self) -> None:
        self.records: dict[str, tuple[int, int]] = {}
        self.calls: list[str] = []
        self.now = 0
        self.fail = False

    async def eval(
        self, script: str, key_count: int, key: str, window: int
    ) -> tuple[int, int]:
        self.calls.append(key)
        if self.fail:
            raise RedisConnectionError("test counter storage unavailable")
        assert key_count == 1
        count, expires = self.records.get(key, (0, self.now + window))
        if expires <= self.now:
            count, expires = 0, self.now + window
        self.records[key] = (count + 1, expires)
        return count + 1, expires - self.now


@dataclass
class PasswordEnvironment:
    app: FastAPI
    config: Settings
    store: MemorySessionStore
    redis: MemoryAttemptRedis
    repository: MagicMock
    user: User
    cookie_name: str


@pytest.fixture
def password_env(sdk_settings: RedisSettings) -> PasswordEnvironment:
    config = settings.model_copy(deep=True)
    config.app.env = "local"
    config.auth = AuthConfig(
        providers=["google", "password"],
        password={"enabled": True},
    )
    assert config.redis is not None
    config.redis.session_cookie_name = sdk_settings.session_cookie_name
    config.redis.session_cookie_https_only = True
    user = User(
        id=USER_ID,
        personal_account=Account(
            id=TENANT_ID, personal_user_id=USER_ID, structure="personal", is_active=True
        ),
        display_name="Alice",
        email=USERNAME,
        avatar_url=None,
        phone=None,
        is_active=True,
        auth_version=1,
    )

    async def authenticate(username: str, password: str) -> User | None:
        try:
            normalized = normalize_username(username)
        except ValueError:
            return None
        if normalized == USERNAME and password == PASSWORD and user.is_active:
            return user
        return None

    async def get_user(user_id: str, provider: str) -> User | None:
        return user if user_id == USER_ID and provider == "password" else None

    repository = MagicMock(authenticate=AsyncMock(side_effect=authenticate))

    async def get_account(user_id: str, account_id: str) -> Account | None:
        account = user.personal_account
        if (
            account is not None
            and account.id == account_id
            and account.personal_user_id == user_id
            and account.is_active
        ):
            return account
        return None

    users = MagicMock(
        get=AsyncMock(side_effect=get_user), account=AsyncMock(side_effect=get_account)
    )
    store = MemorySessionStore()
    redis = MemoryAttemptRedis()
    app = FastAPI()
    configure_auth_sessions(app, config)
    app.add_middleware(RequestContextMiddleware, config=config.request_context)
    app.include_router(password_router, prefix="/api")
    app.include_router(auth_router, prefix="/api")

    async def session_store_override(request: Request) -> SessionStore:
        return store

    app.dependency_overrides[get_session_store] = session_store_override
    app.dependency_overrides[get_async_redis] = lambda: redis
    app.dependency_overrides[get_password_repository] = lambda: repository
    app.dependency_overrides[get_user_repository] = lambda: users
    app.dependency_overrides[get_settings] = lambda: config

    @app.get(PRIVATE_PATH)
    async def private_get(user: CurrentUserDep) -> dict[str, str]:
        return {"id": user.id, "account_id": user.account_id, "provider": user.provider}

    @app.post(PRIVATE_PATH)
    async def private_post(user: CurrentUserDep) -> dict[str, str]:
        return {"id": user.id}

    return PasswordEnvironment(
        app, config, store, redis, repository, user, sdk_settings.session_cookie_name
    )


@pytest.fixture
def password_client(password_env: PasswordEnvironment) -> Iterator[TestClient]:
    with TestClient(password_env.app, base_url="https://testserver") as client:
        yield client


def login(client: TestClient, **headers: str) -> Response:
    return client.post(
        LOGIN_PATH,
        json={"username": USERNAME, "password": PASSWORD},
        headers={**LOGIN_HEADERS, **headers},
    )


def test_password_login_rotates_session_and_binds_trusted_identity(
    password_client: TestClient, password_env: PasswordEnvironment
) -> None:
    first = login(password_client)
    assert first.status_code == 200
    old_id = password_client.cookies[password_env.cookie_name]
    old_csrf = first.json()["csrf_token"]
    response = login(
        password_client,
        **{
            "User-ID": "forged-user",
            "Tenant-ID": "forged-tenant",
            "Request-ID": "password-login-request",
            "Origin": password_env.config.auth.frontend_url,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["user"]["id"] == USER_ID
    assert data["user"]["account_id"] == TENANT_ID
    assert data["user"]["tenant_id"] == TENANT_ID
    assert data["user"]["provider"] == "password"
    assert len(data["csrf_token"]) >= 32
    assert data["csrf_token"] != old_csrf
    assert response.headers["user-id"] == USER_ID
    assert response.headers["tenant-id"] == TENANT_ID
    assert response.headers["request-id"] == "password-login-request"
    assert "no-store" in response.headers["cache-control"]
    cookie = SimpleCookie(response.headers["set-cookie"])[password_env.cookie_name]
    assert cookie["secure"]
    assert cookie["httponly"]
    assert cookie["samesite"].lower() == "lax"
    new_id = password_client.cookies[password_env.cookie_name]
    assert new_id != old_id
    assert old_id not in password_env.store.records
    assert set(password_env.store.records) == {new_id}
    assert password_client.get(SESSION_PATH).json()["user"] == data["user"]
    assert password_client.get(PRIVATE_PATH).json() == {
        "id": USER_ID,
        "account_id": TENANT_ID,
        "provider": "password",
    }
    with TestClient(password_env.app, base_url="https://testserver") as stale:
        assert (
            stale.get(
                PRIVATE_PATH,
                headers={"Cookie": f"{password_env.cookie_name}={old_id}"},
            ).status_code
            == 401
        )
    raw_session = password_env.store.records[new_id][0]
    assert PASSWORD not in raw_session
    assert "hashed_password" not in raw_session
    assert "argon2" not in raw_session
    assert "access_token" not in data


def test_password_session_reuses_write_and_logout_csrf_protection(
    password_client: TestClient, password_env: PasswordEnvironment
) -> None:
    csrf = login(password_client).json()["csrf_token"]
    assert password_client.post(PRIVATE_PATH).status_code == 403
    assert password_client.post("/api/auth/logout").status_code == 403
    assert (
        password_client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": csrf, "Origin": "https://untrusted.example"},
        ).status_code
        == 403
    )
    assert (
        password_client.post(PRIVATE_PATH, headers={"X-CSRF-Token": csrf}).status_code
        == 200
    )
    assert (
        password_client.post(
            "/api/auth/logout", headers={"X-CSRF-Token": csrf}
        ).status_code
        == 204
    )
    assert not password_env.store.records
    assert password_client.get(SESSION_PATH).json()["authenticated"] is False
    assert password_client.get(PRIVATE_PATH).status_code == 401


@pytest.mark.parametrize("failure", ["unknown", "wrong", "disabled"])
def test_invalid_credentials_and_disabled_accounts_have_the_same_response(
    password_client: TestClient, password_env: PasswordEnvironment, failure: str
) -> None:
    if failure == "disabled":
        password_env.user.is_active = False
    response = password_client.post(
        LOGIN_PATH,
        json={
            "username": "unknown" if failure == "unknown" else USERNAME,
            "password": "wrong-password" if failure == "wrong" else PASSWORD,
        },
        headers=LOGIN_HEADERS,
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect username or password"}
    assert "set-cookie" not in response.headers
    assert "user-id" not in response.headers
    assert not password_env.store.records


@pytest.mark.parametrize("omitted", [False, True])
def test_disabled_or_omitted_password_channel_rejects_login_before_verification(
    password_client: TestClient, password_env: PasswordEnvironment, omitted: bool
) -> None:
    if omitted:
        password_env.config.auth.providers = ["google"]
    else:
        password_env.config.auth.password.enabled = False
    response = login(password_client)
    assert response.status_code == 503
    password_env.repository.authenticate.assert_not_awaited()
    assert not password_env.redis.calls


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Requested-With": "fetch"},
        {**LOGIN_HEADERS, "Origin": "https://untrusted.example"},
        {**LOGIN_HEADERS, "Sec-Fetch-Site": "cross-site"},
        [
            ("X-Requested-With", "XMLHttpRequest"),
            ("X-Requested-With", "XMLHttpRequest"),
        ],
        [
            ("X-Requested-With", "XMLHttpRequest"),
            ("Origin", "http://localhost:5173"),
            ("Origin", "http://localhost:5173"),
        ],
    ],
)
def test_login_csrf_policy_rejects_missing_or_cross_site_headers(
    password_client: TestClient,
    password_env: PasswordEnvironment,
    headers: dict[str, str] | list[tuple[str, str]],
) -> None:
    response = password_client.post(
        LOGIN_PATH, json={"username": USERNAME, "password": PASSWORD}, headers=headers
    )
    assert response.status_code == 403
    password_env.repository.authenticate.assert_not_awaited()
    assert not password_env.redis.calls


def test_username_rate_limit_normalizes_names_and_resets_after_fixed_window(
    password_client: TestClient, password_env: PasswordEnvironment
) -> None:
    config = password_env.config.auth.password
    assert (config.rate_limit_attempts, config.ip_rate_limit_attempts) == (10, 50)
    assert config.rate_limit_window_seconds == 300
    config.rate_limit_attempts = 2
    for username in (USERNAME, f"  {USERNAME.upper()}  "):
        assert (
            password_client.post(
                LOGIN_PATH,
                json={"username": username, "password": "wrong-password"},
                headers=LOGIN_HEADERS,
            ).status_code
            == 401
        )
    password_env.redis.now = 120
    blocked = login(password_client)
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "180"
    assert "no-store" in blocked.headers["cache-control"]
    assert password_env.repository.authenticate.await_count == 2
    keys = [key for key in password_env.redis.records if ":username:" in key]
    assert len(keys) == 1
    assert keys[0].endswith(hashlib.sha256(USERNAME.encode()).hexdigest())
    assert USERNAME not in keys[0]
    assert len(password_env.redis.calls) == 6
    password_env.redis.now = 300
    assert login(password_client).status_code == 200
    assert password_env.redis.records[keys[0]][0] == 1


def test_ip_rate_limit_cannot_be_bypassed_with_forwarded_headers_or_new_names(
    password_client: TestClient, password_env: PasswordEnvironment
) -> None:
    password_env.config.auth.password.ip_rate_limit_attempts = 2
    for attempt in range(3):
        response = password_client.post(
            LOGIN_PATH,
            json={"username": f"account-{attempt}", "password": PASSWORD},
            headers={**LOGIN_HEADERS, "X-Forwarded-For": f"203.0.113.{attempt + 1}"},
        )
        assert response.status_code == (429 if attempt == 2 else 401)
    assert response.headers["retry-after"] == "300"
    assert len([key for key in password_env.redis.records if ":client:" in key]) == 1
    assert len(password_env.redis.calls) == 5
    assert password_env.repository.authenticate.await_count == 2


def test_redis_rate_counter_failure_does_not_run_password_verification(
    password_client: TestClient, password_env: PasswordEnvironment
) -> None:
    password_env.redis.fail = True
    response = login(password_client)
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    password_env.repository.authenticate.assert_not_awaited()
    assert not password_env.store.records


@pytest.mark.parametrize(
    "body",
    [
        {"username": USERNAME, "password": PASSWORD * 100},
        {"username": USERNAME, "password": {"secret": PASSWORD}},
        {"password": PASSWORD},
        {"username": USERNAME, "password": PASSWORD, "extra": PASSWORD},
        [USERNAME, PASSWORD],
        PASSWORD,
    ],
)
def test_invalid_login_schema_never_reflects_password_or_body(
    password_client: TestClient, password_env: PasswordEnvironment, body: object
) -> None:
    response = password_client.post(LOGIN_PATH, json=body, headers=LOGIN_HEADERS)
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert all("input" not in error for error in response.json()["detail"])
    assert "no-store" in response.headers["cache-control"]
    password_env.repository.authenticate.assert_not_awaited()


def test_password_and_request_body_do_not_appear_in_logs(
    password_client: TestClient, caplog: LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        assert login(password_client).status_code == 200
        assert (
            password_client.post(
                LOGIN_PATH,
                content=json.dumps({"username": USERNAME, "password": PASSWORD})[:-1],
                headers={**LOGIN_HEADERS, "Content-Type": "application/json"},
            ).status_code
            == 422
        )
    assert PASSWORD not in caplog.text
    assert PASSWORD not in repr([record.__dict__ for record in caplog.records])


@pytest.mark.parametrize("transient", [False, True])
def test_session_write_failure_cannot_establish_a_logged_in_cookie(
    password_client: TestClient,
    password_env: PasswordEnvironment,
    monkeypatch: MonkeyPatch,
    transient: bool,
) -> None:
    original_write = password_env.store._write
    calls = 0

    async def fail_write(
        session_id: str, payload: str, *, idle: int, absolute: int | None
    ) -> None:
        nonlocal calls
        calls += 1
        if not transient or calls == 1:
            raise RedisConnectionError("test write failure")
        await original_write(session_id, payload, idle=idle, absolute=absolute)

    monkeypatch.setattr(password_env.store, "_write", fail_write)
    response = login(password_client)
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    assert "user-id" not in response.headers
    assert not password_env.store.records
    assert password_client.get(SESSION_PATH).json()["authenticated"] is False
