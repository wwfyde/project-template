import asyncio
import logging
from collections.abc import Iterator
from weakref import WeakValueDictionary

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError
from pytest import CaptureFixture, MonkeyPatch
from starlette.types import Message, Receive, Scope, Send

from api.core import request_context
from api.core.log import setup_logging
from api.core.request_context import (
    RequestContextConfig,
    RequestContextMiddleware,
    bind_identity,
    correlation_attributes,
    get_request_context,
    outbound_context_headers,
)

TRACE_ID = "12345678901234567890123456789012"
PARENT_ID = "1234567890123456"
TRACEPARENT = f"00-{TRACE_ID}-{PARENT_ID}-01"


def new_app(config: RequestContextConfig | None = None) -> FastAPI:
    app = FastAPI(
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        }
    )
    app.add_middleware(RequestContextMiddleware, config=config)

    @app.get("/anonymous")
    async def anonymous(request: Request, response: Response) -> dict[str, object]:
        # Simulate stale metadata from a cached response; middleware must replace it.
        response.headers["Request-ID"] = "stale-request"
        response.headers["User-ID"] = "another-user"
        response.headers["Tenant-ID"] = "another-tenant"
        response.headers["traceparent"] = TRACEPARENT
        return {
            "request_id": request.state.request_id,
            "outbound": outbound_context_headers(),
        }

    @app.get("/authenticated")
    async def authenticated() -> dict[str, object]:
        bind_identity("user-42", "tenant-7")
        logging.getLogger("api.auth").info(
            "Identity resolved", extra={"user_id": "spoofed-extra"}
        )
        return {"outbound": outbound_context_headers()}

    @app.get("/failure")
    async def failure() -> None:
        raise RuntimeError("do not log oauth-code-or-token")

    return app


def test_anonymous_headers_are_generated_and_identity_input_is_ignored() -> None:
    with TestClient(new_app()) as client:
        response = client.get(
            "/anonymous",
            headers={
                "User-ID": "attacker",
                "Tenant-ID": "other-tenant",
            },
        )
    request_id = response.headers["Request-ID"]
    assert len(request_id) == 32
    assert response.json() == {
        "request_id": request_id,
        "outbound": {"Request-ID": request_id},
    }
    assert "User-ID" not in response.headers
    assert "Tenant-ID" not in response.headers
    assert "traceparent" not in response.headers
    assert get_request_context() is None
    assert outbound_context_headers() == {}


@pytest.mark.parametrize("supplied", ["", "a" * 129, "invalid request", "bad\r\nvalue"])
def test_invalid_request_id_is_replaced(supplied: str) -> None:
    with TestClient(new_app()) as client:
        response = client.get("/anonymous", headers={"Request-ID": supplied})
    assert response.headers["Request-ID"] != supplied
    assert len(response.headers["Request-ID"]) == 32


def test_duplicate_request_id_and_traceparent_are_rejected() -> None:
    with TestClient(new_app()) as client:
        response = client.get(
            "/anonymous",
            headers=[
                ("Request-ID", "first"),
                ("Request-ID", "second"),
                ("traceparent", TRACEPARENT),
                ("traceparent", TRACEPARENT),
            ],
        )
    assert response.headers["Request-ID"] not in {"first", "second"}
    assert "traceparent" not in response.headers


def test_authenticated_ids_replace_spoofed_headers_and_are_not_publicly_cacheable() -> (
    None
):
    with TestClient(new_app()) as client:
        response = client.get(
            "/authenticated",
            headers={
                "Request-ID": "client.request:1",
                "User-ID": "attacker",
                "Tenant-ID": "attacker",
            },
        )
    assert response.headers["Request-ID"] == "client.request:1"
    assert response.headers["User-ID"] == "user-42"
    assert response.headers["Tenant-ID"] == "tenant-7"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json()["outbound"] == {
        "Request-ID": "client.request:1",
        "User-ID": "user-42",
        "Tenant-ID": "tenant-7",
    }


def test_headers_and_incoming_id_policy_are_configurable() -> None:
    config = RequestContextConfig(
        request_id_header="X-Request-ID",
        user_id_header="X-User-ID",
        tenant_id_header="X-Tenant-ID",
        accept_request_id=False,
        expose_identity_headers=False,
    )
    with TestClient(new_app(config)) as client:
        response = client.get("/authenticated", headers={"X-Request-ID": "ignored"})
    assert response.headers["X-Request-ID"] != "ignored"
    assert "X-User-ID" not in response.headers
    assert "X-Tenant-ID" not in response.headers
    assert response.json()["outbound"]["X-User-ID"] == "user-42"
    assert "Request-ID" not in response.headers


@pytest.mark.parametrize(
    "config",
    [
        {"request_id_header": "Invalid Header"},
        {"user_id_header": "Set-Cookie"},
        {"tenant_id_header": "traceparent"},
        {"user_id_header": "request-id"},
    ],
)
def test_header_configuration_rejects_collisions_and_unsafe_names(
    config: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        RequestContextConfig(**config)


@pytest.mark.parametrize(
    "incoming", [TRACEPARENT, "00-" + "0" * 32 + f"-{PARENT_ID}-01", "garbage"]
)
def test_trace_context_can_be_forwarded_without_creating_a_local_span(
    incoming: str,
) -> None:
    app = new_app()

    @app.get("/trace-status")
    async def trace_status() -> dict[str, object]:
        return {
            "local_span_valid": trace.get_current_span().get_span_context().is_valid,
            "attributes": correlation_attributes(),
            "outbound": outbound_context_headers(),
        }

    with TestClient(app) as client:
        response = client.get(
            "/trace-status",
            headers={
                "traceparent": incoming,
                "baggage": "secret=never-forward",
            },
        )
    assert response.json()["local_span_valid"] is False
    assert "baggage" not in response.json()["outbound"]
    if incoming == TRACEPARENT:
        assert response.headers["traceparent"] == TRACEPARENT
        assert response.json()["attributes"]["incoming_trace_id"] == TRACE_ID
    else:
        assert "traceparent" not in response.headers
        assert "incoming_trace_id" not in response.json()["attributes"]


def test_existing_server_span_is_enriched_and_propagated_without_duplicate_spans() -> (
    None
):
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = new_app()
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, exclude_spans=["send", "receive"]
    )
    try:
        with TestClient(app) as client:
            response = client.get(
                "/authenticated",
                headers={"Request-ID": "request-1", "traceparent": TRACEPARENT},
            )
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        server = spans[0]
        assert server.context.trace_id == int(TRACE_ID, 16)
        assert server.parent.span_id == int(PARENT_ID, 16)
        assert server.attributes["request.id"] == "request-1"
        assert server.attributes["user.id"] == "user-42"
        assert server.attributes["tenant.id"] == "tenant-7"
        propagated = f"00-{TRACE_ID}-{server.context.span_id:016x}-01"
        assert response.headers["traceparent"] == propagated
        assert response.json()["outbound"]["traceparent"] == propagated
    finally:
        FastAPIInstrumentor.uninstrument_app(app)
        provider.shutdown()


@pytest.mark.asyncio
async def test_concurrent_requests_keep_separate_identity_and_reset_afterwards() -> (
    None
):
    entered = 0
    both_entered = asyncio.Event()
    observations: dict[str, dict[str, str]] = {}

    async def endpoint(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal entered
        identity = scope["path"].strip("/")
        bind_identity(identity, f"tenant-{identity}")
        entered += 1
        if entered == 2:
            both_entered.set()
        await both_entered.wait()
        observations[identity] = outbound_context_headers()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    app = RequestContextMiddleware(endpoint)

    async def request(identity: str) -> None:
        async def receive() -> Message:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: Message) -> None:
            pass

        await app(
            {
                "type": "http",
                "path": f"/{identity}",
                "method": "GET",
                "headers": [(b"request-id", identity.encode())],
            },
            receive,
            send,
        )
        assert get_request_context() is None

    await asyncio.wait_for(asyncio.gather(request("alice"), request("bob")), timeout=3)
    assert observations == {
        identity: {
            "Request-ID": identity,
            "User-ID": identity,
            "Tenant-ID": f"tenant-{identity}",
        }
        for identity in ("alice", "bob")
    }


@pytest.fixture
def isolated_logging(monkeypatch: MonkeyPatch) -> Iterator[None]:
    root = logging.RootLogger(logging.WARNING)
    monkeypatch.setattr(logging, "root", root)
    monkeypatch.setattr(logging.Logger, "root", root)
    monkeypatch.setattr(logging.Logger, "manager", logging.Manager(root))
    monkeypatch.setattr(logging, "_handlers", WeakValueDictionary())
    monkeypatch.setattr(logging, "_handlerList", [])
    monkeypatch.setattr(
        request_context, "logger", logging.getLogger(request_context.__name__)
    )
    yield
    logging.shutdown(logging._handlerList)


def test_application_and_completion_logs_include_trusted_context_in_console_and_otlp(
    isolated_logging: None,
    capsys: CaptureFixture[str],
) -> None:
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider(shutdown_on_exit=False)
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    setup_logging(logger_provider=provider)
    try:
        with TestClient(new_app()) as client:
            response = client.get(
                "/authenticated?code=secret",
                headers={
                    "Request-ID": "request-logs",
                    "User-ID": "attacker",
                    "traceparent": TRACEPARENT,
                },
            )
        assert response.status_code == 200
        records = [item.log_record for item in exporter.get_finished_logs()]
        business = next(item for item in records if item.body == "Identity resolved")
        completed = next(
            item for item in records if item.body == "HTTP request completed"
        )
        for record in (business, completed):
            assert record.attributes["request_id"] == "request-logs"
            assert record.attributes["user_id"] == "user-42"
            assert record.attributes["tenant_id"] == "tenant-7"
            assert record.attributes["incoming_trace_id"] == TRACE_ID
            assert record.trace_id == 0  # We did not fabricate a local span.
        assert completed.attributes["http.route"] == "/authenticated"
        assert completed.attributes["http.response.status_code"] == 200
        assert completed.attributes["http.request.duration_ms"] >= 0
        output = capsys.readouterr().err
        assert '"request_id":"request-logs"' in output
        assert f"trace_id={TRACE_ID}" in output
        assert "secret" not in output
        assert "spoofed-extra" not in output
        assert "attacker" not in output
    finally:
        provider.shutdown()


def test_unhandled_failure_has_request_id_and_does_not_log_exception_secrets(
    isolated_logging: None,
    capsys: CaptureFixture[str],
) -> None:
    setup_logging()
    with TestClient(new_app(), raise_server_exceptions=False) as client:
        response = client.get(
            "/failure?token=secret", headers={"Request-ID": "failed-request"}
        )
    assert response.status_code == 500
    assert response.headers["Request-ID"] == "failed-request"
    assert response.json() == {"detail": "Internal Server Error"}
    output = capsys.readouterr().err
    assert '"request_id":"failed-request"' in output
    assert '"error.type":"RuntimeError"' in output
    assert "oauth-code-or-token" not in output
    assert "token=secret" not in output
    assert get_request_context() is None
