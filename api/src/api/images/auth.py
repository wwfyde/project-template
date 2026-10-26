import hmac
from typing import Annotated

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

from api.dependencies.auth import CurrentUserDep
from api.deps import SettingsDep

IMAGE_API_PREFIX = "/api/v1/images"
image_key_scheme = APIKeyHeader(
    name="X-Api-Key",
    scheme_name="ImageServiceKey",
    auto_error=False,
    description="Image service client key configured in images.clients; independent of browser sessions.",
)


async def browser_image_owner(user: CurrentUserDep) -> str:
    return f"user:{user.account_id}:{user.id}"


async def service_image_owner(
    request: Request,
    settings: SettingsDep,
    token: Annotated[str | None, Security(image_key_scheme)],
) -> str:
    if not settings.images.clients:
        raise HTTPException(
            503,
            {
                "code": "image_api_unavailable",
                "message": "External image API is not configured.",
            },
            headers={"Cache-Control": "no-store"},
        )
    candidate = (token or "").encode()
    matched = None
    for client in settings.images.clients:
        for key in client.keys:
            if hmac.compare_digest(candidate, key.get_secret_value().encode()):
                matched = client.id
    if matched is None or len(request.headers.getlist("X-Api-Key")) != 1:
        raise HTTPException(
            401,
            {"code": "invalid_api_key", "message": "Invalid image service API key."},
            headers={"Cache-Control": "no-store", "WWW-Authenticate": "ApiKey"},
        )
    request.state.authenticated = True
    # Caller-supplied identity headers never determine this namespace.
    return f"service:{matched}"
