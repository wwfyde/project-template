import logging

from fastapi import APIRouter
from pydantic import BaseModel

from api.core import settings

misc_router = APIRouter()

logger = logging.getLogger(f"{settings.project_name}.routes.examples")


@misc_router.get("/misc")
async def get_misc() -> dict:
    extra = settings.extra
    logger.info(f"Hello, {extra}")
    logger.exception("Error !!Exception")
    return extra.model_dump()
