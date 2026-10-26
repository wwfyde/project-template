"""Image HTTP validation failures are observable without exposing request input."""

import base64
import inspect
import json
import logging
from unittest.mock import Mock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator
from pytest import LogCaptureFixture, MonkeyPatch

from api.core.log import ConsoleFormatter
from api.core.request_context import RequestContextMiddleware
from api.routes import images as image_routes
from api.routes.ai_tools import ai_tools_router
from api.tools.images import gpt
from api.tools.types import ImageToolResponse

PATH = "/api/ai-tools/images/gpt/gpt-image-2"
EVENT = "http.request.validation_failed"
PROMPT = "生成一碗牛肉面"
PRIVATE_PROMPT = "PRIVATE_PROMPT_DO_NOT_LOG"
IMAGE_BASE64 = base64.b64encode(b"PRIVATE_IMAGE_BYTES_DO_NOT_LOG").decode()
IMAGE_DATA = "data:image/png;base64," + IMAGE_BASE64
API_KEY = "private-header-api-key-do-not-log"
AUTH_TOKEN = "private-authorization-token-do-not-log"


@pytest.fixture
def validation_app(monkeypatch: MonkeyPatch) -> tuple[FastAPI, Mock, dict[str, object]]:
    defaults = {
        name: parameter.default
        for name, parameter in inspect.signature(
            gpt.image_create_with_gpt_image_2
        ).parameters.items()
        if parameter.default is not inspect.Parameter.empty
    }
    tool = Mock(
        return_value=ImageToolResponse(image_model="gpt-image-2", content="", images=[])
    )
    monkeypatch.setattr(gpt, "image_create_with_gpt_image_2", tool)
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(ai_tools_router, prefix="/api")
    return app, tool, defaults


def assert_validation_event(
    caplog: LogCaptureFixture,
    *,
    request_id: str,
    location: str,
    error_type: str,
) -> dict[str, object]:
    records = [
        record
        for record in caplog.records
        if record.__dict__.get("otel.event.name") == EVENT
    ]
    assert len(records) == 1, (
        "ImageRoute must emit one structured validation failure event"
    )
    record = records[0]
    attributes = record.__dict__
    assert record.levelno == logging.ERROR
    assert attributes["request_id"] == request_id
    assert attributes["http.response.status_code"] == 422
    assert attributes["validation.error_count"] == 1
    assert attributes["validation.error_locations"] == [location]
    assert attributes["validation.error_types"] == [error_type]
    assert isinstance(attributes["validation.errors"], str)
    errors = json.loads(attributes["validation.errors"])
    assert len(errors) == 1
    assert set(errors[0]) <= {"loc", "type", "msg", "json"}
    assert errors[0]["type"] == error_type
    assert isinstance(errors[0]["loc"], list)
    assert isinstance(errors[0]["msg"], str) and errors[0]["msg"]
    # A regular console line must explain the field, error category and reason.
    message = record.getMessage()
    assert location in message
    assert error_type in message
    assert errors[0]["msg"] in message
    rendered = ConsoleFormatter("%(levelname)s %(message)s").format(record)
    exposed = rendered + json.dumps(attributes, default=str)
    for private in (
        PROMPT,
        PRIVATE_PROMPT,
        IMAGE_DATA,
        IMAGE_BASE64,
        "PRIVATE_IMAGE_BYTES_DO_NOT_LOG",
        API_KEY,
        AUTH_TOKEN,
        "INVALID_PRIVATE_QUALITY",
    ):
        assert private not in exposed
    for error in errors:
        assert "input" not in error and "ctx" not in error
    return errors[0]


def test_trailing_json_comma_logs_safe_error_with_position_and_request_id(
    validation_app: tuple[FastAPI, Mock, dict[str, object]],
    caplog: LogCaptureFixture,
) -> None:
    app, tool, _ = validation_app
    content = '{"prompt":"生成一碗牛肉面",\n}'
    try:
        json.loads(content)
    except json.JSONDecodeError as error:
        position, line, column = error.pos, error.lineno, error.colno
    else:
        raise AssertionError("The regression request must contain invalid JSON")
    request_id = "validation-trailing-comma"
    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            response = client.post(
                PATH,
                content=content,
                headers={
                    "Content-Type": "application/json",
                    "Request-ID": request_id,
                    "X-Api-Key": API_KEY,
                    "Authorization": f"Bearer {AUTH_TOKEN}",
                },
            )
    assert response.status_code == 422
    assert response.headers["Request-ID"] == request_id
    assert response.json()["detail"][0]["type"] == "json_invalid"
    assert PROMPT not in response.text
    tool.assert_not_called()
    error = assert_validation_event(
        caplog,
        request_id=request_id,
        location=f"body@{position}",
        error_type="json_invalid",
    )
    assert error["loc"] == ["body", position]
    if "json" in error:
        assert error["json"] == {"line": line, "column": column, "position": position}


@pytest.mark.parametrize(
    "payload,provider,location,error_type",
    [
        (
            {
                "prompt": PRIVATE_PROMPT,
                "image_urls": [IMAGE_DATA],
                "quality": "INVALID_PRIVATE_QUALITY",
            },
            None,
            "body.quality",
            "literal_error",
        ),
        ({"image_urls": [IMAGE_DATA]}, None, "body.prompt", "missing"),
        (
            {"prompt": PRIVATE_PROMPT, "image_urls": [IMAGE_DATA]},
            "unknown",
            "query.provider",
            "literal_error",
        ),
    ],
)
def test_schema_and_query_errors_log_fields_without_input_values(
    validation_app: tuple[FastAPI, Mock, dict[str, object]],
    caplog: LogCaptureFixture,
    payload: dict,
    provider: str | None,
    location: str,
    error_type: str,
) -> None:
    app, tool, _ = validation_app
    request_id = "validation-" + location
    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            response = client.post(
                PATH,
                params={"provider": provider} if provider else {},
                json=payload,
                headers={
                    "Request-ID": request_id,
                    "X-Api-Key": API_KEY,
                    "Authorization": f"Bearer {AUTH_TOKEN}",
                },
            )
    assert response.status_code == 422
    assert response.headers["Request-ID"] == request_id
    tool.assert_not_called()
    error = assert_validation_event(
        caplog, request_id=request_id, location=location, error_type=error_type
    )
    assert error["loc"] == location.split(".")
    assert "PRIVATE" not in response.text
    assert IMAGE_BASE64 not in response.text
    assert API_KEY not in response.text
    assert AUTH_TOKEN not in response.text


def test_valid_prompt_only_calls_tool_with_declared_defaults_without_validation_error(
    validation_app: tuple[FastAPI, Mock, dict[str, object]],
    caplog: LogCaptureFixture,
) -> None:
    app, tool, defaults = validation_app
    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            response = client.post(
                PATH,
                json={"prompt": PROMPT},
                headers={"Request-ID": "validation-valid-control"},
            )
    assert response.status_code == 200
    assert response.json()["success"] is True
    tool.assert_called_once_with(prompt=PROMPT, **defaults)
    assert not any(
        record.__dict__.get("otel.event.name") == EVENT for record in caplog.records
    )


def test_extra_field_name_is_redacted_only_from_logs(
    validation_app: tuple[FastAPI, Mock, dict[str, object]],
    caplog: LogCaptureFixture,
) -> None:
    app, tool, _ = validation_app
    private_key = "PRIVATE_EXTRA_FIELD_CONTAINING_CUSTOMER_TEXT"
    with caplog.at_level(logging.ERROR, logger="api.routes.images"):
        with TestClient(app) as client:
            response = client.post(
                PATH,
                json={"prompt": PRIVATE_PROMPT, private_key: IMAGE_DATA},
                headers={"Request-ID": "validation-private-extra-key"},
            )
    assert response.status_code == 422
    tool.assert_not_called()
    # Keep the existing caller-facing loc contract; only persistent diagnostics
    # must omit the private field name supplied by the caller.
    assert response.json()["detail"][0]["loc"] == ["body", private_key]
    error = assert_validation_event(
        caplog,
        request_id="validation-private-extra-key",
        location="body.<extra_field>",
        error_type="extra_forbidden",
    )
    assert error["loc"] == ["body", "<extra_field>"]
    record = next(
        record
        for record in caplog.records
        if record.__dict__.get("otel.event.name") == EVENT
    )
    exposed = ConsoleFormatter("%(levelname)s %(message)s").format(record)
    exposed += json.dumps(record.__dict__, default=str)
    assert private_key not in exposed


def test_custom_validator_private_message_is_replaced_in_error_logs(
    caplog: LogCaptureFixture,
) -> None:
    private_value = "PRIVATE_VALIDATOR_INPUT_VALUE"
    private_message = (
        f"Custom failure input={private_value}; image={IMAGE_DATA}; api_key={API_KEY}"
    )

    class PrivateValidationRequest(BaseModel):
        value: str

        @field_validator("value")
        @classmethod
        def validate_value(cls, value: str) -> str:
            raise ValueError(private_message + "; received=" + value)

    router = APIRouter(route_class=image_routes.ImageRoute)
    called = False

    @router.post("/private-validation")
    def validate(payload: PrivateValidationRequest) -> dict[str, bool]:
        nonlocal called
        called = True
        return {"ok": True}

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router)
    with caplog.at_level(logging.ERROR, logger="api.routes.images"):
        with TestClient(app) as client:
            response = client.post(
                "/private-validation",
                json={"value": private_value},
                headers={
                    "Request-ID": "validation-custom-message",
                    "X-Api-Key": API_KEY,
                },
            )
    assert response.status_code == 422
    assert called is False
    error = assert_validation_event(
        caplog,
        request_id="validation-custom-message",
        location="body.value",
        error_type="value_error",
    )
    assert error["msg"] == "Value failed validation"
    assert set(error) == {"type", "loc", "msg"}
    record = next(
        record
        for record in caplog.records
        if record.__dict__.get("otel.event.name") == EVENT
    )
    exposed = ConsoleFormatter("%(levelname)s %(message)s").format(record)
    exposed += json.dumps(record.__dict__, default=str)
    assert private_value not in exposed
    assert private_message not in exposed
    assert "received=" not in exposed


@pytest.mark.parametrize("error_count", [3, 25])
def test_multiple_errors_emit_one_bounded_event_with_total_count(
    validation_app: tuple[FastAPI, Mock, dict[str, object]],
    caplog: LogCaptureFixture,
    error_count: int,
) -> None:
    app, tool, _ = validation_app
    extra_fields = {
        f"PRIVATE_EXTRA_KEY_{index}": IMAGE_DATA for index in range(error_count)
    }
    with caplog.at_level(logging.ERROR, logger="api.routes.images"):
        with TestClient(app) as client:
            response = client.post(
                PATH,
                json={"prompt": PRIVATE_PROMPT, **extra_fields},
                headers={"Request-ID": "validation-many-errors"},
            )
    assert response.status_code == 422
    assert len(response.json()["detail"]) == error_count
    tool.assert_not_called()
    records = [
        record
        for record in caplog.records
        if record.__dict__.get("otel.event.name") == EVENT
    ]
    assert len(records) == 1
    record = records[0]
    attributes = record.__dict__
    assert record.levelno == logging.ERROR
    assert attributes["request_id"] == "validation-many-errors"
    assert attributes["validation.error_count"] == error_count
    assert attributes["validation.errors_truncated"] is (error_count > 20)
    details = json.loads(attributes["validation.errors"])
    assert len(details) == min(error_count, 20)
    assert len(attributes["validation.error_locations"]) == len(details)
    assert len(attributes["validation.error_types"]) == len(details)
    assert all(item["loc"] == ["body", "<extra_field>"] for item in details)
    assert all(set(item) == {"loc", "type", "msg"} for item in details)
    exposed = ConsoleFormatter("%(levelname)s %(message)s").format(record)
    exposed += json.dumps(attributes, default=str)
    assert PRIVATE_PROMPT not in exposed
    assert IMAGE_DATA not in exposed
    assert IMAGE_BASE64 not in exposed
    assert "PRIVATE_EXTRA_KEY_" not in exposed


def test_validation_event_exports_as_error_with_safe_otlp_attributes(
    validation_app: tuple[FastAPI, Mock, dict[str, object]],
    monkeypatch: MonkeyPatch,
) -> None:
    from opentelemetry._logs import SeverityNumber
    from opentelemetry.instrumentation.logging.handler import LoggingHandler
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import (
        InMemoryLogRecordExporter,
        SimpleLogRecordProcessor,
    )

    from api.core.log import ExportLogFilter, RequestContextFilter

    app, tool, _ = validation_app
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider(shutdown_on_exit=False)
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    handler = LoggingHandler(level=logging.ERROR, logger_provider=provider)
    handler.addFilter(RequestContextFilter())
    handler.addFilter(ExportLogFilter())
    logger = logging.Logger("api.routes.images.validation-export", level=logging.ERROR)
    logger.addHandler(handler)
    logger.propagate = False
    monkeypatch.setattr(image_routes, "logger", logger)
    try:
        with TestClient(app) as client:
            response = client.post(
                PATH,
                json={
                    "prompt": PRIVATE_PROMPT,
                    "image_urls": [IMAGE_DATA],
                    "quality": "INVALID_PRIVATE_QUALITY",
                },
                headers={
                    "Request-ID": "validation-otel-export",
                    "Authorization": f"Bearer {AUTH_TOKEN}",
                },
            )
        assert response.status_code == 422
        tool.assert_not_called()
        provider.force_flush()
        records = [item.log_record for item in exporter.get_finished_logs()]
        assert len(records) == 1
        record = records[0]
        assert record.severity_number == SeverityNumber.ERROR
        assert record.severity_text == "ERROR"
        attributes = record.attributes
        # The OTel handler promotes otel.event.name into the native event field;
        # ExportLogFilter also preserves a searchable event_name attribute.
        assert record.event_name == EVENT
        assert attributes["event_name"] == EVENT
        assert attributes["request_id"] == "validation-otel-export"
        assert attributes["http.response.status_code"] == 422
        assert attributes["validation.error_count"] == 1
        assert attributes["validation.errors_truncated"] is False
        assert tuple(attributes["validation.error_locations"]) == ("body.quality",)
        assert tuple(attributes["validation.error_types"]) == ("literal_error",)
        assert isinstance(attributes["validation.errors"], str)
        details = json.loads(attributes["validation.errors"])
        assert details[0]["loc"] == ["body", "quality"]
        assert set(details[0]) == {"loc", "type", "msg"}
        exposed = str(record.body) + json.dumps(dict(attributes), default=str)
        for private in (
            PRIVATE_PROMPT,
            IMAGE_DATA,
            IMAGE_BASE64,
            API_KEY,
            AUTH_TOKEN,
            "INVALID_PRIVATE_QUALITY",
        ):
            assert private not in exposed
    finally:
        logger.removeHandler(handler)
        handler.close()
        provider.shutdown()
