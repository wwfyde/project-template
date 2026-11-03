"""Responses image inputs are prepared without external network or model calls."""

import base64
from collections.abc import Callable
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from openai.types.responses import ResponseInputImageParam
from openai.types.responses.tool_param import ImageGenerationInputImageMask
from PIL import Image, UnidentifiedImageError
from pytest import MonkeyPatch

from api.tools.images import gpt


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
        return_value=SimpleNamespace(usage=None, output=[], output_text="")
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
        image_mask=mask,
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
        image_mask=mask if native_mask else mask_url,
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
        prompt="edit", images=[inline, native_inline, file_input], image_mask=mask
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
