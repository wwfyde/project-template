"""GPT image functions exercise the real SDK/HTTP contract with mocked OSS."""

import base64
import json
from collections.abc import Callable
from io import BytesIO
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from PIL import Image
from pydantic import SecretStr
from pytest import MonkeyPatch

from api.core.config import LLMConfig, settings
from api.tools.images import gpt, gpt_evolink
from api.tools.types import ImageInfo, ImageToolResponse

KEY = "test-provider-key"


def png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (8, 6), (20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def image_info() -> ImageInfo:
    return ImageInfo(
        id="oss-image-id",
        filename="oss-image-id.png",
        url="https://cdn.example/creative/gpt/oss-image-id.png",
        storage_key="creative/gpt/oss-image-id.png",
        mime_type="image/png",
        file_size=len(png()),
        width=8,
        height=6,
        sha256="upload-provided-sha256",
    )


@pytest.fixture
def provider_config(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "proxy_url", None)
    for provider in ("openai", "evolink"):
        monkeypatch.setattr(
            settings.providers,
            provider,
            LLMConfig(
                base_url=f"https://{provider}.example/v1", api_key=SecretStr(KEY)
            ),
        )


def mock_sdk_transport(
    monkeypatch: MonkeyPatch, handler: Callable[[httpx2.Request], httpx2.Response]
) -> list[dict[str, object]]:
    options = []
    client_type = httpx2.Client

    class Client(client_type):
        def __init__(self, **kwargs: object) -> None:
            options.append(dict(kwargs))
            super().__init__(transport=httpx2.MockTransport(handler), **kwargs)

    monkeypatch.setattr(gpt.httpx2, "Client", Client)
    return options


def generated_response() -> httpx2.Response:
    return httpx2.Response(
        200,
        json={
            "created": 1,
            "data": [{"b64_json": base64.b64encode(png()).decode()}],
            "output_format": "png",
            "usage": {
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
                "input_tokens_details": {"text_tokens": 1, "image_tokens": 0},
            },
        },
    )


@pytest.mark.parametrize(
    "suffix,model",
    [
        ("2", "gpt-image-2"),
        ("2_5_flare", "gpt-image-2.5-flare"),
        ("2_5_sunburst", "gpt-image-2.5-sunburst"),
        ("2_5", "gpt-image-2.5-flare"),
    ],
)
def test_openai_tool_uses_model_credentials_and_oss_metadata(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    image_info: ImageInfo,
    suffix: str,
    model: str,
) -> None:
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert str(request.url) == "https://openai.example/v1/images/generations"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        return generated_response()

    options = mock_sdk_transport(monkeypatch, handler)
    upload = AsyncMock(return_value=image_info)
    monkeypatch.setattr(gpt, "upload_image", upload)
    result = getattr(gpt, f"image_create_with_gpt_image_{suffix}")(
        "draw a cup", image_size="2K", aspect_ratio="16:9", quality="high", n=2
    )
    assert isinstance(result, ImageToolResponse)
    assert result.success, result
    assert result.image_model == model
    assert result.images == [
        image_info.model_dump(exclude_unset=True, exclude_none=True)
    ]
    assert result.usage["total_tokens"] == 3
    payload = json.loads(requests[0].content)
    assert payload == {
        "model": model,
        "prompt": "draw a cup",
        "quality": "high",
        "n": 2,
        "size": "2048x1152",
        "output_format": "png",
    }
    assert options[0]["proxy"] is None
    assert options[0]["trust_env"] is False
    upload.assert_awaited_once_with("generated.png", png(), prefix="creative/gpt")


@pytest.mark.parametrize("inline", [False, True])
def test_openai_reference_images_become_multipart_bytes(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    image_info: ImageInfo,
    inline: bool,
) -> None:
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == "GET":
            assert "authorization" not in request.headers
            assert str(request.url) == "https://reference.example/source.png"
            return httpx2.Response(200, content=png())
        assert request.url.path == "/v1/images/edits"
        assert request.headers["content-type"].startswith("multipart/form-data")
        assert png() in request.content
        assert b"reference-0.png" in request.content
        assert b"2048x1152" in request.content
        return generated_response()

    mock_sdk_transport(monkeypatch, handler)
    upload = AsyncMock(return_value=image_info)
    monkeypatch.setattr(gpt, "upload_image", upload)
    reference = (
        "data:image/png;base64," + base64.b64encode(png()).decode()
        if inline
        else "https://reference.example/source.png"
    )
    result = gpt.image_create_with_gpt_image_2(
        "make the cup blue", image_urls=reference, aspect_ratio="2048x1152"
    )
    assert result.success, result
    assert [request.method for request in requests] == (
        ["POST"] if inline else ["GET", "POST"]
    )
    upload.assert_awaited_once()


@pytest.mark.parametrize("suffix", ["2", "2_5_flare", "2_5_sunburst"])
def test_openai_entry_point_selects_evolink_function(
    monkeypatch: MonkeyPatch, suffix: str
) -> None:
    expected = ImageToolResponse(image_model="selected-model", content="", images=[])
    function = Mock(return_value=expected)
    monkeypatch.setattr(gpt_evolink, f"image_create_with_gpt_image_{suffix}", function)
    result = getattr(gpt, f"image_create_with_gpt_image_{suffix}")(
        "draw", provider="evolink", aspect_ratio="1:1", image_size="2K", n=3
    )
    assert result is expected
    function.assert_called_once_with(
        "draw", image_urls=None, aspect_ratio="1:1", image_size="2K", quality="low", n=3
    )


@pytest.mark.parametrize(
    "suffix,model",
    [
        ("2", "gpt-image-2"),
        ("2_5_flare", "gpt-image-2.5-flare"),
        ("2_5_sunburst", "gpt-image-2.5-sunburst"),
        ("2_5", "gpt-image-2.5-flare"),
    ],
)
def test_evolink_tool_polls_downloads_and_uses_oss_metadata(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    image_info: ImageInfo,
    suffix: str,
    model: str,
) -> None:
    post = Mock(
        return_value=httpx2.Response(
            200,
            json={"id": "task-id"},
            request=httpx2.Request("POST", "https://evolink.example"),
        )
    )
    poll = Mock(
        return_value=httpx2.Response(
            200,
            json={
                "status": "completed",
                "results": ["https://result.example/image.png"],
            },
            request=httpx2.Request("GET", "https://evolink.example"),
        )
    )
    download = Mock(
        return_value=httpx2.Response(
            200,
            content=png(),
            request=httpx2.Request("GET", "https://result.example/image.png"),
        )
    )
    upload = AsyncMock(return_value=image_info)
    monkeypatch.setattr(gpt_evolink.requests, "post", post)
    monkeypatch.setattr(gpt_evolink.requests, "get", poll)
    monkeypatch.setattr(gpt_evolink.httpx2, "get", download)
    monkeypatch.setattr(gpt_evolink, "upload_image", upload)
    result = getattr(gpt_evolink, f"image_create_with_gpt_image_{suffix}")(
        "draw",
        image_urls="https://ref.example/1.png， https://ref.example/2.png",
        aspect_ratio="4:3",
        image_size="2K",
        quality="medium",
        n=2,
    )
    assert result.success, result
    assert result.image_model == model
    assert result.images == [
        image_info.model_dump(exclude_unset=True, exclude_none=True)
    ]
    assert post.call_args.args == ("https://evolink.example/v1/images/generations",)
    assert post.call_args.kwargs["headers"]["Authorization"] == f"Bearer {KEY}"
    assert post.call_args.kwargs["json"] == {
        "model": model,
        "prompt": "draw",
        "n": 2,
        "quality": "medium",
        "resolution": "2K",
        "size": "4:3",
        "image_urls": ["https://ref.example/1.png", "https://ref.example/2.png"],
    }
    assert post.call_args.kwargs["timeout"] > 0
    poll.assert_called_once_with(
        "https://evolink.example/v1/tasks/task-id",
        headers={"Authorization": f"Bearer {KEY}"},
        timeout=60,
        proxies=None,
    )
    download.assert_called_once_with(
        "https://result.example/image.png", timeout=180, proxy=None
    )
    upload.assert_awaited_once_with("generated.png", png(), prefix="creative/gpt")


def test_provider_and_upload_failures_return_tool_response_without_private_error(
    monkeypatch: MonkeyPatch, provider_config: None
) -> None:
    mock_sdk_transport(monkeypatch, lambda request: generated_response())
    monkeypatch.setattr(
        gpt, "upload_image", AsyncMock(side_effect=RuntimeError("private OSS secret"))
    )
    response = gpt.image_create_with_gpt_image_2("draw")
    assert response.success is False
    assert "private" not in response.model_dump_json()
    monkeypatch.setattr(
        gpt_evolink,
        "create_task",
        Mock(side_effect=RuntimeError("private upstream secret")),
    )
    response = gpt_evolink.image_create_with_gpt_image_2("draw")
    assert response.success is False
    assert "private" not in response.model_dump_json()


def test_unconfigured_providers_do_not_require_import_time_clients(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings.providers, "openai", None)
    monkeypatch.setattr(settings.providers, "evolink", None)
    assert gpt.image_create_with_gpt_image_2("draw").success is False
    assert gpt_evolink.image_create_with_gpt_image_2("draw").success is False


def encoded_image(
    image_format: str = "PNG", *, alpha: bool = False, size: tuple[int, int] = (8, 6)
) -> bytes:
    output = BytesIO()
    Image.new(
        "RGBA" if alpha else "RGB", size, (20, 40, 60, 0) if alpha else (20, 40, 60)
    ).save(output, format=image_format)
    return output.getvalue()


def data_url(content: bytes, image_format: str = "png") -> str:
    return f"data:image/{image_format};base64," + base64.b64encode(content).decode()


@pytest.mark.parametrize(
    "suffix,quality", [("2_5_flare", "xhigh"), ("2_5_sunburst", "max")]
)
@pytest.mark.parametrize("image_format", ["jpeg", "webp", "png"])
def test_extended_output_options_and_actual_uploaded_format(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    image_info: ImageInfo,
    suffix: str,
    quality: str,
    image_format: str,
) -> None:
    output = encoded_image(image_format.upper(), alpha=image_format != "jpeg")
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "created": 1,
                "output_format": image_format,
                "data": [{"b64_json": base64.b64encode(output).decode()}],
            },
        )

    mock_sdk_transport(monkeypatch, handler)
    metadata = image_info.model_copy(update={"mime_type": "image/" + image_format})
    upload = AsyncMock(return_value=metadata)
    monkeypatch.setattr(gpt, "upload_image", upload)
    options = {
        "output_format": image_format,
        "background": "opaque" if image_format == "jpeg" else "transparent",
    }
    if image_format != "png":
        options["output_compression"] = 75
    result = getattr(gpt, f"image_create_with_gpt_image_{suffix}")(
        "draw a cup",
        quality=quality,
        size="1536x864",
        moderation="low",
        safety_identifier="hashed-user-id",
        **options,
    )
    assert result.success, result
    body = json.loads(requests[0].content)
    assert body["quality"] == quality
    assert body["size"] == "1536x864"
    assert body["output_format"] == image_format
    assert body["background"] == options["background"]
    assert body["moderation"] == "low"
    assert body["safety_identifier"] == "hashed-user-id"
    extension = "jpg" if image_format == "jpeg" else image_format
    upload.assert_awaited_once_with(
        f"generated.{extension}", output, prefix="creative/gpt"
    )
    assert result.images == [
        metadata.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    ]
    assert result.input_params["output_format"] == image_format
    assert result.input_params["quality"] == quality
    assert "hashed-user-id" not in json.dumps(result.input_params)
    assert "draw a cup" not in json.dumps(result.input_params)


def test_masked_edit_converts_first_image_to_png_and_passes_sdk_extra_body(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    image_info: ImageInfo,
) -> None:
    reference = encoded_image("JPEG")
    mask = encoded_image("PNG", alpha=True)
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == "GET":
            assert "authorization" not in request.headers
            return httpx2.Response(
                200, content=mask if request.url.path == "/mask.png" else reference
            )
        assert request.url.path == "/v1/images/edits"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert b"reference-0.png" in request.content
        assert b'filename="mask.png"' in request.content
        assert mask in request.content
        assert b'name="moderation"' in request.content
        assert b'name="safety_identifier"' in request.content
        assert b"hashed-user-id" in request.content
        assert b"input_fidelity" not in request.content
        return generated_response()

    mock_sdk_transport(monkeypatch, handler)
    monkeypatch.setattr(gpt, "upload_image", AsyncMock(return_value=image_info))
    result = gpt.image_create_with_gpt_image_2_5_sunburst(
        "change background",
        image_urls=["https://reference.example/source.jpg"],
        mask_url="https://reference.example/mask.png",
        quality="max",
        moderation="auto",
        safety_identifier="hashed-user-id",
    )
    assert result.success, result
    assert [request.method for request in requests] == ["GET", "GET", "POST"]
    assert result.input_params["operation"] == "edit"
    assert result.input_params["mask"] is True
    assert "reference.example" not in json.dumps(result.input_params)


@pytest.mark.parametrize(
    "parameters,code",
    [
        ({"prompt": ""}, "invalid_parameters"),
        ({"prompt": "x" * 32001}, "invalid_parameters"),
        ({"n": 0}, "invalid_parameters"),
        ({"n": True}, "invalid_parameters"),
        ({"quality": "xhigh"}, "invalid_parameters"),
        ({"size": "1024x1024", "aspect_ratio": "1:1"}, "invalid_parameters"),
        ({"size": "3840x3840"}, "invalid_parameters"),
        ({"aspect_ratio": "4:1"}, "invalid_parameters"),
        ({"aspect_ratio": "2.5:1"}, "invalid_parameters"),
        ({"aspect_ratio": "1024.9x1024"}, "invalid_parameters"),
        ({"background": "transparent", "output_format": "jpeg"}, "invalid_parameters"),
        ({"output_compression": 70}, "invalid_parameters"),
        ({"output_format": "webp", "output_compression": 101}, "invalid_parameters"),
        ({"safety_identifier": "a" * 129}, "invalid_parameters"),
        (
            {"image_urls": ["https://reference.example/image.png"] * 17},
            "too_many_images",
        ),
        ({"image_urls": [42]}, "invalid_image_input"),
        ({"mask_url": "https://reference.example/mask.png"}, "invalid_mask"),
    ],
)
def test_invalid_parameters_never_invoke_model_or_upload(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    parameters: dict,
    code: str,
) -> None:
    model = Mock(side_effect=AssertionError("Model was invoked"))
    upload = AsyncMock(side_effect=AssertionError("Upload was invoked"))
    monkeypatch.setattr(gpt, "OpenAI", model)
    monkeypatch.setattr(gpt, "upload_image", upload)
    result = gpt.image_create_with_gpt_image_2(**{"prompt": "draw", **parameters})
    assert result.success is False
    assert result.error == code
    model.assert_not_called()
    upload.assert_not_awaited()


@pytest.mark.parametrize("kind", ["non_png", "missing_alpha", "wrong_size"])
def test_invalid_mask_is_rejected_before_model_call(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    kind: str,
) -> None:
    mock_sdk_transport(
        monkeypatch, lambda request: pytest.fail("Unexpected HTTP request")
    )
    model = Mock(side_effect=AssertionError("Model was invoked"))
    monkeypatch.setattr(gpt, "OpenAI", model)
    content = (
        encoded_image("JPEG")
        if kind == "non_png"
        else encoded_image(
            "PNG",
            alpha=kind != "missing_alpha",
            size=(4, 4) if kind == "wrong_size" else (8, 6),
        )
    )
    result = gpt.image_create_with_gpt_image_2(
        "draw",
        image_urls=data_url(png()),
        mask_url=data_url(content, "jpeg" if kind == "non_png" else "png"),
    )
    assert result.success is False
    assert result.error == "invalid_mask"
    model.assert_not_called()


@pytest.mark.parametrize(
    "reference",
    [
        "data:image/png;base64,not-valid",
        "data:image/png;base64," + base64.b64encode(b"not an image").decode(),
    ],
)
def test_invalid_reference_data_is_classified_as_input_failure(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    reference: str,
) -> None:
    mock_sdk_transport(
        monkeypatch, lambda request: pytest.fail("Unexpected HTTP request")
    )
    result = gpt.image_create_with_gpt_image_2("draw", image_urls=reference)
    assert result.error == "invalid_image_input"
    assert result.success is False


def test_reference_download_is_bounded_before_model_call(
    monkeypatch: MonkeyPatch,
    provider_config: None,
) -> None:
    monkeypatch.setattr(gpt, "MAX_IMAGE_BYTES", 32)
    requests = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, content=b"x" * 33)

    mock_sdk_transport(monkeypatch, handler)
    result = gpt.image_create_with_gpt_image_2(
        "draw", image_urls="https://reference.example/large.png"
    )
    assert result.error == "image_input_too_large"
    assert len(requests) == 1 and requests[0].method == "GET"


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "provider_auth_failed"),
        (403, "provider_auth_failed"),
        (429, "provider_rate_limited"),
        (400, "provider_failed"),
        (500, "provider_failed"),
    ],
)
def test_provider_status_errors_are_distinct_and_redacted(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    status: int,
    code: str,
) -> None:
    mock_sdk_transport(
        monkeypatch,
        lambda request: httpx2.Response(
            status,
            json={
                "error": {
                    "message": "private-provider-secret",
                    "type": "provider_error",
                }
            },
        ),
    )
    result = gpt.image_create_with_gpt_image_2("draw")
    assert result.error == code
    assert result.success is False
    assert "private-provider-secret" not in result.model_dump_json()


def test_provider_timeout_is_distinct_from_upload_failure(
    monkeypatch: MonkeyPatch,
    provider_config: None,
) -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("private transport detail", request=request)

    mock_sdk_transport(monkeypatch, timeout)
    result = gpt.image_create_with_gpt_image_2("draw")
    assert result.error == "provider_timeout"
    assert "private transport" not in result.model_dump_json()


@pytest.mark.parametrize(
    "body,code",
    [
        ({"created": 1, "data": []}, "no_image_returned"),
        (
            {"created": 1, "data": [{"b64_json": "not-base64"}]},
            "provider_invalid_response",
        ),
        (
            {
                "created": 1,
                "data": [{"b64_json": base64.b64encode(b"not an image").decode()}],
            },
            "provider_invalid_response",
        ),
        (
            {"created": 1, "data": [{"url": "https://provider.example/private.png"}]},
            "provider_invalid_response",
        ),
        (
            {
                "created": 1,
                "data": [{"b64_json": base64.b64encode(png()).decode()}] * 2,
            },
            "provider_invalid_response",
        ),
        ({"created": 1, "usage": "invalid", "data": []}, "provider_invalid_response"),
    ],
)
def test_invalid_model_outputs_are_rejected_before_upload(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    body: dict,
    code: str,
) -> None:
    mock_sdk_transport(monkeypatch, lambda request: httpx2.Response(200, json=body))
    upload = AsyncMock()
    monkeypatch.setattr(gpt, "upload_image", upload)
    result = gpt.image_create_with_gpt_image_2("draw")
    assert result.error == code
    assert result.success is False
    upload.assert_not_awaited()


def test_upload_failure_retains_usage_and_effective_parameters(
    monkeypatch: MonkeyPatch,
    provider_config: None,
) -> None:
    mock_sdk_transport(monkeypatch, lambda request: generated_response())
    monkeypatch.setattr(
        gpt, "upload_image", AsyncMock(side_effect=RuntimeError("private OSS key"))
    )
    result = gpt.image_create_with_gpt_image_2("draw", size="1024x1024")
    assert result.error == "image_upload_failed"
    assert result.usage["total_tokens"] == 3
    assert result.input_params["size"] == "1024x1024"
    assert "private OSS" not in result.model_dump_json()


@pytest.mark.parametrize(
    "parameters",
    [
        {"size": "1024x1024"},
        {"background": "opaque"},
        {"output_format": "png"},
        {"moderation": "auto"},
        {"safety_identifier": "opaque-id"},
        {"quality": "xhigh"},
        {"output_format": "webp", "output_compression": 90},
    ],
)
def test_evolink_rejects_unsupported_extended_parameters_without_dispatch(
    monkeypatch: MonkeyPatch,
    parameters: dict,
) -> None:
    tool = Mock(side_effect=AssertionError("Evolink was invoked"))
    monkeypatch.setattr(gpt_evolink, "image_create_with_gpt_image_2_5_flare", tool)
    result = gpt.image_create_with_gpt_image_2_5_flare(
        "draw", provider="evolink", **parameters
    )
    assert result.error == "unsupported_provider_parameter"
    assert result.success is False
    tool.assert_not_called()


def test_http_mask_source_guard_cannot_access_local_addresses(
    monkeypatch: MonkeyPatch,
    provider_config: None,
) -> None:
    from api.images.source_access import http_image_sources

    mock_sdk_transport(
        monkeypatch, lambda request: pytest.fail("Unexpected HTTP request")
    )
    reference = data_url(png())
    with http_image_sources(reference):
        result = gpt.image_create_with_gpt_image_2(
            "draw", image_urls=reference, mask_url="http://127.0.0.1/private-mask.png"
        )
    assert result.error == "invalid_image_source"
    assert result.success is False
    assert "127.0.0.1" not in result.model_dump_json()


def test_non_json_model_response_is_classified_as_invalid(
    monkeypatch: MonkeyPatch,
    provider_config: None,
) -> None:
    mock_sdk_transport(
        monkeypatch, lambda request: httpx2.Response(200, text="private upstream body")
    )
    result = gpt.image_create_with_gpt_image_2("draw")
    assert result.error == "provider_invalid_response"
    assert "private upstream" not in result.model_dump_json()


def test_partial_upload_failure_preserves_already_uploaded_metadata(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    image_info: ImageInfo,
) -> None:
    body = {"created": 1, "data": [{"b64_json": base64.b64encode(png()).decode()}] * 2}
    mock_sdk_transport(monkeypatch, lambda request: httpx2.Response(200, json=body))
    upload = AsyncMock(side_effect=[image_info, RuntimeError("private OSS failure")])
    monkeypatch.setattr(gpt, "upload_image", upload)
    result = gpt.image_create_with_gpt_image_2("draw", n=2)
    assert result.error == "image_upload_failed"
    assert result.success is False
    assert result.images == [
        image_info.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    ]
    assert upload.await_count == 2


def test_invalid_output_format_and_excess_bytes_never_reach_oss(
    monkeypatch: MonkeyPatch,
    provider_config: None,
) -> None:
    output = encoded_image("GIF")
    mock_sdk_transport(
        monkeypatch,
        lambda request: httpx2.Response(
            200,
            json={
                "created": 1,
                "data": [{"b64_json": base64.b64encode(output).decode()}],
            },
        ),
    )
    upload = AsyncMock()
    monkeypatch.setattr(gpt, "upload_image", upload)
    assert (
        gpt.image_create_with_gpt_image_2("draw").error == "provider_invalid_response"
    )
    monkeypatch.setattr(gpt, "MAX_IMAGE_BYTES", 10)
    assert (
        gpt.image_create_with_gpt_image_2("draw").error == "provider_invalid_response"
    )
    upload.assert_not_awaited()
