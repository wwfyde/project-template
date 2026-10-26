import base64
import json
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
from types import SimpleNamespace
from typing import Any, Callable

import httpx2
import pytest
from PIL import Image

from api.core.config import LLMProvider
from api.images.config import ImagesConfig
from api.images.contracts import ImageFailure, ImageProvider, ProviderInput
from api.images.providers import _veimagex_sdk, build_providers


def png(color: str = "red") -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), color).save(output, format="PNG")
    return output.getvalue()


def settings(**image_settings: object) -> SimpleNamespace:
    return SimpleNamespace(
        proxy_url=None,
        images=ImagesConfig(**image_settings),
        providers=LLMProvider.model_validate(
            {
                "openai": {
                    "base_url": "https://gpt.example/v1",
                    "api_key": "secret-gpt",
                },
                "google": {
                    "base_url": "https://gemini.example",
                    "api_key": "secret-gemini",
                },
                "volcengine": {
                    "base_url": "https://ark.example/api/v3",
                    "api_key": "secret-seedream",
                },
            }
        ),
    )


def mock_async(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> None:
    client = httpx2.AsyncClient
    monkeypatch.setattr(
        httpx2,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx2.MockTransport(handler), **kwargs),
    )


def edit_input(provider: ImageProvider, **overrides: object) -> ProviderInput:
    return ProviderInput(
        **(
            {
                "operation": "erase",
                "model": provider.info.default_model,
                "image": png(),
                "mask": png("white"),
            }
            | overrides
        )
    )


@pytest.mark.asyncio
async def test_gpt_native_mask_translates_white_selection_to_transparent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    mask = Image.new("L", (2, 2), 0)
    mask.putpixel((0, 0), 255)
    buffer = BytesIO()
    mask.save(buffer, format="PNG")

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        assert str(request.url) == "https://gpt.example/v1/images/edits"
        assert request.headers["authorization"] == "Bearer secret-gpt"
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: "
            + request.headers["content-type"].encode()
            + b"\r\n\r\n"
            + request.content
        )
        fields = {
            part.get_param("name", header="content-disposition"): part.get_payload(
                decode=True
            )
            for part in message.iter_parts()
        }
        assert fields["model"] == b"gpt-image-2.5-sunburst"
        assert fields["image"] == png()
        converted = Image.open(BytesIO(fields["mask"]))
        assert converted.mode == "RGBA"
        assert converted.getpixel((0, 0))[3] == 0
        assert converted.getpixel((1, 1))[3] == 255
        return httpx2.Response(
            200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]}
        )

    mock_async(monkeypatch, handler)
    provider = build_providers(settings())["gpt"]
    assert await provider.edit(edit_input(provider, mask=buffer.getvalue())) == png()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_gpt_cutout_requests_transparent_png(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert b'name="background"\r\n\r\ntransparent' in request.content
        assert b'name="mask"' not in request.content
        return httpx2.Response(
            200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]}
        )

    mock_async(monkeypatch, handler)
    provider = build_providers(settings())["gpt"]
    await provider.edit(edit_input(provider, operation="remove_background", mask=None))


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_id", ["gemini", "seedream"])
async def test_reference_mask_payloads_and_decoding(
    monkeypatch: pytest.MonkeyPatch, provider_id: str
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        payload = json.loads(request.content)
        if provider_id == "gemini":
            assert (
                str(request.url)
                == "https://gemini.example/v1beta/models/gemini-3.1-flash-image:generateContent"
            )
            assert request.headers["x-goog-api-key"] == "secret-gemini"
            parts = payload["contents"][0]["parts"]
            assert "white pixels" in parts[0]["text"]
            assert base64.b64decode(parts[1]["inlineData"]["data"]) == png()
            assert base64.b64decode(parts[2]["inlineData"]["data"]) == png("white")
            return httpx2.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": base64.b64encode(png()).decode(),
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
            )
        assert str(request.url) == "https://ark.example/api/v3/images/generations"
        assert request.headers["authorization"] == "Bearer secret-seedream"
        assert len(payload["image"]) == 2
        assert base64.b64decode(payload["image"][1].split(",", 1)[1]) == png("white")
        assert payload["response_format"] == "b64_json"
        assert "sequential_image_generation" not in payload
        return httpx2.Response(
            200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]}
        )

    mock_async(monkeypatch, handler)
    provider = build_providers(settings())[provider_id]
    assert await provider.edit(edit_input(provider)) == png()
    assert provider.info.mask_mode == "reference"
    with pytest.raises(ImageFailure, match="does not support"):
        await provider.edit(
            edit_input(provider, operation="remove_background", mask=None)
        )


@pytest.mark.asyncio
async def test_gemini_compatible_base_url_uses_native_image_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert (
            request.url.path == "/v1beta/models/gemini-3.1-flash-image:generateContent"
        )
        return httpx2.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "image/png",
                                        "data": base64.b64encode(png()).decode(),
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    mock_async(monkeypatch, handler)
    config = settings()
    config.providers.google.base_url = "https://gemini.example/v1beta/openai/"
    provider = build_providers(config)["gemini"]
    assert await provider.edit(edit_input(provider)) == png()


@pytest.mark.asyncio
async def test_provider_timeout_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("secret request details")

    mock_async(monkeypatch, handler)
    provider = build_providers(settings())["gpt"]
    with pytest.raises(ImageFailure) as caught:
        await provider.edit(edit_input(provider))
    assert caught.value.code == "provider_timeout"
    assert caught.value.status == 504
    assert "secret" not in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": [{"b64_json": "%%%"}]},
        {"data": [{"url": "http://127.0.0.1/secret"}]},
        {"data": [{"b64_json": ""}]},
    ],
)
async def test_invalid_results_fail_closed(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    mock_async(monkeypatch, lambda request: httpx2.Response(200, json=payload))
    provider = build_providers(settings())["gpt"]
    with pytest.raises(ImageFailure) as caught:
        await provider.edit(edit_input(provider))
    assert caught.value.code == "provider_invalid_response"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, code",
    [
        (401, "provider_failed"),
        (429, "provider_rate_limited"),
        (500, "provider_failed"),
        (302, "provider_failed"),
    ],
)
async def test_upstream_failures_are_sanitized_and_not_retried(
    monkeypatch: pytest.MonkeyPatch, status: int, code: str
) -> None:
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(
            status,
            text="secret-gpt sensitive provider body",
            headers={"Location": "https://elsewhere.example"},
        )

    mock_async(monkeypatch, handler)
    provider = build_providers(settings())["gpt"]
    with pytest.raises(ImageFailure) as caught:
        await provider.edit(edit_input(provider))
    assert caught.value.code == code
    assert "secret" not in str(caught.value)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_output_and_model_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        return httpx2.Response(
            200, json={"data": [{"b64_json": base64.b64encode(b"x" * 1025).decode()}]}
        )

    mock_async(monkeypatch, handler)
    provider = build_providers(settings(max_upload_bytes=1024))["gpt"]
    with pytest.raises(ImageFailure) as caught:
        await provider.edit(edit_input(provider, model="not-enabled"))
    assert caught.value.code == "unsupported_model"
    assert calls == []
    with pytest.raises(ImageFailure) as caught:
        await provider.edit(edit_input(provider))
    assert caught.value.code == "provider_invalid_response"


def test_missing_credentials_and_vertex_are_explicitly_unavailable() -> None:
    config = settings()
    config.providers.openai = None
    config.providers.google.use_vertexai = True
    providers = build_providers(config)
    assert set(providers) == {"local", "gpt", "gemini", "seedream", "veimagex"}
    assert providers["local"].info.configured
    assert not providers["gpt"].info.configured
    assert not providers["gemini"].info.configured
    assert "Vertex" in providers["gemini"].info.unavailable_reason
    assert not providers["veimagex"].info.configured
    assert "secret" not in json.dumps(
        [provider.info.model_dump() for provider in providers.values()]
    )


def test_veimagex_sdk_credentials_are_per_request() -> None:
    pytest.importorskip("volcengine")
    first, second = _veimagex_sdk("cn-north-1"), _veimagex_sdk("cn-north-1")
    try:
        assert first.service_info is not second.service_info
        assert first.service_info.credentials is not second.service_info.credentials
        first.set_ak("first-client")
        assert second.service_info.credentials.ak != "first-client"
    finally:
        first.session.close()
        second.session.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe_url", [False, True])
async def test_native_veimagex_sdk_upload_segment_and_download(
    monkeypatch: pytest.MonkeyPatch, unsafe_url: bool
) -> None:
    pytest.importorskip("volcengine")
    calls = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        action = request.url.params.get("Action")
        result: Any
        if action == "ApplyImageUpload":
            assert request.headers["authorization"].startswith("HMAC-SHA256 ")
            result = {
                "RequestId": "test",
                "UploadAddress": {
                    "UploadHosts": ["upload.example.com"],
                    "StoreInfos": [{"StoreUri": "source.png", "Auth": "upload-token"}],
                    "SessionKey": "session",
                },
            }
        elif request.url.host == "upload.example.com":
            assert request.method == "PUT"
            assert request.content == png()
            assert request.headers["authorization"] == "upload-token"
            return httpx2.Response(200, text="ok")
        elif action == "CommitImageUpload":
            result = {"Results": [{"Uri": "source.png", "UriStatus": 2000}]}
        elif action == "GetSegmentImage":
            assert request.url.params["Version"] == "2023-05-01"
            assert json.loads(request.content) == {
                "StoreUri": "source.png",
                "Class": "productv2",
                "Refine": True,
                "TransBg": False,
                "OutFormat": "png",
            }
            result = {"ResUri": "result.png"}
        elif action == "GetResourceURL":
            assert request.url.params["Domain"] == "images.example.com"
            assert request.url.params["URI"] == "result.png"
            assert request.url.params["Tpl"] == "original.image"
            result = {
                "URL": "https://attacker.example/result.png"
                if unsafe_url
                else "https://images.example.com/result.png?sign=temporary"
            }
        else:
            assert request.url.host == "images.example.com"
            assert "authorization" not in request.headers
            return httpx2.Response(
                200, content=png(), headers={"Content-Type": "image/png"}
            )
        return httpx2.Response(200, json={"ResponseMetadata": {}, "Result": result})

    client = httpx2.Client
    monkeypatch.setattr(
        httpx2,
        "Client",
        lambda **kwargs: client(transport=httpx2.MockTransport(handler), **kwargs),
    )
    provider = build_providers(
        settings(
            veimagex={
                "access_key": "test-ak",
                "secret_key": "test-sk",
                "service_id": "service",
                "domain": "images.example.com",
                "template": "original.image",
            }
        )
    )["veimagex"]
    assert provider.info.configured
    request = edit_input(provider, operation="remove_background", mask=None)
    if unsafe_url:
        with pytest.raises(ImageFailure) as caught:
            await provider.edit(request)
        assert caught.value.code == "provider_invalid_response"
        assert len(calls) == 5
    else:
        assert await provider.edit(request) == png()
        assert len(calls) == 6
