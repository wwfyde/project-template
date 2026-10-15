import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.core.cache import close_redis_cache, get_async_redis

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    logger.info("startup")
    # 初始化一次, 在事件循环中创建
    await get_async_redis()  # 在事件循环里创建一次, 目标是创建

    yield
    # 优雅关闭
    await close_redis_cache()

    logger.info("shutdown")
    # 关闭全局资源
