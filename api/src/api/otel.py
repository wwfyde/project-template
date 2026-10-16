"""One OTel SDK per worker, shared by HTTP, Postgres and fastapi-redis-sdk.

Providers are initialized before Redis starts. Lifespan exit flushes all signals;
the SDK's atexit handlers close exporters when the worker process exits. Keeping
providers alive until then also supports repeated app factories without trying
to replace OpenTelemetry's write-once global providers.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import (
    Counter,
    Histogram,
    MeterProvider,
    ObservableCounter,
    ObservableUpDownCounter,
    UpDownCounter,
)
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    TraceIdRatioBased,
)

from api import __version__
from api.core.telemetry_config import OtelConfig, parse_key_values

logger = logging.getLogger(__name__)


@dataclass
class TelemetryRuntime:
    tracer_provider: TracerProvider
    meter_provider: MeterProvider
    logger_provider: LoggerProvider | None = None

    def force_flush(self) -> None:
        # Redis shuts down first so its final connection metrics are included.
        # Logs flush last, including diagnostics from the other providers.
        for signal, provider in (
            ("traces", self.tracer_provider),
            ("metrics", self.meter_provider),
            ("logs", self.logger_provider),
        ):
            if provider is None:
                continue
            try:
                if provider.force_flush(timeout_millis=5000) is False:
                    logger.warning(
                        "Telemetry flush timed out",
                        extra={
                            "event_name": "telemetry.flush_timeout",
                            "telemetry_signal": signal,
                        },
                    )
            except Exception:
                # A collector outage must not prevent application shutdown.
                logger.warning(
                    "Telemetry flush failed",
                    exc_info=True,
                    extra={
                        "event_name": "telemetry.flush_failed",
                        "telemetry_signal": signal,
                    },
                )


_runtime: TelemetryRuntime | None = None
_runtime_lock = Lock()
_runtime_config: tuple[OtelConfig, str] | None = None


def _create_runtime(config: OtelConfig, environment: str) -> TelemetryRuntime:
    attributes = parse_key_values(config.resource_attributes)
    attributes.update(
        {
            "service.name": config.service_name,
            "service.version": config.service_version or __version__,
            "deployment.environment.name": config.deployment_environment or environment,
        }
    )
    attributes.setdefault("service.instance.id", str(uuid4()))
    if config.service_namespace:
        attributes["service.namespace"] = config.service_namespace
    resource = Resource.create(attributes)
    samplers = {
        "parentbased_traceidratio": ParentBased(
            TraceIdRatioBased(config.traces_sampler_arg)
        ),
        "parentbased_always_on": ParentBased(ALWAYS_ON),
        "traceidratio": TraceIdRatioBased(config.traces_sampler_arg),
        "always_on": ALWAYS_ON,
        "always_off": ALWAYS_OFF,
    }
    headers = parse_key_values(config.exporter_otlp_headers.get_secret_value())
    tracer_provider = TracerProvider(
        resource=resource,
        sampler=samplers[config.traces_sampler]
        if config.traces_enabled
        else ALWAYS_OFF,
    )
    if config.traces_enabled:
        tracer_provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=config.endpoint("traces"),
                    headers=headers,
                    timeout=config.exporter_otlp_timeout,
                )
            )
        )
    readers = []
    if config.metrics_enabled:
        # Alloy's Prometheus exporter requires cumulative sums/histograms.
        temporality = {
            instrument: AggregationTemporality.CUMULATIVE
            for instrument in (
                Counter,
                UpDownCounter,
                Histogram,
                ObservableCounter,
                ObservableUpDownCounter,
            )
        }
        exporter = OTLPMetricExporter(
            endpoint=config.endpoint("metrics"),
            headers=headers,
            timeout=config.exporter_otlp_timeout,
            preferred_temporality=temporality,
        )
        readers.append(
            PeriodicExportingMetricReader(
                exporter,
                export_interval_millis=config.metric_export_interval,
                export_timeout_millis=config.metric_export_timeout,
            )
        )
    meter_provider = MeterProvider(resource=resource, metric_readers=readers)
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    if (
        trace.get_tracer_provider() is not tracer_provider
        or metrics.get_meter_provider() is not meter_provider
    ):
        tracer_provider.shutdown()
        meter_provider.shutdown()
        raise RuntimeError(
            "OTel is already configured; use the application Settings instead of a second auto-instrumentation bootstrap"
        )
    logger_provider = None
    if config.logs_enabled:
        logger_provider = LoggerProvider(
            resource=resource, meter_provider=meter_provider
        )
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(
                OTLPLogExporter(
                    endpoint=config.endpoint("logs"),
                    headers=headers,
                    timeout=config.exporter_otlp_timeout,
                    meter_provider=meter_provider,
                ),
                meter_provider=meter_provider,
            )
        )
    # The logging handler receives this provider explicitly. Keeping it local
    # avoids replacing the write-once global provider used by other libraries.
    return TelemetryRuntime(tracer_provider, meter_provider, logger_provider)


def _get_runtime(config: OtelConfig, environment: str) -> TelemetryRuntime:
    global _runtime, _runtime_config
    with _runtime_lock:
        if _runtime is None:
            _runtime = _create_runtime(config, environment)
            _runtime_config = (config.model_copy(deep=True), environment)
        elif _runtime_config != (config, environment):
            raise RuntimeError(
                "OTel configuration changed inside a running worker; restart it to apply Settings"
            )
        return _runtime


def setup_telemetry(
    app: FastAPI,
    config: OtelConfig,
    *,
    environment: str,
) -> None:
    if not config.active:
        if _runtime is not None:
            raise RuntimeError(
                "Restart the worker to disable its existing OTel providers"
            )
        return
    runtime = _get_runtime(config, environment)
    if getattr(app.state, "otel_runtime", None) is not None:
        return
    app.state.otel_runtime = runtime
    if config.fastapi_enabled:
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=runtime.tracer_provider,
            meter_provider=runtime.meter_provider,
            excluded_urls=config.excluded_urls,
            exclude_spans=["send", "receive"],
            http_capture_headers_server_request=[],
            http_capture_headers_server_response=[],
            http_capture_headers_sanitize_fields=[".*"],
        )
    if config.postgres_enabled:
        instrumentor = PsycopgInstrumentor()
        if not instrumentor.is_instrumented_by_opentelemetry:
            # Covers async SQLAlchemy through its psycopg driver. Instrument
            # one layer only; SQLAlchemy 2.1 is not supported by the SA plugin.
            instrumentor.instrument(
                tracer_provider=runtime.tracer_provider,
                enable_commenter=False,
                capture_parameters=False,
            )
    existing_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def telemetry_lifespan(
        application: FastAPI,
    ) -> AsyncGenerator[Mapping[str, Any] | None]:
        try:
            async with existing_lifespan(application) as state:
                yield state
        finally:
            await asyncio.to_thread(runtime.force_flush)

    app.router.lifespan_context = telemetry_lifespan
