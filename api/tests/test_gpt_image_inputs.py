"""Responses image inputs are prepared without external network or model calls."""

import base64
import json
from collections.abc import Callable, Iterable, Iterator
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from openai.types.responses import ResponseInputImageParam
from openai.types.responses.response_output_item import ImageGenerationCall
from openai.types.responses.tool import ImageGeneration as ResponseImageGeneration
from openai.types.responses.tool_param import ImageGenerationInputImageMask
from PIL import Image, UnidentifiedImageError
from pytest import MonkeyPatch

from api.tools.images import gpt
from api.tools.types import GPTImageGenerationParams, ImageInfo


def png() -> bytes:
    output = BytesIO()
    Image.new("RGBA", (4, 3), (20, 40, 60, 128)).save(output, format="PNG")
    return output.getvalue()


def data_url() -> str:
    return "data:image/png;base64," + base64.b64encode(png()).decode()


@pytest.fixture
def responses_create(monkeypatch: MonkeyPatch) -> AsyncMock:
    monkeypatch.setattr(gpt, "model_config", SimpleNamespace(model="test-main-model"))
    monkeypatch.setattr(gpt.settings, "proxy_url", None)
    create = AsyncMock(
        return_value=SimpleNamespace(
            usage=None, output=[], output_text="", tools=[], model="response-main-model"
        )
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    monkeypatch.setattr(gpt, "get_openai_client", lambda: client)
    return create


def mock_downloads(
    monkeypatch: MonkeyPatch,
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> tuple[list[httpx2.Request], list[httpx2.AsyncClient], list[dict[str, object]]]:
    requests: list[httpx2.Request] = []
    clients: list[httpx2.AsyncClient] = []
    options: list[dict[str, object]] = []
    client_type = httpx2.AsyncClient

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert "authorization" not in request.headers
        return handler(request)

    def create_client(
        *, proxy: str | None, timeout: float, trust_env: bool, follow_redirects: bool
    ) -> httpx2.AsyncClient:
        options.append(
            {
                "proxy": proxy,
                "timeout": timeout,
                "trust_env": trust_env,
                "follow_redirects": follow_redirects,
            }
        )
        # Record the configured proxy while routing every test request to the mock.
        client = client_type(
            transport=httpx2.MockTransport(handle),
            timeout=timeout,
            trust_env=trust_env,
            follow_redirects=follow_redirects,
        )
        clients.append(client)
        return client

    monkeypatch.setattr(gpt.httpx2, "AsyncClient", create_client)
    return requests, clients, options


@pytest.mark.asyncio
async def test_default_downloads_reference_urls_and_mask(
    monkeypatch: MonkeyPatch, responses_create: AsyncMock
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/redirect":
            return httpx2.Response(302, headers={"Location": "/reference.png"})
        return httpx2.Response(200, content=png())

    requests, clients, options = mock_downloads(monkeypatch, handler)
    monkeypatch.setattr(gpt.settings, "proxy_url", "http://configured-proxy:8080")
    reference = ResponseInputImageParam(
        type="input_image", detail="high", image_url="https://images.example/native"
    )
    mask = ImageGenerationInputImageMask(image_url="https://images.example/mask")
    original_reference, original_mask = reference.copy(), mask.copy()
    await gpt.image_create_with_gpt_image(
        prompt="edit",
        images=["https://images.example/redirect", reference],
        mask=mask,
    )

    responses_create.assert_awaited_once()
    assert responses_create.await_args is not None
    request = responses_create.await_args.kwargs
    assert request["model"] == "test-main-model"
    assert request["input"][0]["content"] == [
        {"type": "input_text", "text": "edit"},
        {"type": "input_image", "detail": "auto", "image_url": data_url()},
        {"type": "input_image", "detail": "high", "image_url": data_url()},
    ]
    assert request["tools"][0]["input_image_mask"] == {"image_url": data_url()}
    assert reference == original_reference
    assert mask == original_mask
    assert [request.url.path for request in requests] == [
        "/redirect",
        "/reference.png",
        "/native",
        "/mask",
    ]
    assert clients and all(client.is_closed for client in clients)
    assert options and all(
        option
        == {
            "proxy": "http://configured-proxy:8080",
            "timeout": 60,
            "trust_env": False,
            "follow_redirects": True,
        }
        for option in options
    )


@pytest.mark.asyncio
async def test_disabled_helper_conversion_preserves_remote_url(
    monkeypatch: MonkeyPatch,
) -> None:
    download = Mock(side_effect=AssertionError("No download client is needed"))
    monkeypatch.setattr(gpt.httpx2, "AsyncClient", download)
    url = "https://images.example/reference"
    assert await gpt._image_url(url, convert_image_url_to_base64=False) == url
    download.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("native_mask", [False, True])
async def test_remote_mask_is_converted_for_plain_and_native_inputs(
    monkeypatch: MonkeyPatch, responses_create: AsyncMock, native_mask: bool
) -> None:
    requests, clients, _ = mock_downloads(
        monkeypatch, lambda request: httpx2.Response(200, content=png())
    )
    inline = data_url()
    mask_url = "https://images.example/mask"
    mask = ImageGenerationInputImageMask(image_url=mask_url)
    await gpt.image_create_with_gpt_image(
        prompt="edit",
        images=inline,
        mask=mask if native_mask else mask_url,
    )
    assert responses_create.await_args is not None
    request = responses_create.await_args.kwargs
    assert request["input"][0]["content"][1]["image_url"] == inline
    assert request["tools"][0]["input_image_mask"] == {"image_url": data_url()}
    assert mask == {"image_url": mask_url}
    assert [str(request.url) for request in requests] == [mask_url]
    assert len(clients) == 1 and clients[0].is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("file_mask", [False, True])
async def test_data_urls_and_file_ids_bypass_download_and_base64_codecs(
    monkeypatch: MonkeyPatch, responses_create: AsyncMock, file_mask: bool
) -> None:
    inline = data_url()
    native_inline = ResponseInputImageParam(
        type="input_image", detail="high", image_url=inline
    )
    file_input = ResponseInputImageParam(
        type="input_image", detail="low", file_id="file-reference"
    )
    mask = (
        ImageGenerationInputImageMask(file_id="file-mask")
        if file_mask
        else ImageGenerationInputImageMask(image_url=inline)
    )
    unexpected = Mock(side_effect=AssertionError("Input is already API-ready"))
    monkeypatch.setattr(gpt.httpx2, "AsyncClient", unexpected)
    monkeypatch.setattr(gpt, "decode_data_url", unexpected)
    monkeypatch.setattr(gpt.base64, "b64decode", unexpected)
    monkeypatch.setattr(gpt.base64, "b64encode", unexpected)
    await gpt.image_create_with_gpt_image(
        prompt="edit", images=[inline, native_inline, file_input], mask=mask
    )
    assert responses_create.await_args is not None
    request = responses_create.await_args.kwargs
    assert request["input"][0]["content"][1:] == [
        {"type": "input_image", "detail": "auto", "image_url": inline},
        native_inline,
        file_input,
    ]
    assert request["tools"][0]["input_image_mask"] == mask
    unexpected.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("http_failure", [False, True])
async def test_failed_download_never_invokes_responses(
    monkeypatch: MonkeyPatch, responses_create: AsyncMock, http_failure: bool
) -> None:
    _, clients, _ = mock_downloads(
        monkeypatch,
        lambda request: httpx2.Response(
            404 if http_failure else 200, content=b"not an image"
        ),
    )
    with pytest.raises(
        httpx2.HTTPStatusError if http_failure else UnidentifiedImageError
    ):
        await gpt.image_create_with_gpt_image(
            prompt="edit", images="https://images.example/reference"
        )
    responses_create.assert_not_awaited()
    assert len(clients) == 1 and clients[0].is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("use_generator", [False, True], ids=["tuple", "generator"])
async def test_iterable_inputs_preserve_order_and_consume_generator_once(
    responses_create: AsyncMock, use_generator: bool
) -> None:
    inline = data_url()
    native = ResponseInputImageParam(
        type="input_image", detail="high", file_id="file-reference"
    )
    sources: tuple[gpt.ImageInput, ...] = (inline, native)
    consumed: list[gpt.ImageInput] = []

    def generate() -> Iterator[gpt.ImageInput]:
        for source in sources:
            consumed.append(source)
            yield source

    images: Iterable[gpt.ImageInput] = generate() if use_generator else sources
    await gpt.image_create_with_gpt_image(prompt="edit", images=images)

    assert responses_create.await_args is not None
    assert responses_create.await_args.kwargs["input"][0]["content"][1:] == [
        {"type": "input_image", "detail": "auto", "image_url": inline},
        native,
    ]
    assert consumed == (list(sources) if use_generator else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("with_mask", [False, True])
async def test_empty_generator_behaves_like_no_reference_images(
    responses_create: AsyncMock, with_mask: bool
) -> None:
    images: Iterator[gpt.ImageInput] = (source for source in ())
    if with_mask:
        with pytest.raises(
            ValueError, match="image_mask requires at least one input image"
        ):
            await gpt.image_create_with_gpt_image(
                prompt="draw",
                images=images,
                mask=ImageGenerationInputImageMask(file_id="file-mask"),
            )
        responses_create.assert_not_awaited()
    else:
        await gpt.image_create_with_gpt_image(prompt="draw", images=images)
        assert responses_create.await_args is not None
        assert responses_create.await_args.kwargs["input"] == "draw"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["str", "bytes", "native"])
async def test_single_iterable_image_values_are_not_split(
    responses_create: AsyncMock, kind: str
) -> None:
    native = ResponseInputImageParam(
        type="input_image", detail="high", file_id="file-reference"
    )
    source: gpt.ImageInput
    if kind == "str":
        source = data_url()
    elif kind == "bytes":
        source = png()
    else:
        source = native
    await gpt.image_create_with_gpt_image(prompt="edit", images=source)

    assert responses_create.await_args is not None
    assert responses_create.await_args.kwargs["input"][0]["content"][1:] == [
        native
        if kind == "native"
        else {"type": "input_image", "detail": "auto", "image_url": data_url()}
    ]


@pytest.mark.asyncio
async def test_generation_params_prefer_output_then_echoed_tool_then_sent_tool(
    monkeypatch: MonkeyPatch, responses_create: AsyncMock
) -> None:
    responses_create.return_value.tools = [
        ResponseImageGeneration(
            type="image_generation",
            model="gpt-image-2.5-sunburst",
            quality="medium",
            size="1024x1536",
            background=None,
            output_compression=50,
            partial_images=0,
        )
    ]
    responses_create.return_value.output = [
        ImageGenerationCall.model_validate(
            {
                "id": "call-success",
                "type": "image_generation_call",
                "status": "completed",
                "result": base64.b64encode(png()).decode(),
                "model": "gpt-image-2.5-flare",
                "quality": "high",
                "size": None,
                "background": None,
                "action": "auto",
                "output_compression": 0,
                "cached": False,
                "revised_prompt": "",
            }
        )
    ]
    upload = AsyncMock(
        return_value=ImageInfo(
            id="uploaded",
            filename="generated.png",
            url="https://cdn.example/image.png",
            mime_type="image/png",
        )
    )
    monkeypatch.setattr(gpt, "upload_image", upload)
    result = await gpt.image_create_with_gpt_image(
        prompt="draw",
        image_param=gpt.ImageParam(
            model="gpt-image-2",
            action="generate",
            quality="low",
            background="transparent",
            output_compression=80,
            partial_images=2,
        ),
    )
    parameters = result.generation_params
    assert isinstance(parameters, GPTImageGenerationParams)
    assert parameters.id == "call-success"
    assert parameters.type == "image_generation_call"
    assert parameters.status == "completed"
    assert parameters.model == "gpt-image-2.5-flare"
    assert parameters.quality == "high"
    assert parameters.size == "1024x1536"
    assert parameters.background == "transparent"
    assert parameters.action == "auto"
    assert parameters.output_format == "png"
    assert parameters.output_compression == 0
    assert parameters.partial_images == 0
    assert parameters.prompt == ""
    dumped = parameters.model_dump(exclude_none=True)
    assert dumped["cached"] is False
    assert "revised_prompt" not in dumped
    assert "result" not in dumped
    assert result.instructions == "draw"
    upload.assert_awaited_once_with("generated.png", png(), prefix="creative/gpt")


@pytest.mark.asyncio
async def test_failed_call_keeps_error_and_falls_back_to_image_tool_model(
    monkeypatch: MonkeyPatch, responses_create: AsyncMock
) -> None:
    error = {
        "code": "moderation_blocked",
        "type": "image_generation_error",
        "message": "Blocked",
    }
    responses_create.return_value.tools = [
        ResponseImageGeneration(type="image_generation", model="gpt-image-2.5-sunburst")
    ]
    responses_create.return_value.output = [
        ImageGenerationCall.model_validate(
            {
                "id": "call-failed",
                "type": "image_generation_call",
                "status": "failed",
                "result": None,
                "model": None,
                "error": error,
            }
        )
    ]
    upload = AsyncMock()
    monkeypatch.setattr(gpt, "upload_image", upload)
    result = await gpt.image_create_with_gpt_image(prompt="draw")
    assert result.success is False
    assert isinstance(result.generation_params, GPTImageGenerationParams)
    assert result.generation_params.id == "call-failed"
    assert result.generation_params.status == "failed"
    assert result.generation_params.model == "gpt-image-2.5-sunburst"
    assert result.generation_params.error == error
    assert result.generation_params.prompt == "draw"
    assert result.instructions == "draw"
    assert "result" not in result.generation_params.model_dump(exclude_none=True)
    upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_multiple_calls_keep_separate_resolved_generation_params(
    monkeypatch: MonkeyPatch, responses_create: AsyncMock
) -> None:
    responses_create.return_value.tools = [
        ResponseImageGeneration(
            type="image_generation", model="gpt-image-2.5-sunburst", quality="medium"
        )
    ]
    responses_create.return_value.output = [
        ImageGenerationCall.model_validate(
            {
                "id": "first-call",
                "type": "image_generation_call",
                "status": "completed",
                "result": base64.b64encode(png()).decode(),
                "model": "gpt-image-2",
                "quality": "high",
                "revised_prompt": "First image",
            }
        ),
        ImageGenerationCall.model_validate(
            {
                "id": "second-call",
                "type": "image_generation_call",
                "status": "completed",
                "result": base64.b64encode(png()).decode(),
                "quality": None,
            }
        ),
    ]
    upload = AsyncMock(
        return_value=ImageInfo(
            id="uploaded",
            filename="generated.png",
            url="https://cdn.example/image.png",
            mime_type="image/png",
        )
    )
    monkeypatch.setattr(gpt, "upload_image", upload)
    result = await gpt.image_create_with_gpt_image(prompt="draw two images")
    assert isinstance(result.generation_params, GPTImageGenerationParams)
    assert set(result.generation_params.model_dump(exclude_none=True)) == {"calls"}
    assert result.generation_params.calls is not None
    first, second = result.generation_params.calls
    assert isinstance(first, GPTImageGenerationParams)
    assert isinstance(second, GPTImageGenerationParams)
    assert (first.id, second.id) == ("first-call", "second-call")
    assert (first.model, second.model) == (
        "gpt-image-2",
        "gpt-image-2.5-sunburst",
    )
    assert (first.quality, second.quality) == ("high", "medium")
    assert first.prompt == "First image"
    assert second.prompt == "draw two images"
    serialized = json.loads(result.model_dump_json(exclude_none=True))
    assert serialized["instructions"] == "draw two images"
    calls = serialized["generation_params"]["calls"]
    assert [call["prompt"] for call in calls] == ["First image", "draw two images"]
    assert all("revised_prompt" not in call and "result" not in call for call in calls)
    assert upload.await_count == 2


@pytest.mark.asyncio
async def test_no_call_returns_sent_generation_params_including_mask(
    responses_create: AsyncMock,
) -> None:
    responses_create.return_value.tools = None
    parameters = gpt.ImageParam(
        model="gpt-image-2", action="auto", output_compression=0, partial_images=0
    )
    mask = ImageGenerationInputImageMask(file_id="file-mask")
    result = await gpt.image_create_with_gpt_image(
        prompt="edit",
        images=ResponseInputImageParam(
            type="input_image", detail="auto", file_id="file-reference"
        ),
        mask=mask,
        model="gpt-image-2.5-sunburst",
        image_param=parameters,
    )
    assert isinstance(result.generation_params, GPTImageGenerationParams)
    assert result.generation_params.model_dump(exclude_none=True) == {
        **parameters.model_dump(exclude_none=True),
        "prompt": "edit",
        "input_image_mask": mask,
    }
    assert result.generation_params.model == "gpt-image-2"
    assert result.instructions == "edit"
    assert result.error == "no_image_returned"


@pytest.mark.asyncio
@pytest.mark.parametrize("rewrite_state", ["present", "null", "missing"])
async def test_prompt_rewrite_and_original_instructions_serialize_separately(
    responses_create: AsyncMock, rewrite_state: str
) -> None:
    original = "Original request"
    output: dict[str, object] = {
        "id": "call-rewrite",
        "type": "image_generation_call",
        "status": "completed",
    }
    if rewrite_state != "missing":
        output["revised_prompt"] = (
            "Rewritten prompt" if rewrite_state == "present" else None
        )
    responses_create.return_value.output = [ImageGenerationCall.model_validate(output)]
    result = await gpt.image_create_with_gpt_image(prompt=original)
    assert isinstance(result.generation_params, GPTImageGenerationParams)
    expected = "Rewritten prompt" if rewrite_state == "present" else original
    assert result.generation_params.prompt == expected
    assert result.instructions == original
    serialized = json.loads(result.model_dump_json(exclude_none=True))
    assert serialized["generation_params"]["prompt"] == expected
    assert serialized["instructions"] == original
    assert "revised_prompt" not in serialized["generation_params"]
