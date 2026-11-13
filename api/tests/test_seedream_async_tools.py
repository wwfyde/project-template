import asyncio
import base64
import importlib
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import httpx2
import pytest
from api.images import source_access
from api.tools.types import ImageInfo, ImageToolResponse
from arkruntime import AsyncArk
from PIL import Image
from pydantic import SecretStr

MODEL = "doubao-seedream-5-5-261028"


@pytest.fixture
def image_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    module = importlib.import_module("api.tools.images.seedream")
    output = BytesIO()
    Image.new("RGBA", (12, 8), (30, 90, 170, 128)).save(output, "PNG")
    config = SimpleNamespace(
        providers=SimpleNamespace(
            volcengine=SimpleNamespace(
                base_url="https://ark.example.test/api/v3/",
                api_key=SecretStr("seedream-test-key"),
            )
        ),
        proxy_url=None,
        data_dir=tmp_path,
    )
    state = SimpleNamespace(
        module=module,
        call=module.image_create_with_seedream,
        png=output.getvalue(),
        config=config,
        requests=[],
        downloads=[],
        uploads=[],
        sdk_clients=[],
        download_clients=[],
        status=200,
        download_status=200,
        reference_redirect=False,
        cancel=False,
        images=[{"url": "https://output.example.test/generated.png"}],
    )

    async def upstream(request: httpx.Request) -> httpx.Response:
        state.requests.append(request)
        if state.cancel:
            raise asyncio.CancelledError
        if state.status != 200:
            return httpx.Response(
                state.status,
                json={"error": {"code": "test_error", "message": "private upstream detail"}},
            )
        return httpx.Response(
            200,
            json={
                "model": json.loads(request.content)["model"],
                "created": 1,
                "data": state.images,
                "usage": {"generated_images": 1, "output_tokens": 10, "total_tokens": 10},
            },
        )

    def download(request: httpx2.Request) -> httpx2.Response:
        state.downloads.append(request)
        if state.reference_redirect:
            return httpx2.Response(302, headers={"location": "http://127.0.0.1/private.png"})
        return httpx2.Response(state.download_status, content=state.png)

    sdk_factory = AsyncArk.volc
    download_factory = httpx2.AsyncClient

    def create_sdk(**kwargs: object) -> AsyncArk:
        assert kwargs["api_key"] == "seedream-test-key"
        assert str(kwargs["base_url"]).rstrip("/") == config.providers.volcengine.base_url.rstrip(
            "/"
        )
        client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
        state.sdk_clients.append(client)
        return sdk_factory(**kwargs, http_client=client)

    def create_download_client(**kwargs: object) -> httpx2.AsyncClient:
        client = download_factory(**kwargs, transport=httpx2.MockTransport(download))
        state.download_clients.append(client)
        return client

    async def upload(filename: str, data: bytes, **kwargs: object) -> ImageInfo:
        assert data == state.png
        identifier = f"oss-id-{len(state.uploads) + 1}"
        storage_key = f"{kwargs['prefix']}/{identifier}.png"
        metadata = ImageInfo(
            id=identifier,
            url=f"https://cdn.example.test/{storage_key}",
            filename=f"{identifier}.png",
            original_filename=filename,
            storage_key=storage_key,
            mime_type="image/png",
            width=12,
            height=8,
            file_size=len(data),
            sha256="hash-from-oss-uploader",
        )
        state.uploads.append((data, kwargs, metadata))
        return metadata

    monkeypatch.setattr(module, "settings", config)
    monkeypatch.setattr(module.AsyncArk, "volc", create_sdk)
    monkeypatch.setattr(module.httpx2, "AsyncClient", create_download_client)
    monkeypatch.setattr(module, "upload_image", upload)
    return state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [MODEL, "doubao-seedream-5-0-pro-260628", "doubao-seedream-5-0-flash-260915"],
)
async def test_async_sdk_generation_preserves_model_usage_and_oss_metadata(
    image_tool: SimpleNamespace, model: str
) -> None:
    result = await image_tool.call(
        prompt="a blue cup", model=model, aspect_ratio="16:9", image_size="2K"
    )

    assert isinstance(result, ImageToolResponse)
    assert result.success
    assert result.image_model == model
    assert result.usage == {"generated_images": 1, "output_tokens": 10, "total_tokens": 10}
    request = image_tool.requests[0]
    assert str(request.url) == "https://ark.example.test/api/v3/images/generations"
    assert request.headers["authorization"] == "Bearer seedream-test-key"
    payload = json.loads(request.content)
    assert payload["model"] == model
    assert payload["size"] == "2816x1584"
    assert payload["response_format"] == "url"
    assert payload["output_format"] == "png"
    assert payload["watermark"] is False
    assert payload["stream"] is False
    assert payload["optimize_prompt_options"] == {"mode": "standard"}
    assert not payload.get("image")
    assert str(image_tool.downloads[0].url) == "https://output.example.test/generated.png"
    assert result.images == [
        image_tool.uploads[0][2].model_dump(mode="json", exclude_none=True, exclude_unset=True)
    ]
    assert image_tool.uploads[0][1] == {"prefix": "creative/seedream"}
    assert all(client.is_closed for client in image_tool.sdk_clients)
    assert all(client.is_closed for client in image_tool.download_clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("aspect_ratio", [None, "16:9"])
async def test_seedream_55_supports_one_and_a_half_k(
    image_tool: SimpleNamespace, aspect_ratio: str | None
) -> None:
    result = await image_tool.call(
        prompt="a blue cup", model=MODEL, image_size="1.5K", aspect_ratio=aspect_ratio
    )

    assert result.success
    size = json.loads(image_tool.requests[0].content)["size"]
    assert size == ("1.5K" if aspect_ratio is None else "2048x1152")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "aspect_ratio", ["10000x10000", "16384x1024", "1024x16384", "16:1", "1:16"]
)
async def test_seedream_55_custom_sizes_stay_inside_documented_bounds(
    image_tool: SimpleNamespace, aspect_ratio: str
) -> None:
    result = await image_tool.call(prompt="blue cup", model=MODEL, aspect_ratio=aspect_ratio)

    assert result.success
    size = json.loads(image_tool.requests[0].content)["size"]
    width, height = map(int, size.split("x"))
    assert 921600 <= width * height <= 4624220
    assert 1 / 16 <= width / height <= 16


@pytest.mark.asyncio
async def test_seedream_55_keeps_valid_custom_size_above_old_pixel_limit(
    image_tool: SimpleNamespace,
) -> None:
    result = await image_tool.call(prompt="blue cup", model=MODEL, aspect_ratio="2160x2100")

    assert result.success
    assert json.loads(image_tool.requests[0].content)["size"] == "2160x2100"


@pytest.mark.asyncio
async def test_seedream_data_url_is_not_split_at_base64_comma(
    image_tool: SimpleNamespace,
) -> None:
    reference = "data:image/png;base64," + base64.b64encode(image_tool.png).decode("ascii")

    result = await image_tool.call(prompt="blue cup", model=MODEL, image=reference)

    assert result.success
    assert json.loads(image_tool.requests[0].content)["image"] == [reference]
    assert len(image_tool.uploads) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("absolute", [False, True])
async def test_seedream_local_reference_awaits_upload(
    image_tool: SimpleNamespace, absolute: bool
) -> None:
    directory = image_tool.config.data_dir / "files"
    directory.mkdir()
    reference = directory / "reference.png"
    reference.write_bytes(image_tool.png)

    result = await image_tool.call(
        prompt="blue cup", model=MODEL, image=str(reference) if absolute else reference.name
    )

    assert result.success
    assert len(image_tool.uploads) == 2
    assert image_tool.uploads[0][1] == {"prefix": "files"}
    assert json.loads(image_tool.requests[0].content)["image"] == [image_tool.uploads[0][2].url]
    assert result.images[0]["id"] == "oss-id-2"


@pytest.mark.asyncio
async def test_seedream_remote_reference_is_downloaded_asynchronously(
    image_tool: SimpleNamespace,
) -> None:
    reference = "https://input.example.test/reference.png"

    result = await image_tool.call(prompt="blue cup", model=MODEL, image=reference)

    assert result.success
    assert [str(request.url) for request in image_tool.downloads] == [
        reference,
        "https://output.example.test/generated.png",
    ]
    assert json.loads(image_tool.requests[0].content)["image"] == [reference]


@pytest.mark.asyncio
async def test_seedream_http_request_rejects_private_reference_before_download(
    image_tool: SimpleNamespace,
) -> None:
    with source_access.http_image_sources():
        result = await image_tool.call(
            prompt="blue cup", model=MODEL, image="http://127.0.0.1/private.png"
        )

    assert result.success is False
    assert not image_tool.requests
    assert not image_tool.downloads
    assert not image_tool.uploads


@pytest.mark.asyncio
async def test_seedream_http_request_does_not_follow_reference_redirects(
    image_tool: SimpleNamespace,
) -> None:
    image_tool.reference_redirect = True
    reference = "https://8.8.8.8/reference.png"

    with source_access.http_image_sources():
        result = await image_tool.call(prompt="blue cup", model=MODEL, image=reference)

    assert result.success is False
    assert [str(request.url) for request in image_tool.downloads] == [reference]
    assert not image_tool.requests
    assert not image_tool.uploads
    assert all(client.is_closed for client in image_tool.download_clients)


@pytest.mark.asyncio
async def test_seedream_55_accepts_ten_reference_images(image_tool: SimpleNamespace) -> None:
    reference = "data:image/png;base64," + base64.b64encode(image_tool.png).decode("ascii")
    references = [reference] * 10

    result = await image_tool.call(prompt="blue cup", model=MODEL, image=references)

    assert result.success
    assert json.loads(image_tool.requests[0].content)["image"] == references


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["configuration", "reference", "upstream", "empty", "image_error", "download"]
)
async def test_seedream_failures_are_safe_and_close_clients(
    image_tool: SimpleNamespace, failure: str
) -> None:
    kwargs = {}
    if failure == "configuration":
        image_tool.config.providers.volcengine = None
    elif failure == "reference":
        kwargs["image"] = "missing.png"
    elif failure == "upstream":
        image_tool.status = 503
    elif failure == "empty":
        image_tool.images = []
    elif failure == "image_error":
        image_tool.images = [{"error": {"code": "test", "message": "private upstream detail"}}]
    else:
        image_tool.download_status = 503

    result = await image_tool.call(prompt="blue cup", model=MODEL, **kwargs)

    assert isinstance(result, ImageToolResponse)
    assert result.success is False
    assert result.image_model == MODEL
    assert result.error == "image_tool_failed"
    assert "private upstream detail" not in result.content
    assert not result.images
    assert not image_tool.uploads
    if failure in {"configuration", "reference"}:
        assert not image_tool.requests
    elif failure == "upstream":
        assert len(image_tool.requests) == 1
    assert all(client.is_closed for client in image_tool.sdk_clients)
    assert all(client.is_closed for client in image_tool.download_clients)


@pytest.mark.asyncio
async def test_seedream_upload_failure_is_sanitized(
    image_tool: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def upload_failure(*args: object, **kwargs: object) -> ImageInfo:
        raise RuntimeError("private storage detail")

    monkeypatch.setattr(image_tool.module, "upload_image", upload_failure)
    result = await image_tool.call(prompt="blue cup", model=MODEL)

    assert result.success is False
    assert result.image_model == MODEL
    assert result.error == "image_tool_failed"
    assert "private storage detail" not in result.content
    assert all(client.is_closed for client in image_tool.sdk_clients)
    assert all(client.is_closed for client in image_tool.download_clients)


@pytest.mark.asyncio
async def test_seedream_cancellation_propagates_and_closes_sdk(
    image_tool: SimpleNamespace,
) -> None:
    image_tool.cancel = True

    with pytest.raises(asyncio.CancelledError):
        await image_tool.call(prompt="blue cup", model=MODEL)

    assert not image_tool.uploads
    assert image_tool.sdk_clients
    assert all(client.is_closed for client in image_tool.sdk_clients)
    assert all(client.is_closed for client in image_tool.download_clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["4K", "too_many_references"])
async def test_seedream_55_rejects_unsupported_inputs_before_request(
    image_tool: SimpleNamespace, failure: str
) -> None:
    kwargs = (
        {"image_size": "4K"} if failure == "4K" else {"image": ["data:image/png;base64,a"] * 11}
    )

    result = await image_tool.call(prompt="blue cup", model=MODEL, **kwargs)

    assert result.success is False
    assert result.image_model == MODEL
    assert not image_tool.requests
    assert not image_tool.downloads
    assert not image_tool.uploads


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["doubao-seedream-4-0-250828", "doubao-seedream-4-5-251128"])
async def test_legacy_models_keep_four_k_without_unsupported_output_format(
    image_tool: SimpleNamespace, model: str
) -> None:
    result = await image_tool.call(prompt="blue cup", model=model, image_size="4K")

    assert result.success
    assert result.image_model == model
    payload = json.loads(image_tool.requests[0].content)
    assert payload["size"] == "4K"
    assert not payload.get("output_format")
