import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from redis_fastapi import AsyncRedisDep, FastAPIRedis

from api import __version__
from api.core import settings
from api.core.lifespan import lifespan
from api.core.log import setup_logging
from api.routes import router
from api.routes.examples.cache import configure_sdk_examples


def create_app(lifespan: Callable = lifespan) -> FastAPI:
    setup_logging(level="DEBUG" if settings.app.debug else "INFO")
    logger = logging.getLogger(__name__)
    logger.debug("Hello")
    app = FastAPI(
        lifespan=lifespan,
        docs_url="/docs" if settings.app.env != "prod" else None,
        redoc_url="/redoc" if settings.app.env != "prod" else None,
    )

    # register the redis-sdk
    FastAPIRedis(app).lifespan().caching()
    configure_sdk_examples(app)

    logger.warning(
        "starting API with env: %s, debug mode: %s",
        settings.app.env,
        settings.app.debug,
    )
    app.include_router(router, prefix="/api")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/api/files", StaticFiles(directory=settings.data_dir), name="files")

    @app.get("/api/health")
    async def health_check(redis: AsyncRedisDep) -> dict[str, Any]:
        # check redis

        return {
            "status": "ok",
            "redis": {
                "client": type(redis).__name__,  # RedisCluster
                "pong": await redis.ping(),
            },
            "version": __version__,
        }

    @app.get("/api/hello")
    async def hello() -> dict[str, str]:
        s: str = "世界"
        return {"message": f"Hello, {s}!", "data": f"hello, {s}!"}

    logger.info("API Created")

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=settings.app.port)


if __name__ == "__main__":
    main()
