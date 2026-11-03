"""Gemini tool calls use isolated SDK clients and canonical OSS image metadata."""

import asyncio
import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from google.genai import errors, types
from PIL import Image
from pytest import MonkeyPatch

from api.core.config import GoogleLLMConfig, LLMConfig
from api.tools.images import gemini, gemini_sync
from api.tools.types import ImageInfo, ImageToolResponse


def png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (4, 3), "red").save(output, format="PNG")
    return output.getvalue()


def response_with_parts(parts: list[types.Part]) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        model_version="gemini-test-image",
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(total_token_count=12),
    )


@dataclass
class GeminiEnvironment:
    factory: Mock
    clients: list[SimpleNamespace]
    upload: Mock
    metadata: ImageInfo
    image: bytes
    response: types.GenerateContentResponse
    generate: Callable[..., ImageToolResponse]
    asynchronous: bool

    @property
    def module(self) -> ModuleType:
        return gemini if self.asynchronous else gemini_sync

    @property
    def sdk_call(self) -> Mock:
        client = self.clients[0]
        return (client.aio if self.asynchronous else client).models.generate_content


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def gemini_env(
    monkeypatch: MonkeyPatch, tmp_path: Path, request: pytest.FixtureRequest
) -> GeminiEnvironment:
    asynchronous = request.param
    module = gemini if asynchronous else gemini_sync
    config = SimpleNamespace(
        data_dir=tmp_path,
        proxy_url=None,
        providers=SimpleNamespace(
            google=GoogleLLMConfig(
                base_url="https://google.example/v1beta/openai",
                api_key="google-secret",
                model="test-model",
            ),
            laozhang=LLMConfig(
                base_url="https://laozhang.example/v1",
                api_key="laozhang-secret",
                model="test-model",
            ),
        ),
    )
    monkeypatch.setattr(module, "settings", config)
    image = png()
    response = response_with_parts(
        [
            types.Part(text="generated image"),
            types.Part.from_bytes(data=image, mime_type="image/png"),
        ]
    )
    clients: list[SimpleNamespace] = []

    def create_client(**kwargs: object) -> SimpleNamespace:
        client = SimpleNamespace(
            models=SimpleNamespace(generate_content=Mock(return_value=response)),
            aio=SimpleNamespace(
                models=SimpleNamespace(
                    generate_content=AsyncMock(return_value=response)
                ),
                aclose=AsyncMock(),
            ),
            close=Mock(),
        )
        clients.append(client)
        return client

    factory = Mock(side_effect=create_client)
    monkeypatch.setattr(module.genai, "Client", factory)
    metadata = ImageInfo(
        url="https://oss.example/creative/gemini/result.png",
        id="uploaded-image-id",
        filename="result.png",
        original_filename="generated.png",
        width=4,
        height=3,
        file_size=len(image),
        mime_type="image/png",
        storage_key="creative/gemini/result.png",
        sha256=hashlib.sha256(image).hexdigest(),
    )
    upload = (
        AsyncMock(return_value=metadata)
        if asynchronous
        else Mock(return_value=metadata)
    )
    monkeypatch.setattr(
        module, "upload_image" if asynchronous else "upload_image_sync", upload
    )

    def generate(prompt: str, **kwargs: object) -> ImageToolResponse:
        if asynchronous:
            return asyncio.run(gemini.image_create_with_gemini(prompt, **kwargs))
        return gemini_sync.image_create_with_gemini(prompt, **kwargs)

    return GeminiEnvironment(
        factory, clients, upload, metadata, image, response, generate, asynchronous
    )


@pytest.mark.parametrize("provider", ["google", "laozhang"])
@pytest.mark.parametrize(
    "model",
    [
        "gemini-3-pro-image",
        "gemini-3.1-flash-lite-image",
        "gemini-3.1-flash-image",
        "gemini-nano-banana-2.1",
    ],
)
def test_models_use_selected_client_and_oss_metadata(
    gemini_env: GeminiEnvironment,
    model: str,
    provider: str,
) -> None:
    result = gemini_env.generate(
        "draw a cat",
        model=model,
        aspect_ratio="16:9",
        image_size="1K",
        provider=provider,
    )
    assert isinstance(result, ImageToolResponse)
    assert result.success
    assert result.images == [
        gemini_env.metadata.model_dump(mode="json", exclude_none=True)
    ]
    assert result.content == "generated image"
    assert result.usage == {"total_token_count": 12}
    args = gemini_env.factory.call_args.kwargs
    assert args["api_key"] == f"{provider}-secret"
    assert args["http_options"].base_url == f"https://{provider}.example/v1beta"
    assert args["http_options"].retry_options.attempts == 1
    sdk_call = gemini_env.sdk_call.call_args.kwargs
    assert sdk_call["model"] == model
    assert sdk_call["contents"] == ["draw a cat"]
    assert sdk_call["config"].image_config.aspect_ratio == "16:9"
    assert sdk_call["config"].image_config.image_size == "1K"
    gemini_env.clients[0].close.assert_called_once_with()
    if gemini_env.asynchronous:
        gemini_env.sdk_call.assert_awaited_once()
        gemini_env.clients[0].aio.aclose.assert_awaited_once_with()
        gemini_env.clients[0].models.generate_content.assert_not_called()
    else:
        gemini_env.clients[0].aio.models.generate_content.assert_not_called()
    if gemini_env.asynchronous:
        gemini_env.upload.assert_awaited_once()
    else:
        gemini_env.upload.assert_called_once()
    assert gemini_env.upload.call_args.args[1] == gemini_env.image
    assert gemini_env.upload.call_args.kwargs == {
        "mime_type": "image/png",
        "prefix": "creative/gemini",
        "rename": False,
    }


def test_switching_channels_creates_distinct_clients_without_global_mutation(
    gemini_env: GeminiEnvironment,
) -> None:
    google_config = gemini_env.module.settings.providers.google.model_dump()
    laozhang_config = gemini_env.module.settings.providers.laozhang.model_dump()
    assert gemini_env.generate("one", provider="google").success
    assert gemini_env.generate("two", provider="laozhang").success
    assert len(gemini_env.clients) == 2
    assert gemini_env.clients[0] is not gemini_env.clients[1]
    assert [call.kwargs["api_key"] for call in gemini_env.factory.call_args_list] == [
        "google-secret",
        "laozhang-secret",
    ]
    assert gemini_env.module.settings.providers.google.model_dump() == google_config
    assert gemini_env.module.settings.providers.laozhang.model_dump() == laozhang_config
    for client in gemini_env.clients:
        client.close.assert_called_once_with()


def test_data_url_and_local_references_are_not_downloaded(
    gemini_env: GeminiEnvironment, monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    data_url = "data:image/png;base64," + base64.b64encode(gemini_env.image).decode()
    absolute = tmp_path / "absolute.png"
    absolute.write_bytes(gemini_env.image)
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "relative.png").write_bytes(gemini_env.image)
    download = Mock(side_effect=AssertionError("Local references must not use HTTP"))
    monkeypatch.setattr(gemini_env.module.requests, "get", download)
    result = gemini_env.generate(
        "edit",
        model="gemini-3.1-flash-image",
        image_urls=[data_url, str(absolute), "relative.png"],
    )
    assert result.success
    parts = gemini_env.sdk_call.call_args.kwargs["contents"][1:]
    assert len(parts) == 3
    assert all(part.inline_data.data == gemini_env.image for part in parts)
    assert all(part.inline_data.mime_type == "image/png" for part in parts)
    download.assert_not_called()
    # A single data URL string must retain its comma.
    assert gemini_env.generate("edit", image_urls=data_url).success


def test_remote_reference_is_downloaded_once_and_auto_ratio_is_omitted(
    gemini_env: GeminiEnvironment, monkeypatch: MonkeyPatch
) -> None:
    response = SimpleNamespace(content=gemini_env.image, raise_for_status=Mock())
    download = Mock(return_value=response)
    monkeypatch.setattr(gemini_env.module.requests, "get", download)
    url = "https://images.example/a.png?signature=keep-me"
    result = gemini_env.generate(
        "edit", model="gemini-3.1-flash-image", image_urls=[url], aspect_ratio="auto"
    )
    assert result.success
    download.assert_called_once_with(url, timeout=175)
    response.raise_for_status.assert_called_once_with()
    request = gemini_env.sdk_call.call_args.kwargs
    assert request["contents"][1].inline_data.data == gemini_env.image
    assert request["config"].image_config.aspect_ratio is None
    assert request["config"].image_config.image_size == "2K"


def test_thought_images_are_not_uploaded(
    gemini_env: GeminiEnvironment,
) -> None:
    thought = types.Part.from_bytes(data=gemini_env.image, mime_type="image/png")
    thought.thought = True
    gemini_env.response.candidates[0].content.parts.insert(0, thought)
    result = gemini_env.generate("draw", provider="laozhang")
    assert result.success
    assert result.images == [
        gemini_env.metadata.model_dump(mode="json", exclude_none=True)
    ]
    assert result.usage == {"total_token_count": 12}
    if gemini_env.asynchronous:
        gemini_env.upload.assert_awaited_once()
    else:
        gemini_env.upload.assert_called_once()


@pytest.mark.parametrize("error_kind", ["provider", "input", "upload", "unconfigured"])
def test_failures_return_sanitized_tool_response(
    gemini_env: GeminiEnvironment, monkeypatch: MonkeyPatch, error_kind: str
) -> None:
    secret = "PRIVATE-provider-key-request-and-image-data"
    image_urls = None
    if error_kind == "provider":
        client = gemini_env.factory()
        error = errors.ClientError(
            403,
            {"error": {"code": 403, "message": secret, "status": "PERMISSION_DENIED"}},
        )
        client.models.generate_content.side_effect = error
        client.aio.models.generate_content.side_effect = error
        gemini_env.factory.side_effect = None
        gemini_env.factory.return_value = client
    elif error_kind == "input":
        monkeypatch.setattr(
            gemini_env.module.requests, "get", Mock(side_effect=OSError(secret))
        )
        image_urls = ["https://images.example/source.png"]
    elif error_kind == "upload":
        gemini_env.upload.side_effect = RuntimeError(secret)
    else:
        gemini_env.module.settings.providers.google = None
    result = gemini_env.generate("draw", image_urls=image_urls)
    assert isinstance(result, ImageToolResponse)
    assert not result.success
    assert result.images == []
    assert result.error
    assert secret not in result.model_dump_json()
    if error_kind == "provider":
        client.close.assert_called_once_with()
        if gemini_env.asynchronous:
            client.aio.aclose.assert_awaited_once_with()
    if error_kind == "unconfigured":
        gemini_env.factory.assert_not_called()


def test_empty_or_text_only_response_is_not_success(
    gemini_env: GeminiEnvironment,
) -> None:
    gemini_env.response.candidates[0].content.parts = [types.Part(text="no image")]
    result = gemini_env.generate("draw")
    assert not result.success
    assert result.error == "no_image_returned"
    gemini_env.upload.assert_not_called()
    gemini_env.clients[0].close.assert_called_once_with()


def test_flash_lite_rejects_unsupported_size_before_provider(
    gemini_env: GeminiEnvironment,
) -> None:
    result = gemini_env.generate(
        "draw", model="gemini-3.1-flash-lite-image", image_size="4K"
    )
    assert not result.success
    assert result.error == "unsupported_image_size"
    gemini_env.factory.assert_not_called()


def test_missing_usage_remains_none(gemini_env: GeminiEnvironment) -> None:
    gemini_env.response.usage_metadata = None
    result = gemini_env.generate("draw")
    assert result.success
    assert result.usage is None


def test_legacy_model_is_rejected_before_provider(
    gemini_env: GeminiEnvironment,
) -> None:
    result = gemini_env.generate("draw", model="gemini-2.5-flash-image")
    assert not result.success
    assert result.error == "unsupported_model"
    gemini_env.factory.assert_not_called()


@pytest.mark.parametrize("gemini_env", [True], indirect=True, ids=["async"])
def test_async_upload_is_awaited_on_generation_event_loop(
    gemini_env: GeminiEnvironment,
) -> None:
    upload_loops: list[asyncio.AbstractEventLoop] = []

    async def upload(*args: object, **kwargs: object) -> ImageInfo:
        upload_loops.append(asyncio.get_running_loop())
        return gemini_env.metadata

    gemini_env.upload.side_effect = upload

    async def generate() -> tuple[ImageToolResponse, asyncio.AbstractEventLoop]:
        loop = asyncio.get_running_loop()
        result = await gemini.image_create_with_gemini("draw")
        return result, loop

    result, loop = asyncio.run(generate())
    assert result.success
    gemini_env.upload.assert_awaited_once()
    assert upload_loops == [loop]


@pytest.mark.parametrize("gemini_env", [True], indirect=True, ids=["async"])
def test_async_generation_is_independent_of_sync_helpers(
    gemini_env: GeminiEnvironment, monkeypatch: MonkeyPatch
) -> None:
    unavailable = Mock(side_effect=AssertionError("Sync helpers must not be used"))
    for name in (
        "_prepare_request",
        "_create_client",
        "handle_gemini_image_response",
        "_request_failure",
    ):
        monkeypatch.setattr(gemini_sync, name, unavailable)
    result = gemini_env.generate("draw")
    assert result.success
    assert result.usage == {"total_token_count": 12}
    gemini_env.upload.assert_awaited_once()
    unavailable.assert_not_called()


@pytest.mark.parametrize("gemini_env", [False], indirect=True, ids=["sync"])
def test_sync_generation_and_upload_do_not_require_event_loop(
    gemini_env: GeminiEnvironment, monkeypatch: MonkeyPatch
) -> None:
    run = Mock(side_effect=AssertionError("Sync generation must not run an event loop"))
    monkeypatch.setattr(asyncio, "run", run)
    result = gemini_env.generate("draw")
    assert result.success
    assert result.usage == {"total_token_count": 12}
    gemini_env.sdk_call.assert_called_once()
    gemini_env.upload.assert_called_once()
    gemini_env.clients[0].aio.models.generate_content.assert_not_called()
    run.assert_not_called()
