"""Small header-only examples with no user-session or data-store dependency."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.core.header_auth import HEADER_EXAMPLE_PREFIX as HEADER_EXAMPLE_PREFIX
from api.core.deps import HeaderAuthDep, verify_header_token
from api.deps import SettingsDep


async def require_development_example(settings: SettingsDep) -> None:
    if settings.app.env == "prod":
        raise HTTPException(404, "Not found", headers={"Cache-Control": "no-store"})


header_auth_router = APIRouter(
    prefix="/auth-header",
    tags=["Header authentication examples"],
    dependencies=[Depends(require_development_example)],
)


@header_auth_router.get("/ping", dependencies=[Depends(verify_header_token)])
async def header_ping() -> dict[str, object]:
    """Route dependency: only execute after a service API key is verified."""
    return {"ok": True, "authentication": "api_key"}


class HeaderEcho(BaseModel):
    message: str = Field(min_length=1, max_length=1024)


@header_auth_router.post("/echo")
async def header_echo(payload: HeaderEcho, principal: HeaderAuthDep) -> dict[str, str]:
    """Typed dependency: receive a safe principal, without the credential."""
    return {"message": payload.message, "authentication": principal.scheme}
