"""Exercise SDK session middleware and cookies without connecting to Redis.

The in-memory store replaces only persistence. Session serialization, identifier
rotation, revocation, request dependencies and response cookies use the real SDK.
Expiration and Redis command compatibility require separate integration tests.
"""

from collections.abc import Iterator
from http.cookies import SimpleCookie
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis.exceptions import ConnectionError as RedisConnectionError
from redis_fastapi import RedisSettings, SessionStore, get_session_store, get_settings
from redis_fastapi.session_backend import Deadline

from api.routes.examples import cache

SESSION_PATH = "/api/examples/cache/sdk/session"
COOKIE_NAME = "redis_sdk_test_session"
DEFAULT_PREFERENCES = {"theme": "light", "language": "zh"}
PREFERENCES = {"theme": "dark", "language": "en"}


class MemorySessionStore(SessionStore):
    """Reuse the SDK lifecycle while substituting its storage primitives."""

    def __init__(self) -> None:
        super().__init__(idle_ttl=300, absolute_ttl=1800)
        self.records: dict[str, tuple[str, int]] = {}
        self.indexes: dict[str, dict[str, str]] = {}
        self.operations: list[str] = []
        self.resolutions = 0

    async def _read(
        self, session_id: str, *, refresh_idle: int | None
    ) -> tuple[str | None, int | Deadline]:
        self.operations.append("read")
        return self.records.get(session_id, (None, Deadline.ABSENT))

    async def _write(
        self, session_id: str, payload: str, *, idle: int, absolute: int | None
    ) -> None:
        self.operations.append("write")
        if absolute is not None:
            self.records[session_id] = (payload, absolute)
        elif session_id in self.records:
            self.records[session_id] = (payload, self.records[session_id][1])

    async def _expire(self, session_id: str, idle: int) -> None:
        self.operations.append("touch")

    async def _delete(self, session_id: str) -> None:
        self.operations.append("delete")
        self.records.pop(session_id, None)

    async def _index_add(
        self, subject: str, session_id: str, descriptor: str, absolute_remaining: int
    ) -> None:
        self.indexes.setdefault(subject, {})[session_id] = descriptor

    async def _index_remove(self, subject: str, session_id: str) -> None:
        self.indexes.get(subject, {}).pop(session_id, None)

    async def _delete_many(self, session_ids: list[str]) -> int:
        removed = sum(session_id in self.records for session_id in session_ids)
        for session_id in session_ids:
            self.records.pop(session_id, None)
        return removed

    async def _index_clear(self, subject: str) -> None:
        self.indexes.pop(subject, None)

    async def _alive(self, session_ids: list[str]) -> set[str]:
        return set(session_ids) & self.records.keys()

    async def _index_members(self, subject: str) -> dict[str, str | bytes]:
        return dict(self.indexes.get(subject, {}))

    async def _index_size(self, subject: str) -> int:
        return len(self.indexes.get(subject, {}))


@pytest.fixture
def sdk_settings(monkeypatch: MonkeyPatch, tmp_path: Path) -> RedisSettings:
    # Like conftest.py, never ask Pydantic Settings to read the developer's .env.
    monkeypatch.chdir(tmp_path)
    sdk_settings = get_settings()
    for name, value in {
        "session_cookie_name": COOKIE_NAME,
        "session_cookie_path": "/",
        "session_cookie_domain": None,
        "session_cookie_https_only": True,
        "session_cookie_same_site": "lax",
        "session_refresh_on_load": True,
        "session_always_save": False,
        "session_fail_closed": False,
        "session_principal_keys": ["user_id"],
        "rate_limit_default_limit": 0,
    }.items():
        monkeypatch.setattr(sdk_settings, name, value)
    return sdk_settings


@pytest.fixture
def store(sdk_settings: RedisSettings) -> MemorySessionStore:
    return MemorySessionStore()


@pytest.fixture
def app(monkeypatch: MonkeyPatch, store: MemorySessionStore) -> FastAPI:
    monkeypatch.setattr(cache.settings.app, "env", "local")
    app = FastAPI()
    cache.configure_sdk_examples(app)
    app.include_router(cache.cache_router, prefix="/api/examples")

    async def session_store_override(request: Request) -> SessionStore:
        # The middleware calls override(request), before FastAPI resolves DI.
        store.resolutions += 1
        return store

    app.dependency_overrides[get_session_store] = session_store_override

    @app.get("/outside-session")
    async def outside_session() -> dict[str, bool]:
        return {"ok": True}

    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # No application lifespan: the real middleware uses the overridden store.
    with TestClient(app) as client:
        yield client


def test_first_read_does_not_create_session(
    client: TestClient, store: MemorySessionStore
) -> None:
    response = client.get(SESSION_PATH)

    assert response.status_code == 200
    assert response.json() == DEFAULT_PREFERENCES
    assert "set-cookie" not in response.headers
    assert "no-store" in response.headers["cache-control"]
    assert not store.records
    assert not store.operations


def test_preferences_persist_with_scoped_development_cookie(
    client: TestClient, store: MemorySessionStore
) -> None:
    response = client.put(SESSION_PATH, json=PREFERENCES)

    assert response.status_code == 200
    assert response.json() == PREFERENCES
    assert "no-store" in response.headers["cache-control"]
    cookie = SimpleCookie(response.headers["set-cookie"])[COOKIE_NAME]
    assert cookie["path"] == SESSION_PATH
    assert cookie["httponly"]
    assert cookie["samesite"].lower() == "lax"
    assert not cookie["secure"]
    assert not cookie["domain"]
    assert cookie["max-age"] == "1800"
    assert set(store.records) == {cookie.value}

    # TestClient's cookie jar must send the cookie on the subsequent HTTP call.
    read = client.get(SESSION_PATH)
    assert read.status_code == 200
    assert read.json() == PREFERENCES
    assert "set-cookie" not in read.headers


def test_sessions_are_isolated_between_clients(
    client: TestClient, app: FastAPI, store: MemorySessionStore
) -> None:
    client.put(SESSION_PATH, json=PREFERENCES)

    with TestClient(app) as other:
        assert other.get(SESSION_PATH).json() == DEFAULT_PREFERENCES
        other_preferences = {"theme": "light", "language": "en"}
        assert other.put(SESSION_PATH, json=other_preferences).status_code == 200
        assert other.get(SESSION_PATH).json() == other_preferences

    assert client.get(SESSION_PATH).json() == PREFERENCES
    assert len(store.records) == 2


@pytest.mark.parametrize("method, suffix", [("GET", "/required"), ("POST", "/rotate")])
def test_session_gate_rejects_missing_cookie(
    client: TestClient, store: MemorySessionStore, method: str, suffix: str
) -> None:
    response = client.request(method, SESSION_PATH + suffix)

    assert response.status_code == 401
    assert "set-cookie" not in response.headers
    assert not store.records


def test_session_gate_accepts_stored_anonymous_preferences(client: TestClient) -> None:
    client.put(SESSION_PATH, json=PREFERENCES)

    response = client.get(SESSION_PATH + "/required")

    assert response.status_code == 200
    assert response.json() == PREFERENCES


def test_rotate_invalidates_old_cookie_and_preserves_preferences(
    client: TestClient, app: FastAPI, store: MemorySessionStore
) -> None:
    client.put(SESSION_PATH, json=PREFERENCES)
    old_id = client.cookies[COOKIE_NAME]

    response = client.post(SESSION_PATH + "/rotate")

    assert response.status_code == 200
    assert response.json() == {"rotated": True}
    new_id = client.cookies[COOKIE_NAME]
    assert new_id != old_id
    assert old_id not in store.records
    assert set(store.records) == {new_id}
    assert client.get(SESSION_PATH + "/required").json() == PREFERENCES

    with TestClient(app) as stale_client:
        stale = stale_client.get(
            SESSION_PATH + "/required", headers={"Cookie": f"{COOKIE_NAME}={old_id}"}
        )
    assert stale.status_code == 401


def test_logout_revokes_record_and_clears_cookie(
    client: TestClient, store: MemorySessionStore
) -> None:
    client.put(SESSION_PATH, json=PREFERENCES)

    response = client.delete(SESSION_PATH)

    assert response.status_code == 204
    assert response.content == b""
    cookie = SimpleCookie(response.headers["set-cookie"])[COOKIE_NAME]
    assert cookie.value == ""
    assert cookie["max-age"] == "0"
    assert cookie["path"] == SESSION_PATH
    assert COOKIE_NAME not in client.cookies
    assert not store.records
    assert client.get(SESSION_PATH + "/required").status_code == 401
    assert client.get(SESSION_PATH).json() == DEFAULT_PREFERENCES
    assert client.delete(SESSION_PATH).status_code == 204


@pytest.mark.parametrize("path", ["/outside-session", SESSION_PATH + "-unrelated"])
def test_non_session_paths_do_not_resolve_store(
    client: TestClient, store: MemorySessionStore, path: str
) -> None:
    # Send a cookie explicitly: zero I/O must result from skip, not its absence.
    response = client.get(path, headers={"Cookie": f"{COOKIE_NAME}={'a' * 32}"})

    assert response.status_code == (200 if path == "/outside-session" else 404)
    assert store.resolutions == 0
    assert not store.operations


def test_production_session_request_does_not_resolve_store(
    client: TestClient, store: MemorySessionStore, monkeypatch: MonkeyPatch
) -> None:
    # Even if middleware was registered earlier in dev, the production guard
    # must run before a session load, and the route remains unavailable.
    monkeypatch.setattr(cache.settings.app, "env", "prod")

    response = client.get(SESSION_PATH, headers={"Cookie": f"{COOKIE_NAME}={'a' * 32}"})

    assert response.status_code == 404
    assert "set-cookie" not in response.headers
    assert store.resolutions == 0
    assert not store.operations


def test_failed_session_load_rejects_gate_as_unavailable(
    client: TestClient, store: MemorySessionStore, monkeypatch: MonkeyPatch
) -> None:
    client.put(SESSION_PATH, json=PREFERENCES)
    monkeypatch.setattr(
        store, "_read", AsyncMock(side_effect=RedisConnectionError("test outage"))
    )

    gated = client.get(SESSION_PATH + "/required")

    assert gated.status_code == 503
    assert "no-store" in gated.headers["cache-control"]
    assert "set-cookie" not in gated.headers
    # The ungated preference reader deliberately follows the SDK's default
    # anonymous fallback; an unavailable store must never bypass the gate.
    assert client.get(SESSION_PATH).json() == DEFAULT_PREFERENCES


def test_automatic_save_failure_does_not_report_a_successful_write(
    app: FastAPI, store: MemorySessionStore, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(
        store, "_write", AsyncMock(side_effect=RedisConnectionError("test outage"))
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put(SESSION_PATH, json=PREFERENCES)

    # Saving occurs at response.start, outside the endpoint's try/except.
    assert response.status_code == 500
    assert "set-cookie" not in response.headers
    assert not store.records


def test_failed_rotation_can_revoke_old_session_before_creation_fails(
    client: TestClient, store: MemorySessionStore, monkeypatch: MonkeyPatch
) -> None:
    client.put(SESSION_PATH, json=PREFERENCES)
    old_id = client.cookies[COOKIE_NAME]
    monkeypatch.setattr(
        store, "_write", AsyncMock(side_effect=RedisConnectionError("test outage"))
    )

    response = client.post(SESSION_PATH + "/rotate")

    assert response.status_code == 503
    assert old_id not in store.records
    assert "set-cookie" not in response.headers
    # Rotation deletes first: failure is not a promise to preserve the old ID.
    assert client.get(SESSION_PATH + "/required").status_code == 401


def test_logout_failure_does_not_report_revocation_or_clear_cookie(
    client: TestClient, store: MemorySessionStore, monkeypatch: MonkeyPatch
) -> None:
    client.put(SESSION_PATH, json=PREFERENCES)
    old_id = client.cookies[COOKIE_NAME]
    monkeypatch.setattr(
        store, "_delete", AsyncMock(side_effect=RedisConnectionError("test outage"))
    )

    response = client.delete(SESSION_PATH)

    assert response.status_code == 503
    assert old_id in store.records
    assert client.cookies[COOKIE_NAME] == old_id
    assert "set-cookie" not in response.headers
