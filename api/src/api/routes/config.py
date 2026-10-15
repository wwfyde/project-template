import logging

from fastapi import APIRouter

from api.core.config import settings

config_router = APIRouter()

logger = logging.getLogger(__name__)


@config_router.get("")
async def get_settings() -> dict:
    logger.info("Getting settings")
    return settings.model_dump(
        exclude_unset=True,
        exclude={"postgres_dsn", "redis_dsn", "oss", "nacos"},
    )
