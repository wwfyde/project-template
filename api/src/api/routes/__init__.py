from fastapi import APIRouter, Depends

from api.dependencies.auth import require_auth_user
from api.core.example_access import authorize_examples
from api.routes.auth import auth_router
from api.routes.password import password_router
from api.routes.account import account_router

from api.core import settings
from api.routes.examples import example_router
from api.routes.examples.auth_header import header_auth_router

from .config import config_router
from .agents import agents_router
from .conversations import conversations_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(password_router)
router.include_router(account_router)
# These service-call examples intentionally use only Header API Key auth.
router.include_router(header_auth_router, prefix="/examples", tags=["Header 认证教学"])
router.include_router(agents_router, prefix="/agents", tags=["agents"])

if settings.app.env != "prod":
    router.include_router(
        config_router, prefix="/config", dependencies=[Depends(require_auth_user)]
    )
router.include_router(
    conversations_router, prefix="/conversations", tags=["conversations"]
)

router.include_router(
    example_router,
    prefix="/examples",
    tags=["examples"],
    dependencies=[Depends(authorize_examples)],
)
