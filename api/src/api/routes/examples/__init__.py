from fastapi import APIRouter

from .cache import cache_router
from .misc import misc_router

example_router = APIRouter()

example_router.include_router(cache_router)
example_router.include_router(misc_router)
