import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis_fastapi import redis_lifespan

from api.core.cache import configure_redis_sdk
from api.core.db import engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    configure_redis_sdk()
    logger.info("startup")
    try:
        async with redis_lifespan(app):
            yield
    finally:
        await engine.dispose()
        logger.info("shutdown")
