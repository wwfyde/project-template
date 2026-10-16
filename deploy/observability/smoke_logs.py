"""Send synthetic API logs through the configured OTLP pipeline.

Run from the API directory with its usual environment/configuration:
    uv run python ../deploy/observability/smoke_logs.py

The same script runs inside the API image with ``python /path/to/smoke_logs.py``.
It starts no HTTP listener and connects to neither Postgres nor Redis. The JSON
result identifies the records to verify in Loki; emission alone does not prove
that the collector accepted or stored them.
"""

import json
import logging
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.trace import Status, StatusCode

from api.core.config import settings
from api.core.log import setup_logging
from api.otel import setup_telemetry

logger = logging.getLogger("api.observability.smoke_logs")


def main() -> None:
    if not settings.otel.active or not settings.otel.logs_enabled:
        raise SystemExit("Enable OTel and its logs signal before running this probe")

    verification_id = uuid4().hex
    app = FastAPI(
        telemetry={
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
            "auto_configure": False,
        }
    )
    setup_telemetry(app, settings.otel, environment=settings.app.env)
    runtime = app.state.otel_runtime
    setup_logging(
        logger_provider=runtime.logger_provider,
        otel_level=settings.otel.logs_level,
    )
    tracer = runtime.tracer_provider.get_tracer("api.observability.smoke_logs")

    @app.get("/observability/logs-probe")
    def logs_probe() -> dict[str, str]:
        with tracer.start_as_current_span(
            "observability.logs_probe",
            attributes={"verification.id": verification_id},
        ) as span:
            logger.info(
                "Synthetic log verification completed",
                extra={
                    "otel.event.name": "observability.logs_probe.completed",
                    "verification.id": verification_id,
                },
            )
            try:
                raise RuntimeError("Synthetic log verification failure")
            except RuntimeError as error:
                span.record_exception(error)
                span.set_status(
                    Status(StatusCode.ERROR, "Synthetic verification failure")
                )
                logger.exception(
                    "Synthetic exception log verification",
                    extra={
                        "otel.event.name": "observability.logs_probe.failed",
                        "verification.id": verification_id,
                    },
                )
            return {"trace_id": f"{span.get_span_context().trace_id:032x}"}

    # Exiting the client runs the app lifespan and flushes the shared runtime.
    with TestClient(app) as client:
        response = client.get("/observability/logs-probe")
        response.raise_for_status()
        trace_id = response.json()["trace_id"]

    resource = runtime.tracer_provider.resource.attributes
    print(
        json.dumps(
            {
                "service": resource["service.name"],
                "environment": resource["deployment.environment.name"],
                "trace_id": trace_id,
                "verification_id": verification_id,
            }
        )
    )


if __name__ == "__main__":
    main()
