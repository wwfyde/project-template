"""The Images API uses real SDK serialization with isolated HTTP and OSS mocks."""

import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
import pytest_asyncio
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputImageParam
from openai.types.responses.tool_param import ImageGenerationInputImageMask
from PIL import Image
from pydantic import ValidationError
from pytest import MonkeyPatch

from api.schemas.ai_tools import GPTImageRequest
from api.tools.images import gpt
from api.tools.types import ImageInfo


def image_bytes(image_format: str = "PNG") -> bytes:
    output = BytesIO()
    image = Image.new("RGBA", (4, 3), (20, 40, 60, 128))
    if image_format == "JPEG":
        image = image.convert("RGB")
    image.save(output, format=image_format)
    return output.getvalue()


@dataclass
class ImageAPIEnvironment:
    requests: list[httpx2.Request]
    response: dict[str, object]
    upload: AsyncMock


@pytest_asyncio.fixture
async def api_env(monkeypatch: MonkeyPatch) -> AsyncIterator[ImageAPIEnvironment]:
    requests: list[httpx2.Request] = []
    response: dict[str, object] = {
        "created": 1,
        "data": [{"b64_json": base64.b64encode(image_bytes()).decode()}],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
            "input_tokens_details": {"text_tokens": 1, "image_tokens": 0},
        },
    }

    async def handle(request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        requests.append(request)
        if request.url.host == "images.example":
            assert "authorization" not in request.headers
            assert request.method == "GET"
            return httpx2.Response(200, content=image_bytes())
        assert request.headers["authorization"] == "Bearer test-image-api-key"
        if request.method == "GET" and request.url.path.startswith("/v1/files/"):
            assert request.url.path.endswith("/content")
            return httpx2.Response(200, content=image_bytes())
        assert request.method == "POST"
        assert request.url.path in {"/v1/images/generations", "/v1/images/edits"}
        return httpx2.Response(200, json=response)

    client_type = httpx2.AsyncClient
    client = AsyncOpenAI(
        api_key="test-image-api-key",
        base_url="https://openai.example/v1",
        max_retries=0,
        http_client=client_type(transport=httpx2.MockTransport(handle)),
    )

    def download_client(
        *,
        proxy: str | None = None,
        timeout: float = 60,
        trust_env: bool = False,
        follow_redirects: bool = True,
    ) -> httpx2.AsyncClient:
        assert proxy is None
        return client_type(
            transport=httpx2.MockTransport(handle),
            timeout=timeout,
            trust_env=trust_env,
            follow_redirects=follow_redirects,
        )

    monkeypatch.setattr(
        gpt, "model_config", SimpleNamespace(model="unused-responses-model")
    )
    monkeypatch.setattr(gpt.settings, "proxy_url", None)
    monkeypatch.setattr(gpt, "get_openai_client", lambda: client)
    monkeypatch.setattr(gpt.httpx2, "AsyncClient", download_client)
    upload = AsyncMock(
        return_value=ImageInfo(
            id="stored-image",
            url="https://cdn.example/result.png",
            filename="result.png",
            mime_type="image/png",
        )
    )
    monkeypatch.setattr(gpt, "upload_image", upload)
    try:
        yield ImageAPIEnvironment(requests, response, upload)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_generation_filters_parameters_and_uploads_requested_format(
    api_env: ImageAPIEnvironment,
) -> None:
    output = image_bytes("JPEG")
    api_env.response["data"] = [{"b64_json": base64.b64encode(output).decode()}]
    parameters = gpt.ImageParam(
        action="generate",
        model="gpt-image-2",
        size="1024x1024",
        quality="high",
        background="opaque",
        output_format="jpeg",
        output_compression=70,
        moderation="low",
        input_fidelity="high",
        partial_images=2,
    )
    original = parameters.model_dump()
    result = await gpt.image_create_with_image_api(
        prompt="draw a cup", model="gpt-image-2.5-sunburst", image_param=parameters
    )
    assert len(api_env.requests) == 1
    request = api_env.requests[0]
    assert request.url.path == "/v1/images/generations"
    assert json.loads(request.content) == {
        "model": "gpt-image-2.5-sunburst",
        "prompt": "draw a cup",
        "size": "1024x1024",
        "quality": "high",
        "background": "opaque",
        "output_format": "jpeg",
        "output_compression": 70,
        "moderation": "low",
        "stream": False,
    }
    api_env.upload.assert_awaited_once_with(
        "generated.jpeg", output, prefix="creative/gpt"
    )
    assert parameters.model_dump() == original
    assert result.success
    assert result.image_model == "gpt-image-2.5-sunburst"
    assert result.usage == api_env.response["usage"]
    assert result.images == [
        api_env.upload.return_value.model_dump(mode="json", exclude_none=True)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["missing", "auto"])
@pytest.mark.parametrize("has_images", [False, True])
async def test_auto_selects_endpoint_from_materialized_images(
    api_env: ImageAPIEnvironment, action: str, has_images: bool
) -> None:
    parameters = (
        gpt.ImageParam() if action == "missing" else gpt.ImageParam(action="auto")
    )
    sources = (image_bytes() for _ in range(int(has_images)))
    result = await gpt.image_create_with_image_api(
        prompt="draw", images=sources, image_param=parameters
    )
    assert result.success
    assert [request.url.path for request in api_env.requests] == [
        "/v1/images/edits" if has_images else "/v1/images/generations"
    ]


@pytest.mark.asyncio
async def test_edit_resolves_all_input_forms_and_native_mask_without_mutation(
    api_env: ImageAPIEnvironment, tmp_path: Path
) -> None:
    content = image_bytes()
    path = tmp_path / "source.png"
    path.write_bytes(content)
    pil_image = Image.open(BytesIO(content))
    encoded = base64.b64encode(content).decode()
    native_url = ResponseInputImageParam(
        type="input_image", detail="high", image_url="https://images.example/native"
    )
    native_file = ResponseInputImageParam(
        type="input_image", detail="low", file_id="file-reference"
    )
    mask = ImageGenerationInputImageMask(file_id="file-mask")
    originals = native_url.copy(), native_file.copy(), mask.copy()
    sources: list[gpt.ImageInput] = [
        content,
        path,
        pil_image,
        encoded,
        "data:image/png;base64," + encoded,
        "https://images.example/plain",
        native_url,
        native_file,
    ]
    result = await gpt.image_create_with_image_api(
        prompt="edit",
        images=(source for source in sources),
        mask=mask,
        image_param=gpt.ImageParam(
            action="edit", input_fidelity="high", moderation="low", partial_images=2
        ),
    )
    assert result.success
    assert (native_url, native_file, mask) == originals
    assert [request.url.path for request in api_env.requests] == [
        "/plain",
        "/native",
        "/v1/files/file-reference/content",
        "/v1/files/file-mask/content",
        "/v1/images/edits",
    ]
    request = api_env.requests[-1]
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: "
        + request.headers["content-type"].encode()
        + b"\r\n\r\n"
        + request.content
    )
    parts = list(message.iter_parts())
    references = [
        part
        for part in parts
        if part.get_param("name", header="content-disposition") in {"image", "image[]"}
    ]
    masks = [
        part
        for part in parts
        if part.get_param("name", header="content-disposition") == "mask"
    ]
    assert len(references) == 8
    assert len(masks) == 1
    assert all(part.get_payload(decode=True) == content for part in references + masks)
    fields = {
        part.get_param("name", header="content-disposition"): part.get_payload(
            decode=True
        )
        for part in parts
        if not part.get_filename()
    }
    assert fields["input_fidelity"] == b"high"
    assert fields["moderation"] == b"low"
    assert "action" not in fields and "partial_images" not in fields
    pil_image.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "edit_without_images",
        "generate_with_images",
        "generate_with_mask",
        "auto_with_mask_only",
    ],
)
async def test_invalid_action_inputs_fail_before_network(
    api_env: ImageAPIEnvironment, case: str
) -> None:
    action = (
        "edit"
        if case == "edit_without_images"
        else "auto"
        if case == "auto_with_mask_only"
        else "generate"
    )
    with pytest.raises(ValueError):
        await gpt.image_create_with_image_api(
            prompt="draw",
            images=image_bytes() if case == "generate_with_images" else None,
            mask=image_bytes() if "mask" in case else None,
            image_param=gpt.ImageParam(action=action),
        )
    assert api_env.requests == []
    api_env.upload.assert_not_awaited()


def test_request_schema_validates_action() -> None:
    assert GPTImageRequest(prompt="draw").action == "auto"
    for action in ("generate", "edit", "auto"):
        assert (
            GPTImageRequest.model_validate({"prompt": "draw", "action": action}).action
            == action
        )
    with pytest.raises(ValidationError):
        GPTImageRequest.model_validate({"prompt": "draw", "action": "unknown"})


@pytest.mark.asyncio
async def test_no_image_result_preserves_usage(api_env: ImageAPIEnvironment) -> None:
    api_env.response["data"] = []
    result = await gpt.image_create_with_image_api(prompt="draw")
    assert result.success is False
    assert result.error == "no_image_returned"
    assert result.images == []
    assert result.usage == api_env.response["usage"]
    api_env.upload.assert_not_awaited()
