"""Header credentials are explicit service access, never a user identity."""

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from redis_fastapi import RedisSettings, SessionStore, get_session_store

from api.dependencies.auth import get_user_repository
from api.core.header_auth import HeaderAuthConfig
from api.core.auth_session import configure_auth_sessions
from api.core.config import Settings, get_settings, settings
from api.core.deps import ConfiguredAPIKeyHeader, CurrentUserDep, HeaderAuthDep
from api.core.request_context import RequestContextMiddleware
from api.routes.examples.auth_header import HEADER_EXAMPLE_PREFIX, header_auth_router
from test_redis_sdk_sessions import MemorySessionStore
from test_redis_sdk_sessions import sdk_settings as sdk_settings

KEY = "first-service-api-key-with-enough-entropy"
ROTATED_KEY = "second-service-api-key-with-enough-entropy"


@dataclass
class HeaderEnvironment:
    app: FastAPI
    config: Settings


@pytest.fixture
def header_env() -> HeaderEnvironment:
    config = settings.model_copy(deep=True)
    config.app.env = "local"
    config.auth.header = HeaderAuthConfig(enabled=True, keys=[SecretStr(KEY)])
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: config
    app.add_middleware(RequestContextMiddleware, config=config.request_context)
    app.include_router(header_auth_router, prefix="/api/examples")

    @app.get("/service")
    async def service(request: Request, principal: HeaderAuthDep) -> dict[str, object]:
        return {
            "scheme": principal.scheme,
            "user_authenticated": getattr(request.state, "authenticated", False),
        }

    return HeaderEnvironment(app, config)


@pytest.fixture
def header_client(header_env: HeaderEnvironment) -> Iterator[TestClient]:
    # Deliberately no session middleware or Redis / database setup.
    with TestClient(header_env.app) as client:
        yield client


@pytest.mark.parametrize("suffix", ["/ping", "/echo"])
def test_examples_require_header_and_do_not_echo_secrets(
    header_client: TestClient, suffix: str
) -> None:
    method = "POST" if suffix == "/echo" else "GET"
    payload = {"message": "hello"} if method == "POST" else None
    path = HEADER_EXAMPLE_PREFIX + suffix
    missing = header_client.request(method, path, json=payload)
    assert missing.status_code == 401
    assert missing.headers["cache-control"] == "no-store"
    response = header_client.request(
        method, path, json=payload, headers={"X-Api-Key": KEY}
    )
    assert response.status_code == 200
    assert response.json()["authentication"] == "api_key"
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert KEY not in response.text
    assert KEY not in str(response.headers)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Api-Key": ""},
        {"X-Api-Key": "wrong"},
        [("X-Api-Key", KEY), ("X-Api-Key", KEY)],
        [("X-Api-Key", KEY), ("x-api-key", "wrong")],
        {"Authorization": f"Bearer {KEY}"},
        {"Cookie": f"X-Api-Key={KEY}"},
    ],
)
def test_ambiguous_missing_or_wrong_credentials_are_unauthorized(
    header_client: TestClient, headers: dict[str, str] | list[tuple[str, str]]
) -> None:
    response = header_client.get("/service", headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid header credential"}
    assert response.headers["www-authenticate"] == "ApiKey"
    assert response.headers["cache-control"] == "no-store"
    assert KEY not in response.text


@pytest.mark.parametrize("enabled,keys", [(False, [KEY]), (True, []), (False, [])])
def test_disabled_or_unconfigured_header_authentication_fails_closed(
    header_client: TestClient,
    header_env: HeaderEnvironment,
    enabled: bool,
    keys: list[str],
) -> None:
    header_env.config.auth.header = HeaderAuthConfig(enabled=enabled, keys=keys)
    response = header_client.get("/service", headers={"X-Api-Key": KEY})
    assert response.status_code == 503
    assert response.json() == {"detail": "Header authentication is unavailable"}
    assert response.headers["cache-control"] == "no-store"


def test_custom_header_name_is_case_insensitive_and_replaces_default(
    header_client: TestClient, header_env: HeaderEnvironment
) -> None:
    header_env.config.auth.header.name = "X-Service-Key"
    assert header_client.get("/service", headers={"X-Api-Key": KEY}).status_code == 401
    response = header_client.get("/service", headers={"x-service-key": KEY})
    assert response.status_code == 200
    assert ConfiguredAPIKeyHeader("X-Service-Key").model.name == "X-Service-Key"


@pytest.mark.parametrize("key", [KEY, ROTATED_KEY])
def test_either_rotation_key_is_accepted(
    header_client: TestClient, header_env: HeaderEnvironment, key: str
) -> None:
    header_env.config.auth.header.keys = [SecretStr(KEY), SecretStr(ROTATED_KEY)]
    assert header_client.get("/service", headers={"X-Api-Key": key}).status_code == 200


def test_header_principal_does_not_trust_identity_assertions(
    header_client: TestClient,
) -> None:
    response = header_client.get(
        "/service",
        headers={
            "X-Api-Key": KEY,
            "User-ID": "forged-user",
            "Tenant-ID": "forged-tenant",
            "Request-ID": "header-test-request",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"scheme": "api_key", "user_authenticated": False}
    assert response.headers["request-id"] == "header-test-request"
    assert "user-id" not in response.headers
    assert "tenant-id" not in response.headers


def test_header_key_never_authorizes_a_session_protected_route(
    header_env: HeaderEnvironment, sdk_settings: RedisSettings
) -> None:
    app = header_env.app
    store = MemorySessionStore()
    users = AsyncMock()
    configure_auth_sessions(app, header_env.config)

    async def session_store_override(request: Request) -> SessionStore:
        return store

    app.dependency_overrides[get_session_store] = session_store_override
    app.dependency_overrides[get_user_repository] = lambda: users

    @app.get("/api/private")
    async def private(user: CurrentUserDep) -> dict[str, str]:
        return {"id": user.id}

    with TestClient(app) as client:
        response = client.get("/api/private", headers={"X-Api-Key": KEY})
    assert response.status_code == 401
    users.get.assert_not_awaited()
    assert not store.records


def test_examples_skip_session_storage_even_with_a_stale_browser_cookie(
    header_env: HeaderEnvironment, sdk_settings: RedisSettings
) -> None:
    app = header_env.app
    configure_auth_sessions(app, header_env.config)
    session_store = AsyncMock(side_effect=AssertionError("Session storage accessed"))

    async def session_store_override(request: Request) -> SessionStore:
        return await session_store()

    app.dependency_overrides[get_session_store] = session_store_override
    with TestClient(app) as client:
        client.cookies.set(sdk_settings.session_cookie_name, "a" * 64)
        response = client.post(
            HEADER_EXAMPLE_PREFIX + "/echo",
            json={"message": "without session or csrf"},
            headers={"X-Api-Key": KEY},
        )
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    session_store.assert_not_awaited()


@pytest.mark.parametrize("suffix", ["/ping", "/echo"])
def test_examples_are_hidden_in_production(
    header_client: TestClient, header_env: HeaderEnvironment, suffix: str
) -> None:
    header_env.config.app.env = "prod"
    method = "POST" if suffix == "/echo" else "GET"
    response = header_client.request(
        method, HEADER_EXAMPLE_PREFIX + suffix, json={"message": "hello"}
    )
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


def test_openapi_advertises_header_security(header_env: HeaderEnvironment) -> None:
    schema = header_env.app.openapi()
    scheme = schema["components"]["securitySchemes"]["HeaderAPIKey"]
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == settings.auth.header.name
    for suffix, method in (("/ping", "get"), ("/echo", "post")):
        operation = schema["paths"][HEADER_EXAMPLE_PREFIX + suffix][method]
        assert operation["security"] == [{"HeaderAPIKey": []}]


@pytest.mark.parametrize(
    "name",
    [
        "Authorization",
        "Cookie",
        "Set-Cookie",
        "User-ID",
        "Tenant-ID",
        "Account-ID",
        "aCcOuNt-Id",
        "Request-ID",
        "traceparent",
        "tracestate",
        "baggage",
        "X-CSRF-Token",
        "bad header",
        "bad\nheader",
    ],
)
def test_api_key_header_cannot_overlap_identity_or_protocol_headers(name: str) -> None:
    with pytest.raises(ValidationError):
        HeaderAuthConfig(name=name)


@pytest.mark.parametrize("key", ["", "short", " " * 32, "a" * 31 + "\n", "密" * 32])
def test_invalid_keys_are_rejected_without_error_disclosure(key: str) -> None:
    with pytest.raises(ValidationError) as error:
        HeaderAuthConfig(keys=[key])
    assert "input_value" not in str(error.value)


def test_configuration_redacts_api_keys() -> None:
    config = HeaderAuthConfig(enabled=True, keys=[KEY, ROTATED_KEY])
    assert KEY not in repr(config)
    assert KEY not in config.model_dump_json()
    assert ROTATED_KEY not in config.model_dump_json()
