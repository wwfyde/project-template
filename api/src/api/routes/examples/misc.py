from fastapi import APIRouter
from pydantic import BaseModel

from api.core import settings

misc_router = APIRouter()


@misc_router.get("/misc")
async def get_misc() -> dict:
    extra = settings.extra
    return extra.model_dump()
