import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.telemetry import TelemetryConfig
from redis_fastapi import AsyncRedisDep, FastAPIRedis
from sqlalchemy import text

from api import __version__
from api.core import settings
from api.core.auth_session import configure_auth_sessions
from api.core.cache import configure_redis_sdk
from api.core.db import engine
from api.core.lifespan import lifespan
from api.core.log import setup_logging
from api.core.request_context import RequestContextMiddleware
from api.telemetry import setup_telemetry

logger = logging.getLogger(__name__)


def create_app(lifespan: Callable = lifespan) -> FastAPI:
    # SDK route decorators read configuration during import, before lifespan.
    configure_redis_sdk()
    from api.routes import router
    from api.routes.examples.cache import configure_sdk_examples

    log_level = os.getenv("LOG_LEVEL") or settings.app.log_level
    setup_logging(level=log_level)
    app = FastAPI(
        lifespan=lifespan,
        # One Settings-controlled instrumentation path; FastAPI 0.139 also has
        # native telemetry which must not bypass the per-component switches.
        telemetry=TelemetryConfig(
            tracing=False,
            metrics=False,
            logs=False,
            operation_spans=False,
            auto_configure=False,
        ),
        docs_url="/docs" if settings.app.env != "prod" else None,
        redoc_url="/redoc" if settings.app.env != "prod" else None,
    )

    # The project lifespan passes Settings to the SDK and owns its pools.
    FastAPIRedis(app).caching()
    configure_sdk_examples(app, sessions=False)
    configure_auth_sessions(app, settings)
    app.add_middleware(RequestContextMiddleware, config=settings.request_context)

    app.include_router(router, prefix="/api")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/api/files", StaticFiles(directory=settings.data_dir), name="files")

    @app.get("/api/health")
    async def health_check(redis: AsyncRedisDep, response: Response) -> dict[str, Any]:
        redis_ready = False
        postgres_ready = False
        try:
            async with asyncio.timeout(3):
                redis_ready = bool(await redis.ping())
        except Exception:
            logger.warning("Redis health check failed")
        try:
            async with asyncio.timeout(3):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                postgres_ready = True
        except Exception:
            logger.warning("Postgres health check failed")
        healthy = redis_ready and postgres_ready
        if not healthy:
            response.status_code = 503

        return {
            "status": "ok" if healthy else "unavailable",
            "redis": {
                "client": type(redis).__name__,
                "pong": redis_ready,
            },
            "postgres": {"connected": postgres_ready},
            "version": __version__,
        }

    @app.get("/api/hello")
    async def hello() -> dict[str, str]:
        s: str = "世界"
        logger.error(s)
        logger.info(s)
        logger.debug(s)
        logger.warning(s)
        return {"message": f"Hello, {s}!", "data": f"hello, {s}!"}

    setup_telemetry(app, settings.otel, environment=settings.app.env)
    runtime = getattr(app.state, "otel_runtime", None)
    setup_logging(
        level=settings.app.log_level,
        logger_provider=runtime.logger_provider if runtime is not None else None,
        otel_level=settings.otel.logs_level,
    )
    logger.info(
        "API created with env=%s, debug=%s",
        settings.app.env,
        settings.app.debug,
        extra={"otel.event.name": "app.created"},
    )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    # The app has already configured Uvicorn's handlers, including OTLP logs.
    uvicorn.run(app, host="0.0.0.0", port=settings.app.port, log_config=None)


if __name__ == "__main__":
    main()
