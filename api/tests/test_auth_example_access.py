"""Authorization must run before teaching routes read or mutate cached data."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch
from redis_fastapi import get_async_redis, get_cache_backend, get_session_store

from api.auth.dependencies import get_user_repository, require_auth_user
from api.auth.example_access import authorize_examples
from api.auth.schemas import AuthUser
from api.deps import get_db
from api.routes.examples import cache, example_router

OWNED_ID = str(UUID(int=1))
OTHER_ID = str(UUID(int=2))
BASE_PATH = "/api/examples/cache"


@dataclass
class ExampleEnvironment:
    app: FastAPI
    user: AuthUser
    users: MagicMock
    redis_resolver: AsyncMock
    db_resolver: AsyncMock
    cache_resolver: AsyncMock
    session_resolver: AsyncMock

    def assert_no_service_access(self) -> None:
        self.redis_resolver.assert_not_awaited()
        self.db_resolver.assert_not_awaited()
        self.cache_resolver.assert_not_awaited()
        self.session_resolver.assert_not_awaited()


@pytest.fixture
def example_env(monkeypatch: MonkeyPatch) -> ExampleEnvironment:
    monkeypatch.setattr(cache.settings.app, "env", "local")
    monkeypatch.setattr(cache.settings, "repo_type", "postgres")
    user = AuthUser(
        id="local-user",
        tenant_id="local-tenant",
        provider="google",
        display_name="Test User",
    )

    async def owns(kind: str, resource_id: str, current_user: AuthUser) -> bool:
        assert kind == "conversation"
        assert current_user is user
        return resource_id == OWNED_ID

    users = MagicMock(owns=AsyncMock(side_effect=owns))
    redis_resolver = AsyncMock(
        side_effect=AssertionError("Redis resolved before authorization")
    )
    db_resolver = AsyncMock(
        side_effect=AssertionError("Database resolved before authorization")
    )
    cache_resolver = AsyncMock(
        side_effect=AssertionError("Cache backend resolved before authorization")
    )
    session_resolver = AsyncMock(
        side_effect=AssertionError("Session store resolved by disabled teaching route")
    )
    app = FastAPI()
    app.include_router(
        example_router,
        prefix="/api/examples",
        dependencies=[Depends(authorize_examples)],
    )
    app.dependency_overrides[require_auth_user] = lambda: user
    app.dependency_overrides[get_user_repository] = lambda: users

    async def get_redis_override() -> object:
        return await redis_resolver()

    async def get_db_override() -> object:
        return await db_resolver()

    async def get_cache_override() -> object:
        return await cache_resolver()

    async def get_session_override() -> object:
        return await session_resolver()

    app.dependency_overrides[get_async_redis] = get_redis_override
    app.dependency_overrides[get_db] = get_db_override
    app.dependency_overrides[get_cache_backend] = get_cache_override
    app.dependency_overrides[get_session_store] = get_session_override
    return ExampleEnvironment(
        app, user, users, redis_resolver, db_resolver, cache_resolver, session_resolver
    )


@pytest.fixture
def example_client(example_env: ExampleEnvironment) -> Iterator[TestClient]:
    with TestClient(example_env.app) as client:
        yield client


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("GET", f"/conversations/{OTHER_ID}", None),
        ("PATCH", f"/conversations/{OTHER_ID}", {"title": "Hijacked title"}),
        ("GET", f"/conversations/{OTHER_ID}/hot", None),
        ("GET", f"/sdk/cache-backend/conversations/{OTHER_ID}", None),
        ("DELETE", f"/sdk/cache-backend/conversations/{OTHER_ID}", None),
    ],
)
def test_foreign_resource_returns_not_found_before_cache_or_database_resolution(
    example_client: TestClient,
    example_env: ExampleEnvironment,
    method: str,
    suffix: str,
    payload: dict[str, object] | None,
) -> None:
    response = example_client.request(method, BASE_PATH + suffix, json=payload)
    assert response.status_code == 404
    assert response.json() == {"detail": "Resource not found"}
    example_env.users.owns.assert_awaited_once_with(
        "conversation", OTHER_ID, example_env.user
    )
    example_env.assert_no_service_access()


def test_batch_checks_every_resource_before_accessing_cached_values(
    example_client: TestClient, example_env: ExampleEnvironment
) -> None:
    response = example_client.post(
        BASE_PATH + "/conversations/batch", json={"ids": [OWNED_ID, OWNED_ID, OTHER_ID]}
    )
    assert response.status_code == 404
    assert [call.args[1] for call in example_env.users.owns.await_args_list] == [
        OWNED_ID,
        OTHER_ID,
    ]
    example_env.assert_no_service_access()


@pytest.mark.parametrize(
    "payload",
    [
        {"ids": []},
        {"ids": ["not-a-uuid"]},
        {"ids": [OWNED_ID] * 51},
        {"unexpected": "private-input"},
        [OWNED_ID],
    ],
)
def test_invalid_batch_is_rejected_without_service_access_or_echoing_body(
    example_client: TestClient, example_env: ExampleEnvironment, payload: object
) -> None:
    response = example_client.post(BASE_PATH + "/conversations/batch", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid conversation batch"}
    example_env.users.owns.assert_not_awaited()
    example_env.assert_no_service_access()


def test_malformed_json_is_rejected_without_service_access(
    example_client: TestClient, example_env: ExampleEnvironment
) -> None:
    response = example_client.post(
        BASE_PATH + "/conversations/batch",
        content='{"ids":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    example_env.users.owns.assert_not_awaited()
    example_env.assert_no_service_access()


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("GET", "/sdk/session", None),
        ("PUT", "/sdk/session", {"theme": "dark", "language": "en"}),
        ("DELETE", "/sdk/session", None),
        ("GET", "/sdk/session/required", None),
        ("POST", "/sdk/session/rotate", None),
    ],
)
def test_session_teaching_endpoints_cannot_modify_authentication_session(
    example_client: TestClient,
    example_env: ExampleEnvironment,
    method: str,
    suffix: str,
    payload: dict[str, object] | None,
) -> None:
    response = example_client.request(method, BASE_PATH + suffix, json=payload)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}
    example_env.users.owns.assert_not_awaited()
    example_env.assert_no_service_access()


@pytest.mark.parametrize(
    "suffix", [f"/conversations/{OWNED_ID}", "/sdk/session/rotate"]
)
def test_production_hides_examples_before_resource_or_service_access(
    example_client: TestClient,
    example_env: ExampleEnvironment,
    monkeypatch: MonkeyPatch,
    suffix: str,
) -> None:
    monkeypatch.setattr(cache.settings.app, "env", "prod")
    method = "POST" if suffix.endswith("rotate") else "GET"
    response = example_client.request(method, BASE_PATH + suffix)
    assert response.status_code == 404
    example_env.users.owns.assert_not_awaited()
    example_env.assert_no_service_access()


def test_owned_cache_hit_remains_available_after_authorization(
    example_client: TestClient, example_env: ExampleEnvironment
) -> None:
    snapshot = cache.ConversationSnapshot(
        id=OWNED_ID, title="Owned", is_archived=False, updated_at=None
    )
    redis = MagicMock(get=AsyncMock(return_value=snapshot.model_dump_json()))
    example_env.redis_resolver.side_effect = None
    example_env.redis_resolver.return_value = redis
    example_env.db_resolver.side_effect = None
    example_env.db_resolver.return_value = MagicMock(execute=AsyncMock())
    response = example_client.get(BASE_PATH + f"/conversations/{OWNED_ID}")
    assert response.status_code == 200
    assert response.json()["id"] == OWNED_ID
    example_env.users.owns.assert_awaited_once_with(
        "conversation", OWNED_ID, example_env.user
    )
    redis.get.assert_awaited_once()
    example_env.db_resolver.return_value.execute.assert_not_awaited()
