"""Keep teaching endpoints inside the application's authorization boundary."""

from fastapi import HTTPException, Request
from pydantic import ValidationError

from api.auth.dependencies import CurrentUserDep, UsersDep, authorize_resource
from api.core.config import settings

_SESSION_EXAMPLE_PATH = "/api/examples/cache/sdk/session"
_BATCH_EXAMPLE_PATH = "/api/examples/cache/conversations/batch"


async def authorize_examples(
    request: Request, user: CurrentUserDep, users: UsersDep
) -> None:
    path = request.url.path
    if (
        settings.app.env == "prod"
        or path == _SESSION_EXAMPLE_PATH
        or path.startswith(f"{_SESSION_EXAMPLE_PATH}/")
    ):
        # The SDK teaching routes can rotate or revoke sessions. In the main
        # application these would mutate the real authentication session.
        raise HTTPException(404, "Not found")

    await authorize_resource(request, user, users)
    if request.method == "POST" and path == _BATCH_EXAMPLE_PATH:
        # Import lazily: the main router imports this dependency while mounting
        # the examples. Reuse their schema without creating an import cycle.
        from api.routes.examples.cache import ConversationBatch

        try:
            payload = ConversationBatch.model_validate(await request.json())
        except (ValidationError, ValueError) as exc:
            raise HTTPException(422, "Invalid conversation batch") from exc
        for conversation_id in dict.fromkeys(str(item) for item in payload.ids):
            if not await users.owns("conversation", conversation_id, user):
                raise HTTPException(404, "Resource not found")
