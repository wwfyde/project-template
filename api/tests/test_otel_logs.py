from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import _logs
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import ValidationError
from pytest import LogCaptureFixture, MonkeyPatch

from api import otel
from api.core.telemetry_config import OtelConfig


@pytest.fixture
def memory_exporters(
    monkeypatch: MonkeyPatch,
) -> Iterator[tuple[Mock, Mock]]:
    logs = Mock(side_effect=lambda **kwargs: InMemoryLogRecordExporter())
    spans = Mock(side_effect=lambda **kwargs: InMemorySpanExporter())
    set_tracer = Mock()
    set_meter = Mock()
    monkeypatch.setattr(otel, "_runtime", None)
    monkeypatch.setattr(otel, "_runtime_config", None)
    monkeypatch.setattr(otel, "OTLPLogExporter", logs)
    monkeypatch.setattr(otel, "OTLPSpanExporter", spans)
    monkeypatch.setattr(
        otel,
        "OTLPMetricExporter",
        Mock(side_effect=AssertionError("Metrics must remain disabled in these tests")),
    )
    monkeypatch.setattr(otel.trace, "set_tracer_provider", set_tracer)
    monkeypatch.setattr(
        otel.trace, "get_tracer_provider", lambda: set_tracer.call_args.args[0]
    )
    monkeypatch.setattr(otel.metrics, "set_meter_provider", set_meter)
    monkeypatch.setattr(
        otel.metrics, "get_meter_provider", lambda: set_meter.call_args.args[0]
    )
    try:
        yield logs, spans
    finally:
        if otel._runtime is not None:
            otel._runtime.tracer_provider.shutdown()
            otel._runtime.meter_provider.shutdown()
            if otel._runtime.logger_provider is not None:
                otel._runtime.logger_provider.shutdown()


def log_only_config(**overrides: object) -> OtelConfig:
    values = {
        "enabled": True,
        "traces_enabled": False,
        "metrics_enabled": False,
        "fastapi_enabled": False,
        "postgres_enabled": False,
        **overrides,
    }
    return OtelConfig(**values)


@pytest.mark.parametrize("level", ["debug", "TRACE", "", "WARN"])
def test_invalid_log_level_is_rejected(level: str) -> None:
    with pytest.raises(ValidationError):
        OtelConfig(logs_level=level)


@pytest.mark.parametrize(
    "overrides",
    [{"enabled": False}, {"sdk_disabled": True}, {"logs_enabled": False}],
)
def test_log_off_switches_never_create_exporters(
    memory_exporters: tuple[Mock, Mock], overrides: dict[str, bool]
) -> None:
    log_exporter, _ = memory_exporters
    app = FastAPI()

    otel.setup_telemetry(app, log_only_config(**overrides), environment="test")

    log_exporter.assert_not_called()
    runtime = getattr(app.state, "otel_runtime", None)
    assert runtime is None or runtime.logger_provider is None


@pytest.mark.parametrize("traces_enabled", [False, True])
def test_logs_export_even_when_traces_are_disabled_or_not_sampled(
    monkeypatch: MonkeyPatch,
    memory_exporters: tuple[Mock, Mock],
    traces_enabled: bool,
) -> None:
    logs = InMemoryLogRecordExporter()
    spans = InMemorySpanExporter()
    monkeypatch.setattr(otel, "OTLPLogExporter", Mock(return_value=logs))
    monkeypatch.setattr(otel, "OTLPSpanExporter", Mock(return_value=spans))
    set_global_logs = Mock()
    monkeypatch.setattr(_logs, "set_logger_provider", set_global_logs)
    runtime = otel._get_runtime(
        log_only_config(traces_enabled=traces_enabled, traces_sampler="always_off"),
        "test",
    )
    assert runtime.logger_provider is not None

    with runtime.tracer_provider.get_tracer("test").start_as_current_span(
        "work"
    ) as span:
        runtime.logger_provider.get_logger("api.test").emit(
            body="Work completed",
            attributes={"event_name": "work.completed", "item_id": "item-42"},
        )
        assert span.is_recording() is False

    runtime.force_flush()

    records = logs.get_finished_logs()
    assert len(records) == 1
    assert records[0].log_record.body == "Work completed"
    assert records[0].log_record.attributes["item_id"] == "item-42"
    assert records[0].log_record.trace_id == span.get_span_context().trace_id
    assert spans.get_finished_spans() == ()
    set_global_logs.assert_not_called()


def test_lifespan_flushes_last_business_log_and_reuses_provider(
    monkeypatch: MonkeyPatch, memory_exporters: tuple[Mock, Mock]
) -> None:
    logs = InMemoryLogRecordExporter()
    create_exporter = Mock(return_value=logs)
    monkeypatch.setattr(otel, "OTLPLogExporter", create_exporter)
    config = log_only_config()
    providers = []

    @asynccontextmanager
    async def business_lifespan(app: FastAPI) -> AsyncGenerator[None]:
        yield
        provider = app.state.otel_runtime.logger_provider
        provider.get_logger("api.test").emit(body="Business shutdown completed")

    for expected_count in (1, 2):
        app = FastAPI(lifespan=business_lifespan)
        otel.setup_telemetry(app, config, environment="test")
        otel.setup_telemetry(app, config, environment="test")
        providers.append(app.state.otel_runtime.logger_provider)
        with TestClient(app):
            pass

        assert len(logs.get_finished_logs()) == expected_count
        assert (
            logs.get_finished_logs()[-1].log_record.body
            == "Business shutdown completed"
        )

    assert providers[0] is providers[1]
    assert isinstance(providers[0], LoggerProvider)
    create_exporter.assert_called_once()


def test_flush_continues_after_failure_and_flushes_logs_last(
    caplog: LogCaptureFixture,
) -> None:
    call_order = []

    def fail_trace_flush(**kwargs: object) -> None:
        call_order.append("traces")
        raise RuntimeError("export failed")

    traces = Mock()
    traces.force_flush.side_effect = fail_trace_flush
    metrics = Mock()
    metrics.force_flush.side_effect = lambda **kwargs: call_order.append("metrics")
    logs = Mock()
    logs.force_flush.side_effect = lambda **kwargs: call_order.append("logs")

    otel.TelemetryRuntime(traces, metrics, logs).force_flush()

    assert call_order == ["traces", "metrics", "logs"]
    record = next(record for record in caplog.records if record.name == "api.otel")
    assert record.event_name == "telemetry.flush_failed"
    assert record.telemetry_signal == "traces"
    assert record.exc_info[0] is RuntimeError
