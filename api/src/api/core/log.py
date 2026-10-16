import json
import logging.config
from copy import copy
from datetime import datetime
from typing import Literal

from opentelemetry import trace
from opentelemetry.sdk._logs import LoggerProvider


_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
    "trace_id",
    "span_id",
    "otelTraceID",
    "otelSpanID",
    "otelTraceSampled",
    "otelServiceName",
}


class TraceContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = trace.get_current_span().get_span_context()
        record.trace_id = f"{context.trace_id:032x}" if context.is_valid else "-"
        record.span_id = f"{context.span_id:016x}" if context.is_valid else "-"
        return True


class ConsoleFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        return (
            datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds")
        )

    def format(self, record: logging.LogRecord) -> str:
        # Formatting must not add display-only fields to the record sent by OTLP.
        display_record = copy(record)
        TraceContextFilter().filter(display_record)
        attributes = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RECORD_FIELDS
        }
        if attributes:
            display_record.msg = (
                record.getMessage()
                + " | "
                + json.dumps(
                    attributes, ensure_ascii=False, separators=(",", ":"), default=str
                )
            )
            display_record.args = ()
        return super().format(display_record)


class AccessLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if (
            record.name == "uvicorn.access"
            and isinstance(record.args, tuple)
            and len(record.args) == 5
        ):
            client, method, path, version, status = record.args
            if isinstance(path, str):
                # Uvicorn supplies a concrete URL, not a route template. Never
                # send its query string, which can contain credentials or PII.
                path = path.partition("?")[0]
                record.args = (client, method, path, version, status)
                record.__dict__.update(
                    {
                        "http.request.method": method,
                        "url.path": path,
                        "http.response.status_code": status,
                    }
                )
        return True


class ExportLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # A failed export can log via the SDK or its HTTP client. Sending those
        # records through the same exporter would create a feedback loop.
        name = record.name.lower()
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in ("opentelemetry", "urllib3", "requests")
        ):
            return False
        event_name = record.__dict__.get("otel.event.name")
        if isinstance(event_name, str):
            # Keep a searchable attribute for backends that do not yet retain
            # the native OTel event_name promoted by LoggingHandler.
            record.__dict__.setdefault("event_name", event_name)
        return True


def setup_logging(
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
    *,
    logger_provider: LoggerProvider | None = None,
    otel_level: str = "INFO",
) -> None:
    logger_level = logging.getLevelNamesMapping()[level]
    if logger_provider is not None:
        logger_level = min(logger_level, logging.getLevelNamesMapping()[otel_level])
    handlers = ["console"]
    access_handlers = ["access_console"]
    if logger_provider is not None:
        handlers.append("otel")
        access_handlers.append("otel")

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "access": {"()": AccessLogFilter},
            "export": {"()": ExportLogFilter},
        },
        "formatters": {
            "default": {
                "()": ConsoleFormatter,
                "format": "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | trace_id=%(trace_id)s span_id=%(span_id)s | %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "default",
                "filters": ["access"],
            },
            "access_console": {
                "class": "logging.StreamHandler",
                "level": level,
                "formatter": "default",
                "filters": ["access"],
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            # 你的业务日志
            "api": {
                "handlers": handlers,
                "level": logger_level,
                "propagate": False,
            },
            # Uvicorn 自身日志
            "uvicorn": {
                "handlers": handlers,
                "level": logger_level,
                "propagate": False,
            },
            "uvicorn.error": {
                "handlers": handlers,
                "level": logger_level,
                "propagate": False,
            },
            "uvicorn.access": {
                "handlers": access_handlers,
                "level": logger_level,
                "propagate": False,
            },
            # HTTP client INFO request logs contain full URLs, including signed
            # query strings. Keep warnings/errors without exporting those URLs.
            "httpx": {
                "handlers": handlers,
                "level": "WARNING",
                "propagate": False,
            },
            "httpx2": {
                "handlers": handlers,
                "level": "WARNING",
                "propagate": False,
            },
        },
        "root": {
            "handlers": handlers,
            "level": logger_level,
        },
    }
    if logger_provider is not None:
        logging_config["handlers"]["otel"] = {
            "class": "opentelemetry.instrumentation.logging.handler.LoggingHandler",
            "level": otel_level,
            "logger_provider": logger_provider,
            "log_code_attributes": True,
            "filters": ["access", "export"],
        }
    logging.config.dictConfig(logging_config)
