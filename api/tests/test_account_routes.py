"""Account HTTP security uses real repositories, transactions and SDK sessions.

SQLite exercises persistence, while the SDK memory store replaces Redis I/O and
the fake OAuth providers replace network identity checks. PostgreSQL row-lock
semantics and live provider consent screens are not covered by this suite.
"""

import json
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from fastapi.testclient import TestClient
from httpx2 import Response
from redis.exceptions import ConnectionError as RedisConnectionError
from redis_fastapi import get_async_redis
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.routes import account as account_routes
from api.dependencies.account import get_account_store
from api.repositories.user_security import AccountStore
from api.dependencies.auth import get_user_repository
from api.dependencies.password import get_password_repository
from api.routes.password import password_router
from api.repositories.password import PasswordRepository, hash_password
from api.services.auth_providers import get_oauth_provider
from api.schemas.auth import ProviderIdentity
from api.repositories.user import PostgresUserRepository
from api.models import Account, AccountMember, PasswordCredential, User, UserIdentity
from test_account_store import DatabaseFactory
from test_auth_routes import (
    COOKIE_NAME,
    SESSION_PATH,
    TENANT_ID,
    USER_ID,
    AuthTestEnvironment,
    FakeOAuthProvider,
    MemoryOAuthRedis,
    auth_env as auth_env,
    login,
)
from test_password_routes import MemoryAttemptRedis

PASSWORD = "account-test-password"
NEW_PASSWORD = "account-new-password"
ACCOUNT_PATH = "/api/account"


class AccountOAuthProvider(FakeOAuthProvider):
    def __init__(self, provider_id: str) -> None:
        super().__init__(provider_id)
        self.subject = "external-subject"
        self.interactive: list[bool] = []

    def build_authorize_url(
        self, *, state: str, nonce: str, code_verifier: str, interactive: bool = False
    ) -> str:
        self.interactive.append(interactive)
        return "https://identity.example/authorize?" + urlencode(
            {"state": state, "nonce": nonce}
        )

    async def authenticate(
        self, code: str, *, nonce: str, code_verifier: str
    ) -> ProviderIdentity:
        result = await super().authenticate(
            code, nonce=nonce, code_verifier=code_verifier
        )
        return result.model_copy(update={"subject": self.subject})


class AccountRedis(MemoryOAuthRedis):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = MemoryAttemptRedis()

    async def eval(
        self, script: str, key_count: int, key: str, window: int
    ) -> tuple[int, int]:
        return await self.attempts.eval(script, key_count, key, window)


@dataclass
class AccountEnvironment:
    auth: AuthTestEnvironment
    engine: Engine
    accounts: AccountStore
    redis: AccountRedis
    providers: dict[str, AccountOAuthProvider]


@pytest.fixture
def account_env(
    auth_env: AuthTestEnvironment, monkeypatch: pytest.MonkeyPatch
) -> Iterator[AccountEnvironment]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for model in (User, Account, AccountMember, UserIdentity, PasswordCredential):
            model.__table__.create(connection)
    with Session(engine) as db, db.begin():
        db.add(
            User(
                id=USER_ID,
                personal_account=Account(
                    id=TENANT_ID,
                    personal_user_id=USER_ID,
                    structure="personal",
                    is_active=True,
                ),
                display_name="Local User",
                email="local@example.com",
                is_active=True,
                auth_version=1,
            )
        )
        db.flush()
        db.add(AccountMember(account_id=TENANT_ID, user_id=USER_ID, role="owner"))
        db.add(
            UserIdentity(
                id="google-identity",
                user_id=USER_ID,
                provider="google",
                subject="external-subject",
            )
        )
    factory = cast(async_sessionmaker[AsyncSession], DatabaseFactory(engine))
    accounts = AccountStore(factory)
    users = PostgresUserRepository(factory)
    passwords = PasswordRepository(factory)
    redis = AccountRedis()
    providers = {name: AccountOAuthProvider(name) for name in ("google", "dingtalk")}
    auth_env.providers.update(providers)
    auth_env.settings.auth.providers = ["google", "dingtalk", "password", "phone"]
    auth_env.settings.auth.password.enabled = True
    auth_env.app.include_router(account_routes.account_router, prefix="/api")
    auth_env.app.include_router(password_router, prefix="/api")
    auth_env.app.dependency_overrides[get_account_store] = lambda: accounts
    auth_env.app.dependency_overrides[get_user_repository] = lambda: users
    auth_env.app.dependency_overrides[get_password_repository] = lambda: passwords
    auth_env.app.dependency_overrides[get_async_redis] = lambda: redis

    def provider_override(provider_id: str, config: object) -> AccountOAuthProvider:
        get_oauth_provider(provider_id, config)
        return providers[provider_id]

    monkeypatch.setattr(account_routes, "get_oauth_provider", provider_override)
    yield AccountEnvironment(auth_env, engine, accounts, redis, providers)
    engine.dispose()


@pytest.fixture
def account_client(account_env: AccountEnvironment) -> Iterator[TestClient]:
    with TestClient(account_env.auth.app, base_url="https://testserver") as client:
        yield client


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.get(SESSION_PATH).json()["csrf_token"]}


def session_data(client: TestClient, env: AccountEnvironment) -> dict[str, object]:
    raw, _ = env.auth.store.records[client.cookies[COOKIE_NAME]]
    return env.auth.store.decode(raw).data


def update_session(
    client: TestClient, env: AccountEnvironment, **changes: object
) -> None:
    sid = client.cookies[COOKIE_NAME]
    raw, ttl = env.auth.store.records[sid]
    record = env.auth.store.decode(raw)
    record.data.update(changes)
    env.auth.store.records[sid] = (env.auth.store.encode(record), ttl)


def seed_workspace(env: AccountEnvironment) -> str:
    account_id = "workspace-test"
    with Session(env.engine) as db, db.begin():
        db.add(
            Account(
                id=account_id,
                name="Test workspace",
                structure="workspace",
                is_active=True,
            )
        )
        db.flush()
        db.add(AccountMember(account_id=account_id, user_id=USER_ID, role="owner"))
    return account_id


def seed_identity(
    env: AccountEnvironment,
    provider: str = "dingtalk",
    *,
    user_id: str = USER_ID,
    subject: str = "external-subject",
) -> str:
    identity_id = f"{provider}-{user_id}"
    with Session(env.engine) as db, db.begin():
        if user_id != USER_ID and db.get(User, user_id) is None:
            db.add(
                User(
                    id=user_id,
                    personal_account=Account(
                        id=f"personal-{user_id}",
                        personal_user_id=user_id,
                        structure="personal",
                        is_active=True,
                    ),
                    display_name="Other user",
                    is_active=True,
                    auth_version=1,
                )
            )
            db.flush()
            db.add(
                AccountMember(
                    account_id=f"personal-{user_id}", user_id=user_id, role="owner"
                )
            )
        db.add(
            UserIdentity(
                id=identity_id, user_id=user_id, provider=provider, subject=subject
            )
        )
        if provider == "password":
            db.add(
                PasswordCredential(
                    user_id=user_id,
                    username=subject,
                    hashed_password=hash_password(PASSWORD),
                )
            )
    return identity_id


def start_account_oauth(
    client: TestClient, provider: str = "dingtalk", *, reauth: bool = False
) -> str:
    path = (
        f"{ACCOUNT_PATH}/reauth/oauth/{provider}/start"
        if reauth
        else f"{ACCOUNT_PATH}/identities/{provider}/start"
    )
    response = client.post(path, headers=csrf(client))
    assert response.status_code == 200, response.text
    return parse_qs(urlsplit(response.json()["authorization_url"]).query)["state"][0]


def callback(
    client: TestClient, state: str, provider: str = "dingtalk", **parameters: str
) -> Response:
    return client.get(
        f"/api/auth/oauth/{provider}/callback",
        params={"state": state, "code": "private-provider-code", **parameters},
        follow_redirects=False,
    )


def test_account_requires_session_and_never_caches_errors(
    account_client: TestClient,
) -> None:
    response = account_client.get(ACCOUNT_PATH)
    assert response.status_code == 401
    assert "no-store" in response.headers["cache-control"]
    assert "user-id" not in response.headers


@pytest.mark.parametrize("headers", [{}, {"X-CSRF-Token": "wrong"}])
def test_profile_requires_csrf(
    account_client: TestClient, headers: dict[str, str]
) -> None:
    login(account_client)
    response = account_client.patch(
        f"{ACCOUNT_PATH}/profile", json={"display_name": "Changed"}, headers=headers
    )
    assert response.status_code == 403
    assert (
        account_client.get(ACCOUNT_PATH).json()["user"]["display_name"] == "Local User"
    )


def test_link_start_rejects_cross_origin_even_with_csrf(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    login(account_client)
    response = account_client.post(
        f"{ACCOUNT_PATH}/identities/dingtalk/start",
        headers={**csrf(account_client), "Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert not account_env.redis.records


def test_profile_does_not_refresh_authentication_or_session_deadline(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    login(account_client)
    update_session(account_client, account_env, authenticated_at=time.time() - 600)
    before = session_data(account_client, account_env)
    cookie = account_client.cookies[COOKIE_NAME]
    response = account_client.patch(
        f"{ACCOUNT_PATH}/profile",
        json={"display_name": "Updated User", "avatar_url": None},
        headers=csrf(account_client),
    )
    assert response.status_code == 200
    assert response.json()["user"]["display_name"] == "Updated User"
    assert response.json()["reauthentication"]["required"] is True
    assert account_client.cookies[COOKIE_NAME] == cookie
    after = session_data(account_client, account_env)
    assert after["authenticated_at"] == before["authenticated_at"]
    assert after["login_expires_at"] == before["login_expires_at"]


@pytest.mark.parametrize(
    "body",
    [
        {"tenant_id": "attacker"},
        {"email": "attacker@example.com"},
        {"display_name": None},
        {"display_name": "\u0000"},
        {"avatar_url": "javascript:alert(1)"},
        {},
    ],
)
def test_profile_rejects_ownership_and_invalid_fields(
    account_client: TestClient, body: object
) -> None:
    login(account_client)
    response = account_client.patch(
        f"{ACCOUNT_PATH}/profile", json=body, headers=csrf(account_client)
    )
    assert response.status_code == 422
    assert "no-store" in response.headers["cache-control"]


def test_link_binds_state_to_account_and_preserves_main_user(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    login(account_client)
    before = session_data(account_client, account_env)
    old_cookie = account_client.cookies[COOKIE_NAME]
    state = start_account_oauth(account_client)
    attempt = json.loads(next(iter(account_env.redis.records.values()))[0])
    assert attempt["intent"] == "link"
    assert attempt["user_id"] == USER_ID
    assert attempt["account_id"] == TENANT_ID
    assert attempt["auth_version"] == 1
    assert attempt["session_digest"] != old_cookie
    assert account_env.providers["dingtalk"].interactive == [True]
    response = callback(account_client, state)
    assert response.status_code == 303, response.text
    assert urlsplit(response.headers["location"]).path == "/account"
    account = account_client.get(ACCOUNT_PATH).json()
    assert account["user"]["id"] == USER_ID
    assert account["user"]["display_name"] == "Local User"
    assert account["user"]["email"] == "local@example.com"
    assert {item["provider"] for item in account["identities"]} == {
        "google",
        "dingtalk",
    }
    assert account_client.cookies[COOKIE_NAME] != old_cookie
    after = session_data(account_client, account_env)
    assert after["auth_version"] == 2
    assert after["authenticated_at"] == before["authenticated_at"]
    assert after["login_expires_at"] == before["login_expires_at"]
    assert callback(account_client, state).status_code == 400


def test_link_rejects_identity_owned_by_another_account(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    seed_identity(account_env, user_id="other-user")
    login(account_client)
    state = start_account_oauth(account_client)
    response = callback(account_client, state)
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers["location"]).query)["account_error"] == [
        "identity_conflict"
    ]
    account = account_client.get(ACCOUNT_PATH).json()
    assert [item["provider"] for item in account["identities"]] == ["google"]
    assert session_data(account_client, account_env)["auth_version"] == 1
    with Session(account_env.engine) as db:
        assert len(db.scalars(select(User)).all()) == 2


def test_linked_oauth_and_new_password_both_sign_in_to_the_original_user(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    login(account_client)
    assert (
        callback(account_client, start_account_oauth(account_client)).status_code == 303
    )
    assert (
        account_client.put(
            f"{ACCOUNT_PATH}/password",
            json={"username": "alice", "password": PASSWORD},
            headers=csrf(account_client),
        ).status_code
        == 200
    )
    assert (
        account_client.post(
            "/api/auth/logout", headers=csrf(account_client)
        ).status_code
        == 204
    )
    linked_login = login(account_client, "dingtalk")
    assert linked_login["user"]["id"] == USER_ID
    assert linked_login["user"]["account_id"] == TENANT_ID
    assert linked_login["user"]["tenant_id"] == TENANT_ID
    assert (
        account_client.post(
            "/api/auth/logout", headers=csrf(account_client)
        ).status_code
        == 204
    )
    password_login = account_client.post(
        "/api/auth/password/login",
        headers={"X-Requested-With": "XMLHttpRequest"},
        json={"username": "alice", "password": PASSWORD},
    )
    assert password_login.status_code == 200
    assert password_login.json()["user"]["id"] == USER_ID
    assert password_login.json()["user"]["provider"] == "password"
    with Session(account_env.engine) as db:
        assert len(db.scalars(select(User)).all()) == 1


@pytest.mark.parametrize("operation", ["link", "unlink", "password"])
def test_sensitive_changes_require_recent_authentication(
    account_client: TestClient, account_env: AccountEnvironment, operation: str
) -> None:
    identity = seed_identity(account_env)
    login(account_client)
    update_session(account_client, account_env, authenticated_at=time.time() - 600)
    headers = csrf(account_client)
    if operation == "link":
        response = account_client.post(
            f"{ACCOUNT_PATH}/identities/dingtalk/start", headers=headers
        )
    elif operation == "unlink":
        response = account_client.delete(
            f"{ACCOUNT_PATH}/identities/{identity}", headers=headers
        )
    else:
        response = account_client.put(
            f"{ACCOUNT_PATH}/password",
            json={"username": "alice", "password": NEW_PASSWORD},
            headers=headers,
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "reauthentication_required"
    assert not account_env.redis.records


def test_recent_authentication_is_rechecked_at_link_callback(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    login(account_client)
    state = start_account_oauth(account_client)
    update_session(account_client, account_env, authenticated_at=time.time() - 600)
    response = callback(account_client, state)
    assert response.status_code in {303, 403}
    if response.status_code == 303:
        assert parse_qs(urlsplit(response.headers["location"]).query)[
            "account_error"
        ] == ["reauthentication_required"]
    assert not account_env.providers["dingtalk"].calls
    assert len(account_client.get(ACCOUNT_PATH).json()["identities"]) == 1


@pytest.mark.parametrize(
    "changed", ["session", "user", "account", "version", "provider"]
)
def test_callback_rejects_changed_account_context_before_provider_exchange(
    account_client: TestClient, account_env: AccountEnvironment, changed: str
) -> None:
    login(account_client)
    state = start_account_oauth(account_client)
    if changed == "session":
        old_id = account_client.cookies[COOKIE_NAME]
        new_id = account_env.auth.store.new_id()
        account_env.auth.store.records[new_id] = account_env.auth.store.records.pop(
            old_id
        )
        account_client.cookies.set(
            COOKIE_NAME, new_id, domain="testserver.local", path="/"
        )
    elif changed == "user":
        update_session(account_client, account_env, user_id="other-user")
    elif changed == "account":
        update_session(account_client, account_env, account_id="another-account")
    elif changed == "version":
        with Session(account_env.engine) as db, db.begin():
            db.get(User, USER_ID).auth_version += 1
    else:
        seed_identity(account_env)
        update_session(account_client, account_env, provider="dingtalk")
    response = callback(account_client, state)
    assert response.status_code in {303, 400, 401, 403, 409}
    assert not account_env.providers["dingtalk"].calls
    assert not account_env.redis.records
    assert callback(account_client, state).status_code == 400


def test_oauth_reauth_verifies_existing_identity_and_preserves_deadline(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    login(account_client)
    update_session(account_client, account_env, authenticated_at=time.time() - 600)
    before = session_data(account_client, account_env)
    state = start_account_oauth(account_client, "google", reauth=True)
    response = callback(account_client, state, "google")
    assert response.status_code == 303
    after = session_data(account_client, account_env)
    assert after["authenticated_at"] > before["authenticated_at"]
    assert after["login_expires_at"] == before["login_expires_at"]
    assert (
        account_client.get(ACCOUNT_PATH).json()["reauthentication"]["required"] is False
    )


def test_oauth_reauth_cannot_switch_to_different_identity(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    login(account_client)
    update_session(account_client, account_env, authenticated_at=time.time() - 600)
    before = session_data(account_client, account_env)
    state = start_account_oauth(account_client, "google", reauth=True)
    account_env.providers["google"].subject = "someone-else"
    response = callback(account_client, state, "google")
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers["location"]).query)["account_error"] == [
        "identity_not_linked"
    ]
    assert (
        session_data(account_client, account_env)["authenticated_at"]
        == before["authenticated_at"]
    )
    assert account_client.get(ACCOUNT_PATH).json()["user"]["id"] == USER_ID


def test_unlink_last_available_provider_is_rejected(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    seed_identity(account_env)
    account_env.auth.settings.auth.dingtalk.enabled = False
    login(account_client)
    response = account_client.delete(
        f"{ACCOUNT_PATH}/identities/google-identity", headers=csrf(account_client)
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "last_login_method"


@pytest.mark.parametrize("current", [False, True])
def test_unlink_rotates_or_logs_out_and_invalidates_other_sessions(
    account_client: TestClient, account_env: AccountEnvironment, current: bool
) -> None:
    identity = seed_identity(account_env)
    login(account_client)
    with TestClient(account_env.auth.app, base_url="https://testserver") as other:
        login(other)
        before = session_data(account_client, account_env)
        target = "google-identity" if current else identity
        response = account_client.delete(
            f"{ACCOUNT_PATH}/identities/{target}", headers=csrf(account_client)
        )
        assert response.status_code == 200
        assert response.json()["requires_login"] is current
        assert other.get(SESSION_PATH).json()["authenticated"] is False
    assert account_client.get(SESSION_PATH).json()["authenticated"] is not current
    if not current:
        after = session_data(account_client, account_env)
        assert after["authenticated_at"] == before["authenticated_at"]
        assert after["login_expires_at"] == before["login_expires_at"]


def test_first_password_and_change_keep_same_user_and_require_old_password(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    login(account_client)
    response = account_client.put(
        f"{ACCOUNT_PATH}/password",
        json={"username": "alice", "password": PASSWORD},
        headers=csrf(account_client),
    )
    assert response.status_code == 200
    account = account_client.get(ACCOUNT_PATH).json()
    assert account["user"]["id"] == USER_ID
    assert (
        next(item for item in account["identities"] if item["provider"] == "password")[
            "username"
        ]
        == "alice"
    )
    for current_password in (None, "wrong-password"):
        body = {"password": NEW_PASSWORD}
        if current_password:
            body["current_password"] = current_password
        response = account_client.put(
            f"{ACCOUNT_PATH}/password", json=body, headers=csrf(account_client)
        )
        assert response.status_code == 400
    response = account_client.put(
        f"{ACCOUNT_PATH}/password",
        json={"password": NEW_PASSWORD, "current_password": PASSWORD},
        headers=csrf(account_client),
    )
    assert response.status_code == 200
    assert session_data(account_client, account_env)["auth_version"] == 3


def test_password_reauth_is_limited_and_does_not_extend_login_deadline(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    seed_identity(account_env, "password", subject="alice")
    login(account_client)
    update_session(account_client, account_env, authenticated_at=time.time() - 600)
    before = session_data(account_client, account_env)
    response = account_client.post(
        f"{ACCOUNT_PATH}/reauth/password",
        json={"password": PASSWORD},
        headers=csrf(account_client),
    )
    assert response.status_code == 200
    after = session_data(account_client, account_env)
    assert after["authenticated_at"] > before["authenticated_at"]
    assert after["login_expires_at"] == before["login_expires_at"]
    assert account_env.redis.attempts.calls
    account_env.auth.settings.auth.password.rate_limit_attempts = 1
    response = account_client.post(
        f"{ACCOUNT_PATH}/reauth/password",
        json={"password": PASSWORD},
        headers=csrf(account_client),
    )
    assert response.status_code == 429


@pytest.mark.parametrize("operation", ["password_reauth", "oauth_link", "oauth_reauth"])
def test_security_operations_preserve_workspace_context(
    account_client: TestClient, account_env: AccountEnvironment, operation: str
) -> None:
    if operation == "password_reauth":
        seed_identity(account_env, "password", subject="alice")
    account_id = seed_workspace(account_env)
    login(account_client)
    update_session(account_client, account_env, account_id=account_id)
    before = session_data(account_client, account_env)
    old_cookie = account_client.cookies[COOKIE_NAME]
    if operation == "password_reauth":
        response = account_client.post(
            f"{ACCOUNT_PATH}/reauth/password",
            json={"password": PASSWORD},
            headers=csrf(account_client),
        )
        assert response.status_code == 200, response.text
        assert response.json()["user"]["account_id"] == account_id
    else:
        reauth = operation == "oauth_reauth"
        provider = "google" if reauth else "dingtalk"
        state = start_account_oauth(account_client, provider, reauth=reauth)
        response = callback(account_client, state, provider)
        assert response.status_code == 303, response.text
        assert parse_qs(urlsplit(response.headers["location"]).query) == {
            "account_action": ["reauthenticated" if reauth else "linked"]
        }
    after = session_data(account_client, account_env)
    assert account_client.cookies[COOKIE_NAME] != old_cookie
    assert after["account_id"] == account_id
    assert after["login_expires_at"] == before["login_expires_at"]
    current = account_client.get(ACCOUNT_PATH).json()
    assert current["account"]["id"] == account_id
    assert current["account"]["structure"] == "workspace"
    assert current["user"]["id"] == USER_ID
    assert current["user"]["account_id"] == account_id
    assert current["user"]["tenant_id"] == account_id


@pytest.mark.parametrize("interruption", ["membership_removed", "account_disabled"])
def test_password_reauth_rechecks_workspace_access_after_verification(
    account_client: TestClient,
    account_env: AccountEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    seed_identity(account_env, "password", subject="alice")
    account_id = seed_workspace(account_env)
    login(account_client)
    update_session(account_client, account_env, account_id=account_id)
    sid = account_client.cookies[COOKIE_NAME]
    headers = csrf(account_client)
    repository = account_env.auth.app.dependency_overrides[get_password_repository]()
    original_authenticate = repository.authenticate

    async def authenticate_then_revoke_access(
        username: str, password: str
    ) -> User | None:
        user = await original_authenticate(username, password)
        with Session(account_env.engine) as db, db.begin():
            if interruption == "membership_removed":
                db.delete(db.get(AccountMember, (account_id, USER_ID)))
            else:
                db.get(Account, account_id).is_active = False
        return user

    monkeypatch.setattr(repository, "authenticate", authenticate_then_revoke_access)
    response = account_client.post(
        f"{ACCOUNT_PATH}/reauth/password", json={"password": PASSWORD}, headers=headers
    )
    assert response.status_code == 401, response.text
    assert response.json()["detail"]["code"] == "account_unavailable"
    assert "set-cookie" not in response.headers
    assert not (set(account_env.auth.store.records) - {sid})
    assert account_client.get(SESSION_PATH).json()["authenticated"] is False


@pytest.mark.parametrize(
    "path,body",
    [
        ("password", {"password": PASSWORD * 100}),
        ("password", {"password": PASSWORD, "extra": PASSWORD}),
        ("password", {"password": {"secret": PASSWORD}}),
        ("reauth/password", {"password": {"secret": PASSWORD}}),
        ("reauth/password", {"password": PASSWORD, "extra": PASSWORD}),
    ],
)
def test_account_validation_never_reflects_password(
    account_client: TestClient, path: str, body: object
) -> None:
    login(account_client)
    response = account_client.request(
        "POST" if path.startswith("reauth") else "PUT",
        f"{ACCOUNT_PATH}/{path}",
        json=body,
        headers=csrf(account_client),
    )
    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert all("input" not in item for item in response.json()["detail"])
    assert "no-store" in response.headers["cache-control"]


@pytest.mark.parametrize("operation", ["link", "password", "unlink"])
def test_committed_credential_change_survives_session_failure_but_old_cookie_is_invalid(
    account_client: TestClient,
    account_env: AccountEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    identity = seed_identity(account_env) if operation == "unlink" else None
    login(account_client)
    state = start_account_oauth(account_client) if operation == "link" else None
    headers = csrf(account_client)
    monkeypatch.setattr(
        account_env.auth.store,
        "_write",
        AsyncMock(side_effect=RedisConnectionError("test rotation outage")),
    )
    if operation == "link":
        response = callback(account_client, state)
    elif operation == "password":
        response = account_client.put(
            f"{ACCOUNT_PATH}/password",
            json={"username": "alice", "password": PASSWORD},
            headers=headers,
        )
    else:
        response = account_client.delete(
            f"{ACCOUNT_PATH}/identities/{identity}", headers=headers
        )
    assert response.status_code == 503
    with Session(account_env.engine) as db:
        assert db.get(User, USER_ID).auth_version == 2
        providers = set(
            db.scalars(
                select(UserIdentity.provider).where(UserIdentity.user_id == USER_ID)
            )
        )
        assert providers == (
            {"google", "dingtalk"}
            if operation == "link"
            else {"google", "password"}
            if operation == "password"
            else {"google"}
        )
    assert account_client.get(SESSION_PATH).json()["authenticated"] is False


def test_application_login_deadline_cannot_be_extended_by_rotation(
    account_client: TestClient, account_env: AccountEnvironment
) -> None:
    login(account_client)
    deadline = time.time() + 60
    update_session(account_client, account_env, login_expires_at=deadline)
    state = start_account_oauth(account_client)
    assert callback(account_client, state).status_code == 303
    assert session_data(account_client, account_env)["login_expires_at"] == deadline
    update_session(account_client, account_env, login_expires_at=time.time() - 1)
    assert account_client.get(ACCOUNT_PATH).status_code == 401
    assert account_client.get(SESSION_PATH).json()["authenticated"] is False


@pytest.mark.parametrize("interruption", ["revoked", "expired", "outage"])
def test_password_reauth_does_not_revive_source_session_lost_during_verification(
    account_client: TestClient,
    account_env: AccountEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    seed_identity(account_env, "password", subject="alice")
    login(account_client)
    deadline = time.time() + 60
    update_session(account_client, account_env, login_expires_at=deadline)
    sid = account_client.cookies[COOKIE_NAME]
    headers = csrf(account_client)
    repository = account_env.auth.app.dependency_overrides[get_password_repository]()
    original_authenticate = repository.authenticate
    original_read = account_env.auth.store._read

    async def interrupted_authenticate(username: str, password: str) -> User | None:
        user = await original_authenticate(username, password)
        if interruption == "revoked":
            account_env.auth.store.records.pop(sid)
        elif interruption == "expired":
            monkeypatch.setattr(time, "time", lambda: deadline + 1)
        else:
            monkeypatch.setattr(
                account_env.auth.store,
                "_read",
                AsyncMock(side_effect=RedisConnectionError("source outage")),
            )
        return user

    monkeypatch.setattr(repository, "authenticate", interrupted_authenticate)
    response = account_client.post(
        f"{ACCOUNT_PATH}/reauth/password", json={"password": PASSWORD}, headers=headers
    )
    assert response.status_code == (503 if interruption == "outage" else 401), (
        response.text
    )
    assert "set-cookie" not in response.headers
    assert not (set(account_env.auth.store.records) - {sid})
    monkeypatch.setattr(account_env.auth.store, "_read", original_read)
    if interruption != "outage":
        assert account_client.get(SESSION_PATH).json()["authenticated"] is False


@pytest.mark.parametrize("operation", ["link", "password", "unlink"])
def test_revocation_after_database_commit_cannot_issue_replacement_session(
    account_client: TestClient,
    account_env: AccountEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    identity = seed_identity(account_env) if operation == "unlink" else None
    login(account_client)
    state = start_account_oauth(account_client) if operation == "link" else None
    sid = account_client.cookies[COOKIE_NAME]
    headers = csrf(account_client)
    method = {
        "link": "link_identity",
        "password": "set_password",
        "unlink": "unlink_identity",
    }[operation]
    original = getattr(account_env.accounts, method)

    async def commit_then_revoke(*args: object, **kwargs: object) -> User:
        user = await original(*args, **kwargs)
        account_env.auth.store.records.pop(sid)
        return user

    monkeypatch.setattr(account_env.accounts, method, commit_then_revoke)
    if operation == "link":
        response = callback(account_client, state)
    elif operation == "password":
        response = account_client.put(
            f"{ACCOUNT_PATH}/password",
            json={"username": "alice", "password": PASSWORD},
            headers=headers,
        )
    else:
        response = account_client.delete(
            f"{ACCOUNT_PATH}/identities/{identity}", headers=headers
        )
    if response.status_code == 303:
        assert parse_qs(urlsplit(response.headers["location"]).query)[
            "account_error"
        ] == ["session_changed"]
    else:
        assert response.status_code == 401, response.text
    assert "set-cookie" not in response.headers
    assert not account_env.auth.store.records
    with Session(account_env.engine) as db:
        assert db.get(User, USER_ID).auth_version == 2
    assert account_client.get(SESSION_PATH).json()["authenticated"] is False


@pytest.mark.parametrize("interruption", ["revoked", "expired", "outage"])
def test_oauth_link_checks_source_session_again_after_provider_exchange(
    account_client: TestClient,
    account_env: AccountEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    interruption: str,
) -> None:
    login(account_client)
    deadline = time.time() + 60
    update_session(account_client, account_env, login_expires_at=deadline)
    state = start_account_oauth(account_client)
    sid = account_client.cookies[COOKIE_NAME]
    provider = account_env.providers["dingtalk"]
    original = provider.authenticate

    async def authenticate_then_interrupt(
        code: str, *, nonce: str, code_verifier: str
    ) -> ProviderIdentity:
        identity = await original(code, nonce=nonce, code_verifier=code_verifier)
        if interruption == "revoked":
            account_env.auth.store.records.pop(sid)
        elif interruption == "expired":
            monkeypatch.setattr(time, "time", lambda: deadline + 1)
        else:
            monkeypatch.setattr(
                account_env.auth.store,
                "_read",
                AsyncMock(side_effect=RedisConnectionError("source outage")),
            )
        return identity

    monkeypatch.setattr(provider, "authenticate", authenticate_then_interrupt)
    response = callback(account_client, state)
    if interruption == "outage":
        assert response.status_code == 503
    else:
        assert response.status_code == 303
        assert parse_qs(urlsplit(response.headers["location"]).query)[
            "account_error"
        ] == ["session_changed"]
    with Session(account_env.engine) as db:
        assert db.get(User, USER_ID).auth_version == 1
        assert set(db.scalars(select(UserIdentity.provider))) == {"google"}
    assert not (set(account_env.auth.store.records) - {sid})
