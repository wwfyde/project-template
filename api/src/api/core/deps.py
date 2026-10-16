"""Authentication dependencies for user sessions and explicit header-only APIs.

Header credentials grant access only where ``verify_header_token`` or
``HeaderAuthDep`` is declared. They never create a user session or identity.
"""

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, Security
from fastapi.security import APIKeyHeader

from api.auth.dependencies import CurrentUserDep, require_auth_user
from api.auth.header import HeaderPrincipal
from api.core.config import Settings, get_settings
from api.deps import SettingsDep

__all__ = [
    "CurrentUserDep",
    "HeaderAuthDep",
    "get_current_active_user",
    "get_current_user",
    "verify_header_token",
]

# Both names retain this project's session, active-user and CSRF checks.
get_current_user = require_auth_user
get_current_active_user = require_auth_user


class ConfiguredAPIKeyHeader(APIKeyHeader):
    """Expose the startup configuration to OpenAPI and honor SettingsDep."""

    def __init__(self, name: str) -> None:
        super().__init__(
            name=name,
            scheme_name="HeaderAPIKey",
            description="Configured service API key; does not authenticate a user.",
            auto_error=False,
        )

    async def __call__(
        self,
        request: Request,
        settings: Annotated[Settings | None, Depends(get_settings)] = None,
    ) -> str | None:
        config = settings if settings is not None else get_settings()
        return request.headers.get(config.auth.header.name)


api_key_scheme = ConfiguredAPIKeyHeader(get_settings().auth.header.name)
HeaderTokenDep = Annotated[str | None, Security(api_key_scheme)]


async def verify_header_token(
    request: Request,
    response: Response,
    settings: SettingsDep,
    token: HeaderTokenDep,
) -> HeaderPrincipal:
    config = settings.auth.header
    response.headers["Cache-Control"] = "no-store"
    if not config.enabled or not config.keys:
        raise HTTPException(
            503,
            "Header authentication is unavailable",
            headers={"Cache-Control": "no-store"},
        )

    values = request.headers.getlist(config.name)
    if len(values) != 1 or token is None:
        raise HTTPException(
            401,
            "Invalid header credential",
            headers={"Cache-Control": "no-store", "WWW-Authenticate": "ApiKey"},
        )

    # Evaluate every configured key so rotation order is not revealed by an
    # early return. Bytes also handle malformed non-ASCII incoming headers.
    candidate = token.encode("utf-8")
    matched = False
    for key in config.keys:
        matched |= hmac.compare_digest(candidate, key.get_secret_value().encode())
    if not matched:
        raise HTTPException(
            401,
            "Invalid header credential",
            headers={"Cache-Control": "no-store", "WWW-Authenticate": "ApiKey"},
        )
    return HeaderPrincipal()


HeaderAuthDep = Annotated[HeaderPrincipal, Depends(verify_header_token)]
