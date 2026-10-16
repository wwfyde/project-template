"""Run inside an API container with OTel enabled; creates no database records.

Uses one unique, short-lived Redis key and prints a trace ID to find in Tempo.
"""

import asyncio
import json
import logging
from uuid import uuid4

from opentelemetry import trace
from redis_fastapi import CacheBackend, get_async_redis
from sqlalchemy import text
from starlette.requests import Request

from api.core import settings
from api.core.db import engine
from api.main import app


async def main() -> None:
    if not settings.otel.active:
        raise SystemExit("Enable OTEL_ENABLED before running this probe")
    if not (settings.redis.otel_enabled and settings.otel.postgres_enabled):
        raise SystemExit(
            "Enable Redis SDK and PostgreSQL tracing before running this probe"
        )
    async with app.router.lifespan_context(app):
        request = Request({"type": "http", "app": app})
        backend = CacheBackend(
            await get_async_redis(request), eviction_group="telemetry-smoke"
        )
        key = str(uuid4())
        with trace.get_tracer("project-template.smoke").start_as_current_span(
            "deployment.telemetry.smoke"
        ) as span:
            logging.getLogger("api").info("OpenTelemetry verification probe")
            async with engine.connect() as connection:
                assert (await connection.execute(text("SELECT 1"))).scalar_one() == 1
            try:
                await backend.set(key, {"verified": True}, ttl=60)
                assert await backend.get(key) == {"verified": True}
            finally:
                await backend.delete(key)
            result = {
                "trace_id": f"{span.get_span_context().trace_id:032x}",
                "sampled": span.get_span_context().trace_flags.sampled,
                "service": settings.otel.service_name,
                "environment": settings.otel.deployment_environment or settings.app.env,
            }
    print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
