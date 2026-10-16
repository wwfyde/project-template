import logging
from collections.abc import Iterator
from datetime import datetime
from weakref import WeakValueDictionary

import pytest
from opentelemetry import trace
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from pytest import CaptureFixture, MonkeyPatch

from api.core.log import ConsoleFormatter, setup_logging


@pytest.fixture(autouse=True)
def isolated_logging(monkeypatch: MonkeyPatch) -> Iterator[None]:
    # dictConfig replaces global logging configuration. Give each test its own
    # hierarchy and handler registry so pytest and other suites keep theirs.
    root = logging.RootLogger(logging.WARNING)
    monkeypatch.setattr(logging, "root", root)
    monkeypatch.setattr(logging.Logger, "root", root)
    monkeypatch.setattr(logging.Logger, "manager", logging.Manager(root))
    monkeypatch.setattr(logging, "_handlers", WeakValueDictionary())
    monkeypatch.setattr(logging, "_handlerList", [])
    yield
    logging.shutdown(logging._handlerList)


@pytest.fixture
def log_export() -> Iterator[tuple[LoggerProvider, InMemoryLogRecordExporter]]:
    exporter = InMemoryLogRecordExporter()
    provider = LoggerProvider(shutdown_on_exit=False)
    provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    yield provider, exporter
    provider.shutdown()


def test_console_and_otlp_receive_each_logger_once(
    log_export: tuple[LoggerProvider, InMemoryLogRecordExporter],
    capsys: CaptureFixture[str],
) -> None:
    provider, exporter = log_export
    setup_logging(logger_provider=provider)
    names = (
        "root",
        "api",
        "api.routes.examples",
        "API.ExternalClient",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
    )
    for index, name in enumerate(names):
        logging.getLogger(name).info("message-%s", index)

    provider.force_flush()
    records = exporter.get_finished_logs()
    assert [record.log_record.body for record in records] == [
        f"message-{index}" for index in range(len(names))
    ]
    assert [record.instrumentation_scope.name for record in records] == list(names)
    output = capsys.readouterr()
    combined = output.out + output.err
    for index in range(len(names)):
        assert combined.count(f"message-{index}") == 1
    assert "message-6" in output.out


def test_native_body_attributes_trace_and_exception_survive_console_formatting(
    log_export: tuple[LoggerProvider, InMemoryLogRecordExporter],
    capsys: CaptureFixture[str],
) -> None:
    provider, exporter = log_export
    setup_logging(logger_provider=provider)
    context = trace.SpanContext(
        trace_id=0x12345678901234567890123456789012,
        span_id=0x1234567890123456,
        is_remote=False,
        trace_flags=trace.TraceFlags.SAMPLED,
    )
    with trace.use_span(trace.NonRecordingSpan(context)):
        try:
            raise ValueError("synthetic failure")
        except ValueError:
            logging.getLogger("api.orders").exception(
                "Unable to process order %s",
                "order-42",
                extra={"otel.event.name": "order.failed", "order_id": "order-42"},
            )

    record = exporter.get_finished_logs()[0].log_record
    assert record.body == "Unable to process order order-42"
    assert record.trace_id == context.trace_id
    assert record.span_id == context.span_id
    assert record.event_name == "order.failed"
    assert record.attributes["event_name"] == "order.failed"
    assert record.attributes["order_id"] == "order-42"
    assert record.attributes["code.file.path"] == __file__
    assert record.attributes["code.function.name"] == (
        "test_native_body_attributes_trace_and_exception_survive_console_formatting"
    )
    assert record.attributes["code.line.number"] > 0
    assert record.attributes["exception.type"] == "ValueError"
    assert "ValueError: synthetic failure" in record.attributes["exception.stacktrace"]
    assert "asctime" not in record.attributes
    assert "message" not in record.attributes
    assert "trace_id" not in record.attributes
    assert "span_id" not in record.attributes
    output = capsys.readouterr().err
    assert "api.orders:" in output
    assert f"trace_id={context.trace_id:032x}" in output
    assert '"otel.event.name":"order.failed"' in output
    assert '"order_id":"order-42"' in output
    assert "ValueError: synthetic failure" in output
    assert datetime.fromisoformat(output.split(" | ", 1)[0]).tzinfo is not None


def test_console_formatter_does_not_modify_shared_record() -> None:
    record = logging.LogRecord(
        "api", logging.INFO, __file__, 1, "event %s", ("x",), None
    )
    original = record.__dict__.copy()
    formatter = ConsoleFormatter("%(asctime)s %(trace_id)s %(message)s")

    assert "event x" in formatter.format(record)
    assert record.__dict__ == original


def test_export_preserves_explicit_event_name_attribute(
    log_export: tuple[LoggerProvider, InMemoryLogRecordExporter],
) -> None:
    provider, exporter = log_export
    setup_logging(logger_provider=provider)
    logging.getLogger("api.orders").info(
        "Order event",
        extra={"otel.event.name": "order.created", "event_name": "custom.event"},
    )

    record = exporter.get_finished_logs()[0].log_record
    assert record.event_name == "order.created"
    assert record.attributes["event_name"] == "custom.event"


def test_reconfiguring_replaces_handler_and_can_disable_export(
    log_export: tuple[LoggerProvider, InMemoryLogRecordExporter],
    capsys: CaptureFixture[str],
) -> None:
    provider, exporter = log_export
    setup_logging(logger_provider=provider)
    setup_logging(logger_provider=provider)
    logging.getLogger("api.orders").info("export-once")
    assert len(exporter.get_finished_logs()) == 1
    assert capsys.readouterr().err.count("export-once") == 1

    setup_logging()
    logging.getLogger("api.orders").info("console-only")
    assert len(exporter.get_finished_logs()) == 1
    assert capsys.readouterr().err.count("console-only") == 1


@pytest.mark.parametrize(
    ("console_level", "otel_level", "console_count", "export_count"),
    [("DEBUG", "WARNING", 3, 1), ("WARNING", "DEBUG", 1, 3)],
)
def test_console_and_otlp_have_independent_levels(
    log_export: tuple[LoggerProvider, InMemoryLogRecordExporter],
    capsys: CaptureFixture[str],
    console_level: str,
    otel_level: str,
    console_count: int,
    export_count: int,
) -> None:
    provider, exporter = log_export
    setup_logging(console_level, logger_provider=provider, otel_level=otel_level)
    logger = logging.getLogger("api.orders")
    for level in (logging.DEBUG, logging.INFO, logging.WARNING):
        logger.log(level, "level-check-%s", level)

    assert len(exporter.get_finished_logs()) == export_count
    assert capsys.readouterr().err.count("level-check-") == console_count


def test_exporter_diagnostics_remain_visible_without_reexporting(
    log_export: tuple[LoggerProvider, InMemoryLogRecordExporter],
    capsys: CaptureFixture[str],
) -> None:
    provider, exporter = log_export
    setup_logging(logger_provider=provider)
    for name in (
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
        "OpenTelemetry.sdk._logs",
        "urllib3.connectionpool",
        "requests",
    ):
        logging.getLogger(name).error("export-diagnostic from %s", name)

    assert exporter.get_finished_logs() == ()
    assert capsys.readouterr().err.count("export-diagnostic") == 4


def test_access_logs_have_query_free_path_and_structured_http_fields(
    log_export: tuple[LoggerProvider, InMemoryLogRecordExporter],
    capsys: CaptureFixture[str],
) -> None:
    provider, exporter = log_export
    setup_logging(logger_provider=provider)
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "127.0.0.1:1234",
        "GET",
        "/api/orders?token=secret",
        "1.1",
        200,
    )

    record = exporter.get_finished_logs()[0].log_record
    assert record.body == '127.0.0.1:1234 - "GET /api/orders HTTP/1.1" 200'
    assert record.attributes["http.request.method"] == "GET"
    assert record.attributes["url.path"] == "/api/orders"
    assert record.attributes["http.response.status_code"] == 200
    assert "http.route" not in record.attributes
    assert "secret" not in capsys.readouterr().out


@pytest.mark.parametrize("client_logger", ["httpx", "httpx2"])
def test_http_client_request_urls_are_not_logged_by_default(
    log_export: tuple[LoggerProvider, InMemoryLogRecordExporter],
    capsys: CaptureFixture[str],
    client_logger: str,
) -> None:
    provider, exporter = log_export
    setup_logging("DEBUG", logger_provider=provider, otel_level="DEBUG")
    logging.getLogger(client_logger).info(
        'HTTP Request: GET https://example.test/download?token=secret "HTTP/1.1 200 OK"'
    )
    logging.getLogger(client_logger).warning("HTTP client retry exhausted")
    logging.getLogger("api.orders").info("Application event remains visible")

    assert [record.log_record.body for record in exporter.get_finished_logs()] == [
        "HTTP client retry exhausted",
        "Application event remains visible",
    ]
    output = capsys.readouterr().err
    assert "secret" not in output
    assert "HTTP client retry exhausted" in output
    assert "Application event remains visible" in output
