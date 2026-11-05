"""Exercise the real generateContent SDK against an in-memory HTTP transport."""

import base64
import json
from dataclasses import dataclass, field
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from google.genai import errors, types
from PIL import Image
from pytest import MonkeyPatch

from api.core.config import GoogleLLMConfig
from api.tools.images import gemini
from api.tools.types import ImageInfo


@dataclass
class GenerateContentTransport:
    requests: list[httpx2.Request] = field(default_factory=list)
    clients: list[httpx2.AsyncClient] = field(default_factory=list)
    status_code: int = 200
    fail_connection: bool = False
    parts: list[dict] = field(default_factory=list)

    async def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.fail_connection:
            raise httpx2.ConnectError("private connection detail", request=request)
        if self.status_code != 200:
            return httpx2.Response(
                self.status_code,
                json={
                    "error": {
                        "code": self.status_code,
                        "message": "private provider detail",
                    }
                },
            )
        return httpx2.Response(
            200,
            json={
                "modelVersion": "gemini-test-image",
                "candidates": [{"content": {"role": "model", "parts": self.parts}}],
                "usageMetadata": {"totalTokenCount": 12},
            },
        )


@pytest.fixture
def generate_content_transport(monkeypatch: MonkeyPatch) -> GenerateContentTransport:
    transport = GenerateContentTransport()
    real_async_client = httpx2.AsyncClient

    def create_http_client(**kwargs: object) -> httpx2.AsyncClient:
        client = real_async_client(
            transport=httpx2.MockTransport(transport.handle), **kwargs
        )
        transport.clients.append(client)
        return client

    monkeypatch.setattr(gemini.httpx2, "AsyncClient", create_http_client)
    monkeypatch.setattr(
        gemini,
        "settings",
        SimpleNamespace(
            proxy_url=None,
            providers=SimpleNamespace(
                google=GoogleLLMConfig(
                    base_url="https://google.example/v1beta",
                    api_key="test-only-key",
                    model="test-model",
                ),
            ),
        ),
    )
    return transport


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url",
    [
        "https://google.example/v1beta",
        "https://gateway.example/gemini/v1",
        "https://gateway.example/gemini/v1beta/openai",
    ],
)
async def test_generate_content_preserves_configured_base_url_and_closes_clients(
    generate_content_transport: GenerateContentTransport,
    base_url: str,
) -> None:
    gemini.settings.providers.google.base_url = base_url
    async with gemini._create_client() as client:
        assert (
            client._api_client._async_httpx_client
            is generate_content_transport.clients[0]
        )
        assert client._api_client._http_options.timeout == 175_000
        assert (
            client._api_client._http_options.base_url_resource_scope
            == types.ResourceScope.COLLECTION
        )
        sync_http_client = client._api_client._httpx_client
        await client.aio.models.generate_content(
            model="gemini-3-pro-image", contents="draw"
        )

    assert len(generate_content_transport.requests) == 1
    request = generate_content_transport.requests[0]
    assert request.method == "POST"
    assert str(request.url) == f"{base_url}/models/gemini-3-pro-image:generateContent"
    assert request.headers["x-goog-api-key"] == "test-only-key"
    assert generate_content_transport.clients[0].is_closed
    assert sync_http_client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize(("image_size", "expected_size"), [("4K", "4K"), (None, "2K")])
@pytest.mark.parametrize("allow_grounding", [False, True])
async def test_generation_serializes_native_request_with_reference_image(
    generate_content_transport: GenerateContentTransport,
    monkeypatch: MonkeyPatch,
    image_size: gemini.ImageSize | None,
    expected_size: str,
    allow_grounding: bool,
) -> None:
    output = BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format="PNG")
    encoded_image = base64.b64encode(output.getvalue()).decode()
    generate_content_transport.parts = [
        {"text": "Generated image"},
        {"inlineData": {"mimeType": "image/png", "data": encoded_image}},
    ]
    metadata = ImageInfo(
        url="https://oss.example/generated.png",
        id="test-image",
        filename="generated.png",
        mime_type="image/png",
    )
    upload = AsyncMock(return_value=metadata)
    monkeypatch.setattr(gemini, "upload_image", upload)
    result = await gemini.image_create_with_gemini(
        "edit the reference",
        model="gemini-3.1-flash-image",
        image_urls=f"data:image/png;base64,{encoded_image}",
        aspect_ratio="16:9",
        image_size=image_size,
        allow_grounding=allow_grounding,
    )

    assert result.success
    assert result.content == "Generated image"
    assert result.images == [metadata.model_dump(mode="json", exclude_none=True)]
    assert result.usage == {"total_token_count": 12}
    assert result.image_model == "gemini-test-image"
    upload.assert_awaited_once()
    assert upload.call_args.args[1] == output.getvalue()
    assert len(generate_content_transport.requests) == 1
    body = json.loads(generate_content_transport.requests[0].content)
    assert str(generate_content_transport.requests[0].url).endswith(
        "/models/gemini-3.1-flash-image:generateContent"
    )
    assert body["contents"] == [
        {
            "role": "user",
            "parts": [
                {"text": "edit the reference"},
                {
                    "inlineData": {
                        "mime_type": "image/png",
                        "data": base64.urlsafe_b64encode(output.getvalue()).decode(),
                    }
                },
            ],
        },
    ]
    generation_config = body["generationConfig"]
    assert generation_config["thinkingConfig"]["thinking_level"] == "HIGH"
    assert generation_config["responseModalities"] == ["TEXT", "IMAGE"]
    assert generation_config["imageConfig"] == {
        "aspectRatio": "16:9",
        "imageSize": expected_size,
    }
    if allow_grounding:
        assert body["tools"] == [
            {"googleSearch": {"searchTypes": {"web_search": {}, "image_search": {}}}}
        ]
    else:
        assert not body.get("tools")
    assert "input" not in body
    assert "response_format" not in body
    assert generate_content_transport.clients[0].is_closed


@pytest.mark.asyncio
async def test_generate_content_errors_propagate_without_retry(
    generate_content_transport: GenerateContentTransport,
) -> None:
    generate_content_transport.status_code = 429
    with pytest.raises(errors.APIError) as captured:
        await gemini.image_create_with_gemini("draw")

    assert captured.value.code == 429
    assert captured.value.message == "private provider detail"
    assert len(generate_content_transport.requests) == 1
    assert generate_content_transport.clients[0].is_closed


@pytest.mark.asyncio
async def test_generate_content_connection_failure_closes_custom_client(
    generate_content_transport: GenerateContentTransport,
) -> None:
    generate_content_transport.fail_connection = True
    with pytest.raises(httpx2.ConnectError):
        await gemini.image_create_with_gemini("draw")

    assert len(generate_content_transport.requests) == 1
    assert str(generate_content_transport.requests[0].url).endswith(
        "/models/gemini-3.1-flash-lite-image:generateContent"
    )
    assert not json.loads(generate_content_transport.requests[0].content).get("tools")
    assert generate_content_transport.clients[0].is_closed


@pytest.mark.asyncio
async def test_response_without_images_raises_after_closing_client(
    generate_content_transport: GenerateContentTransport,
) -> None:
    with pytest.raises(gemini.GeminiToolError) as captured:
        await gemini.image_create_with_gemini("draw")

    assert captured.value.code == "no_image_returned"
    assert len(generate_content_transport.requests) == 1
    assert generate_content_transport.clients[0].is_closed


@pytest.mark.asyncio
async def test_upload_error_propagates_unchanged_after_closing_client(
    generate_content_transport: GenerateContentTransport,
    monkeypatch: MonkeyPatch,
) -> None:
    output = BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format="PNG")
    generate_content_transport.parts = [
        {
            "inlineData": {
                "mimeType": "image/png",
                "data": base64.b64encode(output.getvalue()).decode(),
            }
        }
    ]
    error = RuntimeError("original upload failure")
    upload = AsyncMock(side_effect=error)
    monkeypatch.setattr(gemini, "upload_image", upload)
    with pytest.raises(RuntimeError) as captured:
        await gemini.image_create_with_gemini("draw")

    assert captured.value is error
    upload.assert_awaited_once()
    assert upload.call_args.args[1] == output.getvalue()
    assert len(generate_content_transport.requests) == 1
    assert generate_content_transport.clients[0].is_closed
