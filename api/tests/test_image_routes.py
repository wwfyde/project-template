"""Image APIs with real cookie/CSRF and external API-key authorization."""

import json
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from redis_fastapi import SessionStore, get_session_store
from starlette.types import Message, Scope

from api.images.config import ImagesConfig, ImageServiceClient
from api.images.contracts import ImageProvider, ProviderInfo, ProviderInput
from api.images.service import ImageService
from api.images.store import InMemoryImageStore
from api.routes.images import image_service_router, images_router
from test_auth_routes import (
    COOKIE_NAME,
    AuthTestEnvironment,
    auth_env as auth_env,
    login,
)

KEY = "image-client-a-primary-with-enough-entropy"
ROTATED_KEY = "image-client-a-rotated-with-enough-entropy"
OTHER_KEY = "image-client-b-primary-with-enough-entropy"
EXTERNAL = "/api/v1/images"
BROWSER = "/api/images"


def png(color: tuple[int, int, int, int] = (20, 40, 60, 255)) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (8, 6), color).save(output, format="PNG")
    return output.getvalue()


class FakeImageProvider:
    info = ProviderInfo(
        id="gpt",
        label="Test GPT",
        configured=True,
        models=["fake-image"],
        default_model="fake-image",
        operations=["remove_background", "erase"],
        mask_mode="native",
    )

    def __init__(self) -> None:
        self.requests: list[ProviderInput] = []
        self.fail = False

    async def edit(self, request: ProviderInput) -> bytes:
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("private-provider-error-containing-api-key")
        return png((180, 100, 20, 128))


@dataclass
class ImageEnvironment:
    auth: AuthTestEnvironment
    service: ImageService
    provider: FakeImageProvider


@pytest.fixture
def image_env(auth_env: AuthTestEnvironment) -> ImageEnvironment:
    config = ImagesConfig(
        clients=[
            ImageServiceClient(id="client-a", keys=[KEY, ROTATED_KEY]),
            ImageServiceClient(id="client-b", keys=[OTHER_KEY]),
        ]
    )
    auth_env.settings.images = config
    provider = FakeImageProvider()
    providers: dict[str, ImageProvider] = {"gpt": provider}
    service = ImageService(InMemoryImageStore(), providers, config)
    auth_env.app.state.image_service = service
    auth_env.app.include_router(images_router, prefix="/api")
    auth_env.app.include_router(image_service_router, prefix="/api")
    return ImageEnvironment(auth_env, service, provider)


@pytest.fixture
def image_client(image_env: ImageEnvironment) -> Iterator[TestClient]:
    with TestClient(image_env.auth.app, base_url="https://testserver") as client:
        yield client


def upload(
    client: TestClient,
    prefix: str = EXTERNAL,
    headers: dict[str, str] | None = None,
    *,
    purpose: str = "image",
) -> dict[str, object]:
    response = client.post(
        f"{prefix}/assets",
        files={"file": ("photo.png", png(), "image/png")},
        data={"purpose": purpose},
        headers=headers or {"X-Api-Key": KEY},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_external_upload_edit_comments_and_private_content(
    image_client: TestClient,
) -> None:
    headers = {"X-Api-Key": KEY}
    original = upload(image_client)
    assert original["purpose"] == "image"
    assert original["content_url"].startswith(f"{EXTERNAL}/assets/")
    content = image_client.get(original["content_url"], headers=headers)
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/png"
    assert content.headers["cache-control"] == "private, no-store"
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.content.startswith(b"\x89PNG\r\n\x1a\n")
    download = image_client.get(
        original["content_url"] + "?download=true", headers=headers
    )
    assert download.headers["content-disposition"].startswith("attachment;")
    edited = image_client.post(
        f"{EXTERNAL}/assets/{original['id']}/edits",
        headers=headers,
        json={"operation": "resize", "width": 4, "height": 3},
    )
    assert edited.status_code == 201, edited.text
    result = edited.json()
    assert result["id"] != original["id"]
    assert result["parent_id"] == original["id"]
    assert (result["width"], result["height"]) == (4, 3)
    assert (
        image_client.get(original["content_url"], headers=headers).content
        == content.content
    )
    saved = image_client.post(
        f"{EXTERNAL}/assets/{result['id']}/comments",
        headers=headers,
        json={"text": "  Move the title  ", "x": 0.5, "y": 0.25},
    )
    assert saved.status_code == 201
    comment = saved.json()
    assert comment["text"] == "Move the title"
    comments = image_client.get(
        f"{EXTERNAL}/assets/{result['id']}/comments", headers=headers
    )
    assert comments.json() == [comment]
    deleted = image_client.delete(
        f"{EXTERNAL}/assets/{result['id']}/comments/{comment['id']}", headers=headers
    )
    assert deleted.status_code == 204
    assert not deleted.content
    assert (
        image_client.get(
            f"{EXTERNAL}/assets/{result['id']}/comments", headers=headers
        ).json()
        == []
    )


def test_browser_session_requires_csrf_for_upload_edit_comment_and_delete(
    image_client: TestClient,
) -> None:
    session = login(image_client)
    csrf = {"X-CSRF-Token": cast(str, session["csrf_token"])}
    denied = image_client.post(
        f"{BROWSER}/assets", files={"file": ("image.png", png())}
    )
    assert denied.status_code == 403
    original = upload(image_client, BROWSER, csrf)
    assert original["content_url"].startswith(BROWSER)
    asset_path = f"{BROWSER}/assets/{original['id']}"
    assert image_client.get(asset_path).status_code == 200
    for suffix, payload in (
        ("/edits", {"operation": "resize", "width": 4, "height": 3}),
        ("/comments", {"text": "A comment", "x": 0, "y": 0}),
    ):
        assert image_client.post(asset_path + suffix, json=payload).status_code == 403
        bad_origin = image_client.post(
            asset_path + suffix,
            json=payload,
            headers={**csrf, "Origin": "https://other.example"},
        )
        assert bad_origin.status_code == 403
        assert (
            image_client.post(
                asset_path + suffix, json=payload, headers=csrf
            ).status_code
            == 201
        )
    comment_id = image_client.get(asset_path + "/comments").json()[0]["id"]
    assert (
        image_client.delete(asset_path + f"/comments/{comment_id}").status_code == 403
    )
    assert (
        image_client.delete(
            asset_path + f"/comments/{comment_id}", headers=csrf
        ).status_code
        == 204
    )


def test_browser_and_service_clients_share_store_but_not_owners(
    image_client: TestClient,
) -> None:
    external = upload(image_client)
    session = login(image_client)
    browser = upload(
        image_client, BROWSER, {"X-CSRF-Token": cast(str, session["csrf_token"])}
    )
    assert [item["id"] for item in image_client.get(BROWSER + "/assets").json()] == [
        browser["id"]
    ]
    assert [
        item["id"]
        for item in image_client.get(
            EXTERNAL + "/assets", headers={"X-Api-Key": KEY}
        ).json()
    ] == [external["id"]]
    for prefix, asset_id, headers in (
        (BROWSER, external["id"], {}),
        (EXTERNAL, browser["id"], {"X-Api-Key": KEY}),
        (
            EXTERNAL,
            external["id"],
            {"X-Api-Key": OTHER_KEY, "User-ID": "client-a", "Account-ID": "client-a"},
        ),
    ):
        for suffix in ("", "/content", "/comments"):
            response = image_client.get(
                f"{prefix}/assets/{asset_id}{suffix}", headers=headers
            )
            assert response.status_code == 404
            assert response.json()["detail"]["code"] == "image_not_found"


def test_rotated_service_key_keeps_asset_namespace(image_client: TestClient) -> None:
    original = upload(image_client)
    response = image_client.get(
        f"{EXTERNAL}/assets/{original['id']}", headers={"X-Api-Key": ROTATED_KEY}
    )
    assert response.status_code == 200
    assert response.json() == original
    assert (
        image_client.get(EXTERNAL + "/assets", headers={"X-Api-Key": OTHER_KEY}).json()
        == []
    )


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Api-Key": "wrong"},
        {"X-Api-Key": ""},
        [("X-Api-Key", KEY), ("x-api-key", KEY)],
        [("X-Api-Key", KEY), ("x-api-key", OTHER_KEY)],
        {"Authorization": f"Bearer {KEY}"},
        {"User-ID": "client-a", "Tenant-ID": "client-a"},
    ],
)
def test_external_auth_rejects_missing_wrong_or_ambiguous_keys(
    image_client: TestClient, headers: dict[str, str] | list[tuple[str, str]]
) -> None:
    response = image_client.get(EXTERNAL + "/providers", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_api_key"
    assert response.headers["cache-control"] == "no-store"
    assert KEY not in response.text


def test_service_key_cannot_authorize_browser_and_cookie_cannot_authorize_service(
    image_client: TestClient,
) -> None:
    assert (
        image_client.get(BROWSER + "/providers", headers={"X-Api-Key": KEY}).status_code
        == 401
    )
    assert image_client.get(BROWSER + "/providers").status_code == 401
    login(image_client)
    assert image_client.get(EXTERNAL + "/providers").status_code == 401


def test_external_api_fails_closed_when_clients_unconfigured(
    image_client: TestClient, image_env: ImageEnvironment
) -> None:
    image_env.auth.settings.images.clients = []
    response = image_client.get(EXTERNAL + "/providers", headers={"X-Api-Key": KEY})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "image_api_unavailable"


def test_external_api_skips_unavailable_redis_even_with_stale_cookie(
    image_env: ImageEnvironment,
) -> None:
    session_storage = AsyncMock(side_effect=AssertionError("Redis was accessed"))

    async def unavailable(request: Request) -> SessionStore:
        return await session_storage()

    image_env.auth.app.dependency_overrides[get_session_store] = unavailable
    with TestClient(image_env.auth.app, base_url="https://testserver") as client:
        client.cookies.set(COOKIE_NAME, "a" * 64)
        original = upload(client)
        assert (
            client.get(original["content_url"], headers={"X-Api-Key": KEY}).status_code
            == 200
        )
        denied = client.get(EXTERNAL + "/providers")
        assert denied.status_code == 401
        assert "set-cookie" not in denied.headers
    session_storage.assert_not_awaited()


def test_route_validation_omits_private_input_and_provider_errors(
    image_client: TestClient, image_env: ImageEnvironment
) -> None:
    original = upload(image_client)
    path = f"{EXTERNAL}/assets/{original['id']}"
    sentinel = "private-comment-and-prompt-content"
    for suffix, payload in (
        ("/comments", {"text": sentinel, "x": 5, "y": 0}),
        ("/edits", {"operation": "erase", "provider": "gpt", "prompt": sentinel}),
        (
            "/edits",
            {"operation": "remove_background", "provider": "gpt", "secret": sentinel},
        ),
    ):
        response = image_client.post(
            path + suffix, json=payload, headers={"X-Api-Key": KEY}
        )
        assert response.status_code == 422
        assert sentinel not in response.text
        assert all(
            set(item) <= {"type", "loc", "msg"} for item in response.json()["detail"]
        )
    image_env.provider.fail = True
    response = image_client.post(
        path + "/edits",
        json={"operation": "remove_background", "provider": "gpt"},
        headers={"X-Api-Key": KEY},
    )
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "provider_failed"
    assert "private-provider-error" not in response.text


@pytest.mark.parametrize(
    "payload,code",
    [
        (
            {"operation": "remove_background", "provider": "local"},
            "unsupported_operation",
        ),
        (
            {"operation": "resize", "provider": "gpt", "width": 4, "height": 3},
            "unsupported_operation",
        ),
        (
            {
                "operation": "remove_background",
                "provider": "gpt",
                "model": "unlisted-model",
            },
            "unsupported_model",
        ),
    ],
)
def test_unsupported_provider_operation_or_model_never_invokes_provider(
    image_client: TestClient,
    image_env: ImageEnvironment,
    payload: dict[str, object],
    code: str,
) -> None:
    original = upload(image_client)
    response = image_client.post(
        f"{EXTERNAL}/assets/{original['id']}/edits",
        json=payload,
        headers={"X-Api-Key": KEY},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == code
    assert not image_env.provider.requests


def test_foreign_mask_is_rejected_before_model_invocation(
    image_client: TestClient, image_env: ImageEnvironment
) -> None:
    original = upload(image_client)
    mask = upload(image_client, headers={"X-Api-Key": OTHER_KEY}, purpose="mask")
    response = image_client.post(
        f"{EXTERNAL}/assets/{original['id']}/edits",
        headers={"X-Api-Key": KEY},
        json={"operation": "erase", "provider": "gpt", "mask_asset_id": mask["id"]},
    )
    assert response.status_code == 404
    assert not image_env.provider.requests
    assert (
        image_client.get(EXTERNAL + "/assets", headers={"X-Api-Key": OTHER_KEY}).json()
        == []
    )


@pytest.mark.asyncio
async def test_chunked_oversized_body_is_stopped_before_multipart_parsing(
    image_env: ImageEnvironment,
) -> None:
    received = 0
    sent: list[Message] = []

    async def receive() -> Message:
        nonlocal received
        received += 1
        return {
            "type": "http.request",
            "body": b"x" * (1024 * 1024),
            "more_body": received < 22,
        }

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": EXTERNAL + "/assets",
        "raw_path": (EXTERNAL + "/assets").encode(),
        "query_string": b"",
        "root_path": "",
        "server": ("testserver", 443),
        "client": ("127.0.0.1", 1234),
        "headers": [
            (b"x-api-key", KEY.encode()),
            (b"transfer-encoding", b"chunked"),
            (b"content-type", b"multipart/form-data; boundary=test"),
        ],
    }
    await image_env.auth.app(scope, receive, send)
    start = next(
        message for message in sent if message["type"] == "http.response.start"
    )
    assert start["status"] == 413
    body = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    assert json.loads(body)["detail"]["code"] == "request_too_large"
    assert received == 21
    assert not image_env.provider.requests


def test_bad_uploads_and_invalid_asset_ids_return_safe_errors(
    image_client: TestClient,
) -> None:
    response = image_client.post(
        EXTERNAL + "/assets",
        files={"file": ("private.txt", b"private payload", "text/plain")},
        headers={"X-Api-Key": KEY},
    )
    assert response.status_code == 422
    assert "private payload" not in response.text
    assert (
        image_client.get(
            EXTERNAL + "/assets/not-a-uuid", headers={"X-Api-Key": KEY}
        ).status_code
        == 422
    )
    assert (
        image_client.get(
            EXTERNAL + f"/assets/{uuid4()}", headers={"X-Api-Key": KEY}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "clients",
    [
        [{"id": "same", "keys": [KEY]}, {"id": "same", "keys": [OTHER_KEY]}],
        [{"id": "a", "keys": [KEY]}, {"id": "b", "keys": [KEY]}],
        [{"id": "a", "keys": [KEY, KEY]}],
    ],
)
def test_configuration_rejects_ambiguous_external_key_namespaces(
    clients: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError) as error:
        ImagesConfig(clients=clients)
    assert KEY not in str(error.value)


def test_openapi_exposes_external_image_key_scheme(image_env: ImageEnvironment) -> None:
    schema = image_env.auth.app.openapi()
    scheme = schema["components"]["securitySchemes"]["ImageServiceKey"]
    assert scheme["type"] == "apiKey"
    assert scheme["name"] == "X-Api-Key"
    assert schema["paths"][EXTERNAL + "/assets"]["post"]["security"] == [
        {"ImageServiceKey": []}
    ]
