import logging
import os
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    InMemoryMetricReader,
)
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from pydantic import ValidationError
from pytest import MonkeyPatch

from api import otel
from api.core.config import Settings
from api.core.log import TraceContextFilter
from api.core.telemetry_config import OtelConfig


def new_app() -> FastAPI:
    return FastAPI(
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        }
    )


@pytest.fixture
def settings_directory(monkeypatch: MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.chdir(tmp_path)
    for name in list(os.environ):
        if name == "OTEL" or name.startswith("OTEL_"):
            monkeypatch.delenv(name)
    for name, value in {
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
        "POSTGRES_USERNAME": "api",
        "POSTGRES_PASSWORD": "test-only-password",
        "POSTGRES_DATABASE": "api",
    }.items():
        monkeypatch.setenv(name, value)
    return tmp_path


def test_telemetry_defaults_to_disabled(settings_directory: Path) -> None:
    assert Settings(_env_file=None).otel.active is False


@pytest.mark.parametrize("source", ["environment", "dotenv", "toml"])
def test_telemetry_configuration_sources(
    monkeypatch: MonkeyPatch, settings_directory: Path, source: str
) -> None:
    if source == "toml":
        (settings_directory / "config.toml").write_text(
            '[otel]\nenabled = true\nservice_name = "orders-api"\n'
            'exporter_otlp_endpoint = "http://collector:4318"\n'
            'exporter_otlp_headers = "Authorization=Bearer%20test-token"\n'
            'logs_enabled = false\nlogs_level = "DEBUG"\n'
            'exporter_otlp_logs_endpoint = "http://logs:4318/receive"\n'
            "traces_sampler_arg = 0.25\nmetric_export_interval = 1000\n",
            encoding="utf-8",
        )
    else:
        values = {
            "OTEL_ENABLED": "true",
            "OTEL_SERVICE_NAME": "orders-api",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
            "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=Bearer%20test-token",
            "OTEL_LOGS_ENABLED": "false",
            "OTEL_LOGS_LEVEL": "DEBUG",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs:4318/receive",
            "OTEL_TRACES_SAMPLER_ARG": "0.25",
            "OTEL_METRIC_EXPORT_INTERVAL": "1000",
        }
        if source == "environment":
            for name, value in values.items():
                monkeypatch.setenv(name, value)
        else:
            (settings_directory / ".env").write_text(
                "\n".join(f"{name}={value}" for name, value in values.items()),
                encoding="utf-8",
            )

    config = Settings().otel

    assert config.active is True
    assert config.service_name == "orders-api"
    assert config.exporter_otlp_endpoint == "http://collector:4318"
    assert config.exporter_otlp_headers.get_secret_value() == (
        "Authorization=Bearer%20test-token"
    )
    assert config.traces_sampler_arg == 0.25
    assert config.metric_export_interval == 1000
    assert config.logs_enabled is False
    assert config.logs_level == "DEBUG"
    assert config.endpoint("logs") == "http://logs:4318/receive"
    assert "test-token" not in config.model_dump_json()
    assert "test-token" not in repr(config)


def test_settings_precedence(
    monkeypatch: MonkeyPatch, settings_directory: Path
) -> None:
    (settings_directory / "config.toml").write_text(
        '[otel]\nenabled = true\nservice_name = "from-toml"\n'
        'exporter_otlp_endpoint = "http://collector:4318"\n',
        encoding="utf-8",
    )
    (settings_directory / ".env").write_text(
        "OTEL_SERVICE_NAME=from-dotenv\n", encoding="utf-8"
    )
    assert Settings().otel.service_name == "from-dotenv"

    monkeypatch.setenv("OTEL_SERVICE_NAME", "from-environment")
    assert Settings().otel.service_name == "from-environment"

    configured = Settings(otel={"service_name": "from-init"}).otel
    assert configured.service_name == "from-init"
    assert configured.active is True
    assert configured.exporter_otlp_endpoint == "http://collector:4318"


def test_sdk_disabled_overrides_enabled_configuration(
    monkeypatch: MonkeyPatch, settings_directory: Path
) -> None:
    (settings_directory / "config.toml").write_text(
        "[otel]\nenabled = true\n", encoding="utf-8"
    )
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    config = Settings().otel

    assert config.enabled is True
    assert config.sdk_disabled is True
    assert config.active is False


@pytest.mark.parametrize("ratio", [-0.01, 1.01, float("nan")])
def test_invalid_sampling_ratio_is_rejected(ratio: float) -> None:
    with pytest.raises(ValidationError):
        OtelConfig(traces_sampler_arg=ratio)


@pytest.mark.parametrize(
    "endpoint",
    [
        "collector:4318",
        "ftp://collector:4318",
        "http://user:password@collector:4318",
        "http://collector:4318?token=secret",
        "http://collector:4318#fragment",
    ],
)
@pytest.mark.parametrize(
    "field", ["exporter_otlp_endpoint", "exporter_otlp_logs_endpoint"]
)
def test_invalid_or_credential_bearing_endpoint_is_rejected(
    endpoint: str, field: str
) -> None:
    with pytest.raises(ValidationError):
        OtelConfig(**{field: endpoint})


def test_signal_endpoints_respect_explicit_overrides() -> None:
    config = OtelConfig(
        exporter_otlp_endpoint="https://collector.example/otlp/",
        exporter_otlp_traces_endpoint="https://traces.example/custom",
    )

    assert config.endpoint("traces") == "https://traces.example/custom"
    assert config.endpoint("metrics") == "https://collector.example/otlp/v1/metrics"
    assert config.endpoint("logs") == "https://collector.example/otlp/v1/logs"


@pytest.fixture
def memory_telemetry(
    monkeypatch: MonkeyPatch,
) -> Iterator[tuple[InMemorySpanExporter, InMemoryMetricReader, Mock]]:
    spans = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    runtime = otel.TelemetryRuntime(tracer_provider, meter_provider)
    create_runtime = Mock(return_value=runtime)
    monkeypatch.setattr(otel, "_runtime", None)
    monkeypatch.setattr(otel, "_runtime_config", None)
    monkeypatch.setattr(otel, "_create_runtime", create_runtime)
    try:
        yield spans, reader, create_runtime
    finally:
        tracer_provider.shutdown()
        meter_provider.shutdown()


@pytest.mark.parametrize("sdk_disabled", [False, True])
def test_disabled_telemetry_does_not_initialize_or_instrument(
    monkeypatch: MonkeyPatch, sdk_disabled: bool
) -> None:
    create_runtime = Mock(side_effect=AssertionError("OTel must stay uninitialized"))
    instrument_fastapi = Mock()
    instrument_postgres = Mock()
    monkeypatch.setattr(otel, "_create_runtime", create_runtime)
    monkeypatch.setattr(otel.FastAPIInstrumentor, "instrument_app", instrument_fastapi)
    monkeypatch.setattr(otel, "PsycopgInstrumentor", instrument_postgres)
    app = new_app()

    otel.setup_telemetry(
        app,
        OtelConfig(enabled=sdk_disabled, sdk_disabled=sdk_disabled),
        environment="test",
    )

    create_runtime.assert_not_called()
    instrument_fastapi.assert_not_called()
    instrument_postgres.assert_not_called()
    assert getattr(app.state, "otel_runtime", None) is None


def test_fastapi_exports_request_metrics_and_propagates_traceparent(
    memory_telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader, Mock],
) -> None:
    spans, reader, create_runtime = memory_telemetry
    app = new_app()

    @app.get("/items/{item_id}")
    async def get_item(item_id: str) -> dict[str, str]:
        return {"id": item_id}

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    config = OtelConfig(enabled=True, postgres_enabled=False)
    otel.setup_telemetry(app, config, environment="test")
    otel.setup_telemetry(app, config, environment="test")
    trace_id = "12345678901234567890123456789012"
    parent_id = "1234567890123456"
    with TestClient(app) as client:
        response = client.get(
            "/items/42",
            headers={
                "traceparent": f"00-{trace_id}-{parent_id}-01",
                "Authorization": "Bearer test-private-header",
            },
        )
        assert response.status_code == 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/health?probe=ready").status_code == 200

    create_runtime.assert_called_once()
    request_spans = spans.get_finished_spans()
    assert len(request_spans) == 1
    request_span = request_spans[0]
    assert request_span.kind is SpanKind.SERVER
    assert request_span.name == "GET /items/{item_id}"
    assert request_span.context.trace_id == int(trace_id, 16)
    assert request_span.parent.span_id == int(parent_id, 16)
    assert request_span.attributes["http.route"] == "/items/{item_id}"
    assert "test-private-header" not in str(request_span.attributes)
    assert not any("http.request.header" in key for key in request_span.attributes)

    data = reader.get_metrics_data()
    assert data is not None
    durations = [
        point
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name in {"http.server.duration", "http.server.request.duration"}
        for point in metric.data.data_points
    ]
    assert durations
    assert sum(point.count for point in durations) == 1


@pytest.mark.asyncio
async def test_postgres_instruments_async_queries_once_without_parameters(
    monkeypatch: MonkeyPatch,
    memory_telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader, Mock],
) -> None:
    spans, _, create_runtime = memory_telemetry

    class StubCursor:
        async def execute(self, query: str, parameters: tuple[str, ...]) -> str:
            return parameters[0]

    async def connect(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            info=SimpleNamespace(
                dbname="orders", host="postgres", port=5432, user="api"
            ),
            cursor_factory=kwargs["cursor_factory"],
        )

    monkeypatch.setattr(psycopg.AsyncConnection, "connect", connect)
    instrumentor = otel.PsycopgInstrumentor()
    instrument = Mock(wraps=instrumentor.instrument)
    monkeypatch.setattr(instrumentor, "instrument", instrument)
    config = OtelConfig(enabled=True, fastapi_enabled=False)
    try:
        otel.setup_telemetry(new_app(), config, environment="test")
        otel.setup_telemetry(new_app(), config, environment="test")
        connection = await psycopg.AsyncConnection.connect(cursor_factory=StubCursor)
        assert (
            await connection.cursor_factory().execute(
                "SELECT %s", ("private-database-value",)
            )
            == "private-database-value"
        )

        create_runtime.assert_called_once()
        instrument.assert_called_once()
        assert instrument.call_args.kwargs["capture_parameters"] is False
        query_spans = [
            span
            for span in spans.get_finished_spans()
            if "db.statement" in span.attributes
        ]
        assert len(query_spans) == 1
        assert query_spans[0].kind is SpanKind.CLIENT
        assert query_spans[0].attributes["db.system"] == "postgresql"
        assert "SELECT" in query_spans[0].attributes["db.statement"]
        assert "private-database-value" not in str(query_spans[0].attributes)
    finally:
        instrumentor.uninstrument()


@pytest.mark.parametrize("reuse_app", [False, True])
def test_runtime_rejects_changed_configuration_in_same_worker(
    memory_telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader, Mock],
    reuse_app: bool,
) -> None:
    config = OtelConfig(enabled=True, fastapi_enabled=False, postgres_enabled=False)
    app = new_app()
    otel.setup_telemetry(app, config, environment="test")

    with pytest.raises(RuntimeError, match="restart"):
        otel.setup_telemetry(
            app if reuse_app else new_app(),
            config.model_copy(update={"service_name": "changed"}),
            environment="test",
        )


@pytest.mark.parametrize("disable_flag", ["enabled", "sdk_disabled"])
def test_runtime_requires_restart_to_disable_existing_providers(
    memory_telemetry: tuple[InMemorySpanExporter, InMemoryMetricReader, Mock],
    disable_flag: str,
) -> None:
    _, _, create_runtime = memory_telemetry
    config = OtelConfig(enabled=True, fastapi_enabled=False, postgres_enabled=False)
    otel.setup_telemetry(new_app(), config, environment="test")
    inactive = config.model_copy(update={disable_flag: disable_flag == "sdk_disabled"})
    replacement_app = new_app()

    with pytest.raises(RuntimeError, match="Restart"):
        otel.setup_telemetry(replacement_app, inactive, environment="test")

    create_runtime.assert_called_once()
    assert getattr(replacement_app.state, "otel_runtime", None) is None


def test_runtime_configures_otlp_exporters_and_resource_without_network(
    monkeypatch: MonkeyPatch,
) -> None:
    spans = InMemorySpanExporter()
    reader = InMemoryMetricReader()
    logs = InMemoryLogRecordExporter()
    span_exporter = Mock(return_value=spans)
    metric_exporter = Mock()
    log_exporter = Mock(return_value=logs)
    periodic_reader = Mock(return_value=reader)
    set_tracer = Mock()
    set_meter = Mock()
    monkeypatch.setattr(otel, "OTLPSpanExporter", span_exporter)
    monkeypatch.setattr(otel, "OTLPMetricExporter", metric_exporter)
    monkeypatch.setattr(otel, "OTLPLogExporter", log_exporter)
    monkeypatch.setattr(otel, "PeriodicExportingMetricReader", periodic_reader)
    monkeypatch.setattr(otel.trace, "set_tracer_provider", set_tracer)
    monkeypatch.setattr(
        otel.trace, "get_tracer_provider", lambda: set_tracer.call_args.args[0]
    )
    monkeypatch.setattr(otel.metrics, "set_meter_provider", set_meter)
    monkeypatch.setattr(
        otel.metrics, "get_meter_provider", lambda: set_meter.call_args.args[0]
    )
    config = OtelConfig(
        enabled=True,
        service_name="orders-api",
        service_namespace="commerce",
        service_version="test-version",
        deployment_environment="staging",
        resource_attributes="team=platform,service.name=ignored",
        exporter_otlp_endpoint="http://collector:4318",
        exporter_otlp_traces_endpoint="https://traces.example/receive",
        exporter_otlp_logs_endpoint="https://logs.example/receive",
        exporter_otlp_headers="Authorization=Bearer%20test-token,tenant=orders",
        exporter_otlp_timeout=7,
        metric_export_interval=5000,
        metric_export_timeout=2000,
    )
    runtime = otel._create_runtime(config, "fallback-environment")
    try:
        span_exporter.assert_called_once_with(
            endpoint="https://traces.example/receive",
            headers={"Authorization": "Bearer test-token", "tenant": "orders"},
            timeout=7,
        )
        metric_kwargs = metric_exporter.call_args.kwargs
        assert metric_kwargs["endpoint"] == "http://collector:4318/v1/metrics"
        assert metric_kwargs["headers"] == {
            "Authorization": "Bearer test-token",
            "tenant": "orders",
        }
        assert metric_kwargs["timeout"] == 7
        assert set(metric_kwargs["preferred_temporality"].values()) == {
            AggregationTemporality.CUMULATIVE
        }
        periodic_reader.assert_called_once_with(
            metric_exporter.return_value,
            export_interval_millis=5000,
            export_timeout_millis=2000,
        )
        set_tracer.assert_called_once_with(runtime.tracer_provider)
        set_meter.assert_called_once_with(runtime.meter_provider)
        log_exporter.assert_called_once_with(
            endpoint="https://logs.example/receive",
            headers={"Authorization": "Bearer test-token", "tenant": "orders"},
            timeout=7,
            meter_provider=runtime.meter_provider,
        )

        with runtime.tracer_provider.get_tracer("test").start_as_current_span("work"):
            assert runtime.logger_provider is not None
            runtime.logger_provider.get_logger("test").emit(body="work completed")
        runtime.force_flush()
        attributes = spans.get_finished_spans()[0].resource.attributes
        assert attributes["service.name"] == "orders-api"
        assert attributes["service.namespace"] == "commerce"
        assert attributes["service.version"] == "test-version"
        assert attributes["deployment.environment.name"] == "staging"
        assert attributes["team"] == "platform"
        assert attributes["service.instance.id"]
        log = logs.get_finished_logs()[0]
        assert log.resource.attributes == attributes
        assert log.log_record.body == "work completed"
        assert log.log_record.trace_id == spans.get_finished_spans()[0].context.trace_id
    finally:
        runtime.tracer_provider.shutdown()
        runtime.meter_provider.shutdown()
        assert runtime.logger_provider is not None
        runtime.logger_provider.shutdown()


def test_log_filter_adds_current_trace_identifiers() -> None:
    record = logging.LogRecord("api", logging.INFO, __file__, 1, "event", (), None)
    log_filter = TraceContextFilter()
    assert log_filter.filter(record) is True
    assert record.trace_id == "-"
    assert record.span_id == "-"

    context = trace.SpanContext(
        trace_id=0x12345678901234567890123456789012,
        span_id=0x1234567890123456,
        is_remote=False,
        trace_flags=trace.TraceFlags.SAMPLED,
    )
    with trace.use_span(trace.NonRecordingSpan(context)):
        assert log_filter.filter(record) is True

    assert record.trace_id == "12345678901234567890123456789012"
    assert record.span_id == "1234567890123456"
