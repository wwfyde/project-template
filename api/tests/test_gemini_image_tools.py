"""Gemini tool calls use isolated SDK clients and canonical OSS image metadata."""

import base64
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from google.genai import errors, types
from PIL import Image
from pytest import MonkeyPatch

from api.core.config import GoogleLLMConfig, LLMConfig
from api.tools.images import gemini
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
    upload: AsyncMock
    metadata: ImageInfo
    image: bytes
    response: types.GenerateContentResponse


@pytest.fixture
def gemini_env(monkeypatch: MonkeyPatch, tmp_path: Path) -> GeminiEnvironment:
    config = gemini.settings.model_copy(deep=True)
    config.data_dir = tmp_path
    config.providers.google = GoogleLLMConfig(
        base_url="https://google.example/v1beta/openai", api_key="google-secret"
    )
    config.providers.laozhang = LLMConfig(
        base_url="https://laozhang.example/v1", api_key="laozhang-secret"
    )
    monkeypatch.setattr(gemini, "settings", config)
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
            close=Mock(),
        )
        clients.append(client)
        return client

    factory = Mock(side_effect=create_client)
    monkeypatch.setattr(gemini.genai, "Client", factory)
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
    upload = AsyncMock(return_value=metadata)
    monkeypatch.setattr(gemini, "upload_image", upload)
    return GeminiEnvironment(factory, clients, upload, metadata, image, response)


@pytest.mark.parametrize("provider", ["google", "laozhang"])
@pytest.mark.parametrize(
    "function,model",
    [
        (gemini.image_create_with_gemini, "gemini-3-pro-image"),
        (gemini.image_create_with_gemini_flash, "gemini-2.5-flash-image"),
        (gemini.image_create_with_gemini_flash_2, "gemini-3.1-flash-image"),
        (gemini.image_create_with_gemini_flash_2_1, "gemini-nano-banana-2.1"),
    ],
)
def test_model_functions_use_selected_client_and_oss_metadata(
    gemini_env: GeminiEnvironment,
    function: Callable[..., ImageToolResponse],
    model: str,
    provider: str,
) -> None:
    result = function(
        "draw a cat", aspect_ratio="16:9", image_size="1K", provider=provider
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
    sdk_call = gemini_env.clients[0].models.generate_content.call_args.kwargs
    assert sdk_call["model"] == model
    assert sdk_call["contents"] == ["draw a cat"]
    assert sdk_call["config"].image_config.aspect_ratio == "16:9"
    if model == "gemini-2.5-flash-image":
        assert sdk_call["config"].image_config.image_size is None
    else:
        assert sdk_call["config"].image_config.image_size == "1K"
    gemini_env.clients[0].close.assert_called_once_with()
    gemini_env.upload.assert_awaited_once()
    assert gemini_env.upload.call_args.args[1] == gemini_env.image
    assert gemini_env.upload.call_args.kwargs == {
        "mime_type": "image/png",
        "prefix": "creative/gemini",
        "rename": False,
    }


def test_switching_channels_creates_distinct_clients_without_global_mutation(
    gemini_env: GeminiEnvironment,
) -> None:
    google_config = gemini.settings.providers.google.model_dump()
    laozhang_config = gemini.settings.providers.laozhang.model_dump()
    assert gemini.image_create_with_gemini("one", provider="google").success
    assert gemini.image_create_with_gemini("two", provider="laozhang").success
    assert len(gemini_env.clients) == 2
    assert gemini_env.clients[0] is not gemini_env.clients[1]
    assert [call.kwargs["api_key"] for call in gemini_env.factory.call_args_list] == [
        "google-secret",
        "laozhang-secret",
    ]
    assert gemini.settings.providers.google.model_dump() == google_config
    assert gemini.settings.providers.laozhang.model_dump() == laozhang_config
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
    monkeypatch.setattr(gemini.requests, "get", download)
    result = gemini.image_create_with_gemini_flash_2(
        "edit", image_urls=[data_url, str(absolute), "relative.png"]
    )
    assert result.success
    parts = gemini_env.clients[0].models.generate_content.call_args.kwargs["contents"][
        1:
    ]
    assert len(parts) == 3
    assert all(part.inline_data.data == gemini_env.image for part in parts)
    assert all(part.inline_data.mime_type == "image/png" for part in parts)
    download.assert_not_called()
    # A single data URL string must retain its comma.
    assert gemini.image_create_with_gemini("edit", image_urls=data_url).success


def test_remote_reference_is_downloaded_once_and_auto_ratio_is_omitted(
    gemini_env: GeminiEnvironment, monkeypatch: MonkeyPatch
) -> None:
    response = SimpleNamespace(content=gemini_env.image, raise_for_status=Mock())
    download = Mock(return_value=response)
    monkeypatch.setattr(gemini.requests, "get", download)
    url = "https://images.example/a.png?signature=keep-me"
    result = gemini.image_create_with_gemini_flash_2(
        "edit", image_urls=[url], aspect_ratio="auto"
    )
    assert result.success
    download.assert_called_once_with(url, timeout=175)
    response.raise_for_status.assert_called_once_with()
    request = gemini_env.clients[0].models.generate_content.call_args.kwargs
    assert request["contents"][1].inline_data.data == gemini_env.image
    assert request["config"].image_config.aspect_ratio is None
    assert request["config"].image_config.image_size == "2K"


def test_thought_images_are_not_uploaded_and_magic_returns_oss_metadata(
    gemini_env: GeminiEnvironment, monkeypatch: MonkeyPatch
) -> None:
    thought = types.Part.from_bytes(data=gemini_env.image, mime_type="image/png")
    thought.thought = True
    gemini_env.response.candidates[0].content.parts.insert(0, thought)
    data_url = "data:image/png;base64," + base64.b64encode(gemini_env.image).decode()
    images, usage = gemini.magic_generate_with_gemini(
        "edit", data_url, provider="laozhang"
    )
    assert images[0]["image_url"] == gemini_env.metadata.url
    assert images[0]["url"] == gemini_env.metadata.url
    assert images[0]["storage_key"] == gemini_env.metadata.storage_key
    assert images[0]["sha256"] == gemini_env.metadata.sha256
    assert usage == {"total_token_count": 12}
    gemini_env.upload.assert_awaited_once()
    assert gemini_env.factory.call_args.kwargs["api_key"] == "laozhang-secret"


@pytest.mark.parametrize("error_kind", ["provider", "input", "upload", "unconfigured"])
def test_failures_return_sanitized_tool_response(
    gemini_env: GeminiEnvironment, monkeypatch: MonkeyPatch, error_kind: str
) -> None:
    secret = "PRIVATE-provider-key-request-and-image-data"
    image_urls = None
    if error_kind == "provider":
        client = SimpleNamespace(
            models=SimpleNamespace(
                generate_content=Mock(
                    side_effect=errors.ClientError(
                        403,
                        {
                            "error": {
                                "code": 403,
                                "message": secret,
                                "status": "PERMISSION_DENIED",
                            }
                        },
                    )
                )
            ),
            close=Mock(),
        )
        gemini_env.factory.side_effect = None
        gemini_env.factory.return_value = client
    elif error_kind == "input":
        monkeypatch.setattr(gemini.requests, "get", Mock(side_effect=OSError(secret)))
        image_urls = ["https://images.example/source.png"]
    elif error_kind == "upload":
        gemini_env.upload.side_effect = RuntimeError(secret)
    else:
        gemini.settings.providers.google = None
    result = gemini.image_create_with_gemini("draw", image_urls=image_urls)
    assert isinstance(result, ImageToolResponse)
    assert not result.success
    assert result.images == []
    assert result.error
    assert secret not in result.model_dump_json()
    if error_kind == "provider":
        client.close.assert_called_once_with()
    if error_kind == "unconfigured":
        gemini_env.factory.assert_not_called()


def test_empty_or_text_only_response_is_not_success(
    gemini_env: GeminiEnvironment,
) -> None:
    gemini_env.response.candidates[0].content.parts = [types.Part(text="no image")]
    result = gemini.image_create_with_gemini_flash("draw")
    assert not result.success
    assert result.error == "no_image_returned"
    gemini_env.upload.assert_not_awaited()
    gemini_env.clients[0].close.assert_called_once_with()


def test_flash_25_rejects_unsupported_size_before_provider(
    gemini_env: GeminiEnvironment,
) -> None:
    result = gemini.image_create_with_gemini_flash("draw", image_size="4K")
    assert not result.success
    assert result.error == "unsupported_image_size"
    gemini_env.factory.assert_not_called()
