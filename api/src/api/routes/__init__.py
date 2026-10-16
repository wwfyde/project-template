from fastapi import APIRouter

from api.core import settings
from api.routes.examples import example_router

from .config import config_router
from .agents import agents_router
from .conversations import conversations_router

router = APIRouter()
router.include_router(agents_router, prefix="/agents", tags=["agents"])

if settings.app.env != "prod":
    router.include_router(config_router, prefix="/config")
router.include_router(
    conversations_router, prefix="/conversations", tags=["conversations"]
)

router.include_router(example_router, prefix="/examples", tags=["examples"])
