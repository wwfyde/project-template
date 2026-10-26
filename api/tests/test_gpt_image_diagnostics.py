"""Reproduce an opaque GPT edit 500 without calling an external provider."""

import base64
import json
import logging
import math
from unittest.mock import AsyncMock

import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import LogCaptureFixture, MonkeyPatch

from api.core.log import ConsoleFormatter, RequestContextFilter
from api.core.request_context import RequestContextConfig, RequestContextMiddleware
from api.tools.images import gpt
from api.tools.types import ImageToolResponse
from test_gpt_image_tools import (
    KEY,
    mock_sdk_transport,
    png,
    provider_config as provider_config,
)


def test_gpt_edit_500_has_safe_correlated_diagnostics(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    caplog: LogCaptureFixture,
) -> None:
    prompt = "Generate a vertical campaign image. PRIVATE_PROMPT_MARKER"
    first_url = "https://references.example/first.png?signature=private-signature-one"
    second_url = "https://references.example/second.png?signature=private-signature-two"
    encoded = base64.b64encode(png()).decode()
    request_id = "req-diagnostics-upstream-500"
    message = (
        "Renderer is temporarily unavailable. "
        f"key={KEY}; prompt={prompt}; image={first_url}; other={second_url}; "
        f"data:image/png;base64,{encoded}; " + "Please retry later. " * 60
    )
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.method == "GET":
            assert "authorization" not in request.headers
            assert str(request.url) in {first_url, second_url}
            return httpx2.Response(200, content=png())
        assert str(request.url) == "https://openai.example/v1/images/edits"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert request.headers["content-type"].startswith("multipart/form-data")
        assert request.content.count(b'filename="reference-') == 2
        # This is the existing legal square size calculation, not evidence that
        # the upstream 500 was caused by a prompt or aspect-ratio mismatch.
        assert b'name="size"\r\n\r\n2880x2880' in request.content
        assert b'name="quality"\r\n\r\nmedium' in request.content
        assert b'name="n"\r\n\r\n1' in request.content
        return httpx2.Response(
            500,
            headers={"x-request-id": request_id},
            json={
                "error": {
                    "code": "renderer_unavailable",
                    "type": "server_error",
                    "param": "image",
                    "message": message,
                }
            },
        )

    mock_sdk_transport(monkeypatch, handler)
    upload = AsyncMock(side_effect=AssertionError("OSS must not be called after 500"))
    monkeypatch.setattr(gpt, "upload_image", upload)
    with caplog.at_level(logging.WARNING, logger="api.tools.images.gpt"):
        result = gpt.image_create_with_gpt_image_2_5_flare(
            prompt,
            image_urls=[first_url, second_url],
            image_size="4K",
            quality="medium",
            n=1,
        )

    assert [request.method for request in requests] == ["GET", "GET", "POST"]
    upload.assert_not_awaited()
    assert result.success is False
    assert result.error == "provider_failed"
    assert result.input_params["size"] == "2880x2880"
    expected = {
        "provider": "openai",
        "model": "gpt-image-2.5-flare",
        "operation": "edit",
        "size": "2880x2880",
        "status": 500,
        "upstream_request_id": request_id,
        "upstream_host": "openai.example",
        "exception_type": "InternalServerError",
        "error_code": "renderer_unavailable",
        "error_type": "server_error",
        "error_param": "image",
    }
    records = [
        record for record in caplog.records if record.name == "api.tools.images.gpt"
    ]
    assert len(records) == 1
    record = records[0]
    required = set(expected) | {"elapsed_ms", "error_message"}
    assert required <= record.__dict__.keys(), (
        "GPT edit 500 log is missing diagnostic fields: "
        + ", ".join(sorted(required - record.__dict__.keys()))
    )
    assert result.data is not None and isinstance(result.data.get("diagnostics"), dict)
    diagnostics = result.data["diagnostics"]
    for name, value in expected.items():
        assert getattr(record, name) == value
        assert diagnostics[name] == value
    for diagnostic in (record.__dict__, diagnostics):
        elapsed = diagnostic["elapsed_ms"]
        assert isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool)
        assert math.isfinite(elapsed) and elapsed >= 0
        assert isinstance(diagnostic["error_message"], str)
        assert diagnostic["error_message"].startswith(
            "Renderer is temporarily unavailable."
        )
        assert len(diagnostic["error_message"]) <= 512

    exposed = json.dumps(record.__dict__, default=str)
    exposed += record.getMessage() + result.model_dump_json()
    for private in (
        KEY,
        prompt,
        "PRIVATE_PROMPT_MARKER",
        first_url,
        second_url,
        "private-signature-one",
        "private-signature-two",
        encoded,
        "data:image/png;base64,",
    ):
        assert private not in exposed


@pytest.mark.parametrize("status", [502, 503])
def test_sdk_internal_server_error_retains_actual_upstream_status(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    caplog: LogCaptureFixture,
    status: int,
) -> None:
    mock_sdk_transport(
        monkeypatch,
        lambda request: httpx2.Response(
            status,
            headers={"x-request-id": f"req-provider-{status}"},
            json={
                "error": {
                    "code": "temporarily_unavailable",
                    "type": "server_error",
                    "message": "Try again later.",
                }
            },
        ),
    )
    with caplog.at_level(logging.WARNING, logger="api.tools.images.gpt"):
        result = gpt.image_create_with_gpt_image_2_5_flare("draw a cup")
    diagnostics = result.data["diagnostics"]
    assert result.error == "provider_failed"
    assert diagnostics["exception_type"] == "InternalServerError"
    assert diagnostics["status"] == status
    assert diagnostics["upstream_request_id"] == f"req-provider-{status}"
    record = next(
        record for record in caplog.records if record.name == "api.tools.images.gpt"
    )
    assert record.status == status
    assert record.exception_type == "InternalServerError"


@pytest.mark.parametrize("content_type", ["text/plain", "text/html"])
def test_non_json_upstream_failure_never_exposes_body(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    caplog: LogCaptureFixture,
    content_type: str,
) -> None:
    private_body = (
        f"<html>RAW_PRIVATE_BODY key={KEY} prompt=private_prompt_value "
        "https://private.example/image.png?sig=RAW_SIGNED_VALUE</html>"
    )
    mock_sdk_transport(
        monkeypatch,
        lambda request: httpx2.Response(
            502,
            text=private_body,
            headers={"Content-Type": content_type, "x-request-id": "req-html-upstream"},
        ),
    )
    with caplog.at_level(logging.WARNING, logger="api.tools.images.gpt"):
        result = gpt.image_create_with_gpt_image_2_5_flare("draw a cup")
    diagnostics = result.data["diagnostics"]
    assert diagnostics["status"] == 502
    assert diagnostics["error_code"] is None
    assert diagnostics["error_type"] is None
    assert diagnostics["error_param"] is None
    assert "without a structured error message" in diagnostics["error_message"]
    record = next(
        record for record in caplog.records if record.name == "api.tools.images.gpt"
    )
    rendered = ConsoleFormatter("%(levelname)s %(message)s").format(record)
    exposed = (
        rendered + result.model_dump_json() + json.dumps(record.__dict__, default=str)
    )
    for private in (
        KEY,
        "RAW_PRIVATE_BODY",
        "private_prompt_value",
        "RAW_SIGNED_VALUE",
        private_body,
    ):
        assert private not in exposed
    assert "req-html-upstream" in rendered


@pytest.mark.parametrize("field", ["code", "type", "param", "request_id"])
@pytest.mark.parametrize("unsafe", [f"prefix-{KEY}-suffix", "unsafe\nCONTROL_VALUE"])
def test_unsafe_error_identifiers_are_omitted_from_diagnostics_and_console(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    caplog: LogCaptureFixture,
    field: str,
    unsafe: str,
) -> None:
    detail = {
        "code": "backend_error",
        "type": "server_error",
        "param": "image",
        "message": "Provider temporarily unavailable.",
    }
    headers = {"x-request-id": "req-safe-upstream"}
    if field == "request_id":
        headers["x-request-id"] = unsafe
    else:
        detail[field] = unsafe
    mock_sdk_transport(
        monkeypatch,
        lambda request: httpx2.Response(500, headers=headers, json={"error": detail}),
    )
    with caplog.at_level(logging.WARNING, logger="api.tools.images.gpt"):
        result = gpt.image_create_with_gpt_image_2_5_flare("draw a cup")
    name = "upstream_request_id" if field == "request_id" else "error_" + field
    diagnostics = result.data["diagnostics"]
    record = next(
        record for record in caplog.records if record.name == "api.tools.images.gpt"
    )
    assert diagnostics.get(name) is None
    assert getattr(record, name, None) is None
    assert diagnostics["exception_type"] == "InternalServerError"
    rendered = ConsoleFormatter("%(levelname)s %(message)s").format(record)
    exposed = (
        rendered + result.model_dump_json() + json.dumps(record.__dict__, default=str)
    )
    assert KEY not in exposed
    assert unsafe not in exposed
    assert "CONTROL_VALUE" not in exposed


def test_real_request_context_preserves_local_and_upstream_request_ids(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    caplog: LogCaptureFixture,
) -> None:
    local_id = "local-gpt-diagnostics-request"
    upstream_id = "req-distinct-provider-request"
    mock_sdk_transport(
        monkeypatch,
        lambda request: httpx2.Response(
            500,
            headers={"x-request-id": upstream_id},
            json={
                "error": {
                    "code": "backend_error",
                    "type": "server_error",
                    "message": f"Provider failed api_key={KEY}; private prompt",
                }
            },
        ),
    )
    app = FastAPI()
    app.add_middleware(
        RequestContextMiddleware, config=RequestContextConfig(log_requests=False)
    )

    @app.post("/gpt-diagnostics")
    def generate() -> ImageToolResponse:
        return gpt.image_create_with_gpt_image_2_5_flare("private prompt")

    request_filter = RequestContextFilter()
    gpt.logger.addFilter(request_filter)
    try:
        with caplog.at_level(logging.WARNING, logger="api.tools.images.gpt"):
            with TestClient(app) as client:
                response = client.post(
                    "/gpt-diagnostics", headers={"Request-ID": local_id}
                )
    finally:
        gpt.logger.removeFilter(request_filter)

    assert response.status_code == 200
    assert response.headers["Request-ID"] == local_id
    diagnostics = response.json()["data"]["diagnostics"]
    assert diagnostics["local_request_id"] == local_id
    assert diagnostics["upstream_request_id"] == upstream_id
    record = next(
        record for record in caplog.records if record.name == "api.tools.images.gpt"
    )
    assert record.request_id == local_id
    assert record.local_request_id == local_id
    assert record.upstream_request_id == upstream_id
    rendered = ConsoleFormatter(
        "%(levelname)s request_id=%(request_id)s %(message)s"
    ).format(record)
    assert f"request_id={local_id}" in rendered
    assert f'"upstream_request_id":"{upstream_id}"' in rendered
    assert KEY not in rendered
    assert "private prompt" not in rendered
    assert KEY not in response.text
    assert "private prompt" not in response.text


@pytest.mark.parametrize("escaped_slashes", [False, True])
def test_nested_json_escaped_private_values_are_redacted_before_truncation(
    monkeypatch: MonkeyPatch,
    provider_config: None,
    caplog: LogCaptureFixture,
    escaped_slashes: bool,
) -> None:
    prompt = 'PRIVATE_ESCAPED_PROMPT\n"quoted" 中文'
    signed_url = "https://references.example/private-image.png?sig=HIDDEN_SIG_2026"
    # Error messages can contain a nested JSON fragment, including the valid
    # JSON spelling \/ for slash, even when the outer response is already parsed.
    image_data = "data:image/png;base64," + base64.b64encode(b"\xff" * 96).decode()
    private_json = json.dumps(
        {"input": prompt, "source": signed_url, "image": image_data, "credential": KEY},
        ensure_ascii=True,
    )
    if escaped_slashes:
        private_json = private_json.replace("/", "\\/")
    message = "Provider failed; details=" + private_json + "; " + "Try later. " * 80

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET":
            assert "authorization" not in request.headers
            return httpx2.Response(200, content=png())
        return httpx2.Response(
            500,
            headers={"x-request-id": "req-escaped-error"},
            json={"error": {"message": message, "type": "server_error"}},
        )

    mock_sdk_transport(monkeypatch, handler)
    with caplog.at_level(logging.WARNING, logger="api.tools.images.gpt"):
        result = gpt.image_create_with_gpt_image_2_5_flare(
            prompt, image_urls=[signed_url]
        )
    record = next(
        record for record in caplog.records if record.name == "api.tools.images.gpt"
    )
    diagnostics = result.data["diagnostics"]
    assert len(diagnostics["error_message"]) <= 512
    assert diagnostics["error_message"].startswith("Provider failed;")
    rendered = ConsoleFormatter("%(levelname)s %(message)s").format(record)
    exposed = (
        rendered + result.model_dump_json() + json.dumps(record.__dict__, default=str)
    )
    for private in (
        KEY,
        "PRIVATE_ESCAPED_PROMPT",
        "HIDDEN_SIG_2026",
        signed_url,
        image_data,
        private_json,
    ):
        assert private not in exposed
    assert "data:image" not in diagnostics["error_message"]
