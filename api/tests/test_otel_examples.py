"""Exercise manual tracing with isolated providers and no external services."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import propagate, trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.propagators.composite import CompositePropagator
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pytest import MonkeyPatch

from api.routes.examples import example_router, otel


def new_app() -> FastAPI:
    app = FastAPI(
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        }
    )
    app.include_router(example_router, prefix="/api/examples")
    return app


@pytest.fixture
def telemetry(
    monkeypatch: MonkeyPatch,
) -> Iterator[tuple[TracerProvider, InMemorySpanExporter]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(otel, "tracer", provider.get_tracer(otel.__name__))
    monkeypatch.setattr(otel.settings.app, "env", "local")
    original_propagator = propagate.get_global_textmap()
    propagate.set_global_textmap(
        CompositePropagator([TraceContextTextMapPropagator(), W3CBaggagePropagator()])
    )
    try:
        yield provider, exporter
    finally:
        propagate.set_global_textmap(original_propagator)
        provider.shutdown()


@pytest.fixture
def client(
    telemetry: tuple[TracerProvider, InMemorySpanExporter],
) -> Iterator[TestClient]:
    provider, _ = telemetry
    app = new_app()
    FastAPIInstrumentor.instrument_app(
        app, tracer_provider=provider, exclude_spans=["send", "receive"]
    )
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        FastAPIInstrumentor.uninstrument_app(app)


def test_manual_spans_inherit_the_incoming_request_trace(
    client: TestClient,
    telemetry: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    _, exporter = telemetry
    trace_id = "12345678901234567890123456789012"
    parent_id = "1234567890123456"

    response = client.get(
        "/api/examples/otel/trace",
        headers={"traceparent": f"00-{trace_id}-{parent_id}-01"},
    )

    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    server = next(span for span in spans if span.kind is SpanKind.SERVER)
    business = next(span for span in spans if span.name == "examples.otel.trace")
    work = next(span for span in spans if span.name == "examples.otel.work")
    assert server.parent.span_id == int(parent_id, 16)
    assert business.parent.span_id == server.context.span_id
    assert work.parent.span_id == business.context.span_id
    assert all(span.context.trace_id == int(trace_id, 16) for span in spans)
    assert business.attributes["example.fail"] is False
    assert business.attributes["example.result"] == "ok"
    assert "work.completed" in [event.name for event in work.events]
    assert response.json() == {
        "status": "ok",
        "trace": {
            "trace_id": trace_id,
            "span_id": f"{business.context.span_id:016x}",
            "sampled": True,
            "recording": True,
        },
    }


def test_handled_failure_records_errors_on_both_manual_spans(
    client: TestClient,
    telemetry: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    _, exporter = telemetry

    response = client.get("/api/examples/otel/trace", params={"fail": "true"})

    assert response.status_code == 503
    assert response.json()["status"] == "error"
    spans = {span.name: span for span in exporter.get_finished_spans()}
    business = spans["examples.otel.trace"]
    assert business.attributes["example.fail"] is True
    assert business.attributes["example.result"] == "error"
    assert response.json()["trace"]["span_id"] == f"{business.context.span_id:016x}"
    for name in ("examples.otel.trace", "examples.otel.work"):
        span = spans[name]
        assert span.status.status_code is StatusCode.ERROR
        exceptions = [event for event in span.events if event.name == "exception"]
        assert len(exceptions) == 1
        assert exceptions[0].attributes["exception.type"] == "RuntimeError"
        assert exceptions[0].attributes["exception.message"] == (
            "Simulated example failure"
        )
    assert "work.completed" not in [
        event.name for event in spans["examples.otel.work"].events
    ]


def test_propagation_uses_current_span_and_omits_baggage(
    client: TestClient,
    telemetry: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    _, exporter = telemetry
    trace_id = "12345678901234567890123456789012"

    response = client.get(
        "/api/examples/otel/propagation",
        headers={
            "traceparent": f"00-{trace_id}-1234567890123456-01",
            "tracestate": "example=upstream",
            "baggage": "private=do-not-echo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    business = next(
        span
        for span in exporter.get_finished_spans()
        if span.name == "examples.otel.propagation"
    )
    span_id = f"{business.context.span_id:016x}"
    assert payload["trace"]["trace_id"] == trace_id
    assert payload["trace"]["span_id"] == span_id
    assert payload["headers"] == {
        "traceparent": f"00-{trace_id}-{span_id}-01",
        "tracestate": "example=upstream",
    }
    assert "do-not-echo" not in response.text


def test_disabled_tracing_still_runs_the_example(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(otel.settings.app, "env", "local")
    monkeypatch.setattr(
        otel, "tracer", trace.NoOpTracerProvider().get_tracer(otel.__name__)
    )

    with TestClient(new_app()) as client:
        response = client.get("/api/examples/otel/trace")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "trace": {
            "trace_id": None,
            "span_id": None,
            "sampled": False,
            "recording": False,
        },
    }


def test_unsampled_trace_has_valid_context_without_exporting(
    monkeypatch: MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=ALWAYS_OFF)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(otel.settings.app, "env", "local")
    monkeypatch.setattr(otel, "tracer", provider.get_tracer(otel.__name__))
    try:
        with TestClient(new_app()) as client:
            response = client.get("/api/examples/otel/trace")

        assert response.status_code == 200
        context = response.json()["trace"]
        assert len(context["trace_id"]) == 32
        assert int(context["trace_id"], 16) > 0
        assert len(context["span_id"]) == 16
        assert int(context["span_id"], 16) > 0
        assert context["sampled"] is False
        assert context["recording"] is False
        assert exporter.get_finished_spans() == ()
    finally:
        provider.shutdown()


@pytest.mark.parametrize("path", ["/otel/trace", "/otel/propagation"])
def test_examples_are_unavailable_in_production(
    monkeypatch: MonkeyPatch,
    client: TestClient,
    telemetry: tuple[TracerProvider, InMemorySpanExporter],
    path: str,
) -> None:
    _, exporter = telemetry
    monkeypatch.setattr(otel.settings.app, "env", "prod")

    assert client.get(f"/api/examples{path}").status_code == 404
    assert not any(
        span.name.startswith("examples.otel.") for span in exporter.get_finished_spans()
    )
