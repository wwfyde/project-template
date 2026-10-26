import json
import logging
from collections.abc import Callable, Coroutine
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.responses import JSONResponse
from starlette.types import Message

from api.core.request_context import correlation_attributes
from api.deps import SettingsDep
from api.images.auth import browser_image_owner, service_image_owner
from api.images.contracts import (
    AssetResponse,
    CommentCreate,
    EditRequest,
    ImageAsset,
    ImageComment,
    ImageFailure,
    ProviderInfo,
)
from api.images.service import ImageService

logger = logging.getLogger(__name__)

# These built-in messages describe schema rules, not the rejected value.
# Custom ValueError/AssertionError messages can contain private input.
_SAFE_ERROR_TYPES = {
    "missing",
    "literal_error",
    "string_type",
    "string_too_short",
    "string_too_long",
    "string_pattern_mismatch",
    "int_type",
    "int_parsing",
    "int_from_float",
    "float_type",
    "float_parsing",
    "finite_number",
    "bool_type",
    "bool_parsing",
    "list_type",
    "dict_type",
    "model_type",
    "model_attributes_type",
    "extra_forbidden",
    "greater_than",
    "greater_than_equal",
    "less_than",
    "less_than_equal",
    "too_short",
    "too_long",
    "uuid_type",
    "uuid_parsing",
    "uuid_version",
}
_JSON_REASONS = {
    "Illegal trailing comma before end of object": "Trailing comma is not allowed",
    "Illegal trailing comma before end of array": "Trailing comma is not allowed",
    "Expecting property name enclosed in double quotes": "Expected a property name in double quotes",
    "Expecting value": "Expected a JSON value",
    "Expecting ',' delimiter": "Expected a comma between JSON values",
    "Expecting ':' delimiter": "Expected a colon after the property name",
    "Extra data": "Unexpected data after the JSON value",
    "Unterminated string starting at": "Unterminated JSON string",
    "Invalid control character at": "Invalid control character in JSON string",
    "Invalid \\escape": "Invalid JSON escape sequence",
    "Invalid \\uXXXX escape": "Invalid JSON Unicode escape sequence",
}


def _schema_field_names(schema: object) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        names.update(schema.get("properties", {}))
        for value in schema.values():
            names.update(_schema_field_names(value))
    elif isinstance(schema, list):
        for value in schema:
            names.update(_schema_field_names(value))
    return names


class ImageRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        public_fields = {"body", "query", "path", "header", "cookie"}
        for parameter in (
            self.dependant.body_params
            + self.dependant.query_params
            + self.dependant.path_params
            + self.dependant.header_params
            + self.dependant.cookie_params
        ):
            public_fields.update({parameter.name, parameter.alias})
            annotation = parameter.field_info.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                public_fields.update(
                    _schema_field_names(annotation.model_json_schema())
                )

        async def handle(request: Request) -> Response:
            try:
                if request.method in {"POST", "PUT", "PATCH"}:
                    # Bound the actual streamed body before multipart/JSON parsing,
                    # including chunked uploads with no Content-Length header.
                    # Configuration cannot exceed 20 MiB; the service enforces
                    # its lower configured limit on both input and normalized PNG.
                    limit = 20 * 1024 * 1024 + 128 * 1024
                    body = bytearray()
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > limit:
                            raise ImageFailure(
                                "request_too_large",
                                "Request exceeds the image upload limit.",
                                413,
                            )
                        body.extend(chunk)

                    original_receive = request.receive
                    consumed = False

                    async def receive() -> Message:
                        nonlocal consumed
                        if consumed:
                            return await original_receive()
                        consumed = True
                        return {
                            "type": "http.request",
                            "body": bytes(body),
                            "more_body": False,
                        }

                    request = Request(request.scope, receive)
                response = await handler(request)
                response.headers["Cache-Control"] = "private, no-store"
                response.headers["X-Content-Type-Options"] = "nosniff"
                return response
            except ImageFailure as error:
                return JSONResponse(
                    {"detail": {"code": error.code, "message": error.message}},
                    status_code=error.status,
                    headers={"Cache-Control": "no-store"},
                )
            except RequestValidationError as error:
                # Do not echo image data, private prompts or comment bodies.
                errors = error.errors()
                diagnostics = []
                locations = []
                decoder = error.__cause__
                for item in errors[:20]:
                    kind = item.get("type", "validation_error")
                    kind = (
                        kind
                        if kind
                        in _SAFE_ERROR_TYPES
                        | {"json_invalid", "value_error", "assertion_error"}
                        else "validation_error"
                    )
                    location = [
                        part
                        if type(part) is int or part in public_fields
                        else "<field>"
                        for part in item.get("loc", ())
                    ]
                    if kind == "extra_forbidden" and location:
                        location[-1] = "<extra_field>"
                    message = (
                        item.get("msg", "Invalid value")
                        if kind in _SAFE_ERROR_TYPES
                        else "Value failed validation"
                    )
                    diagnostic = {"type": kind, "loc": location, "msg": message}
                    if kind == "json_invalid":
                        message = "Invalid JSON syntax"
                        if isinstance(decoder, json.JSONDecodeError):
                            reason = _JSON_REASONS.get(
                                decoder.msg, "Invalid JSON syntax"
                            )
                            message = f"{reason} (line {decoder.lineno}, column {decoder.colno})"
                            diagnostic["json"] = {
                                "line": decoder.lineno,
                                "column": decoder.colno,
                                "position": decoder.pos,
                            }
                        diagnostic["msg"] = message
                        # Improve the safe response detail as well as the log.
                        item["msg"] = message
                    diagnostics.append(diagnostic)
                    if (
                        kind == "json_invalid"
                        and len(location) == 2
                        and type(location[1]) is int
                    ):
                        display_location = f"body@{location[1]}"
                    else:
                        display_location = "".join(
                            f"[{part}]" if type(part) is int else f".{part}"
                            for part in location
                        ).lstrip(".")
                    locations.append(display_location)
                summary = "; ".join(
                    f"{location} [{item['type']}]: {item['msg']}"
                    for location, item in zip(locations, diagnostics)
                )
                logger.error(
                    "Request validation failed: %s %s status=422; %s",
                    request.method.strip(),
                    self.path,
                    summary,
                    extra={
                        **correlation_attributes(),
                        "otel.event.name": "http.request.validation_failed",
                        "http.request.method": request.method.strip(),
                        "http.route": self.path,
                        "http.response.status_code": 422,
                        "validation.error_count": len(errors),
                        "validation.error_locations": locations,
                        "validation.error_types": [
                            item["type"] for item in diagnostics
                        ],
                        "validation.errors": json.dumps(
                            diagnostics, ensure_ascii=False
                        ),
                        "validation.errors_truncated": len(errors) > len(diagnostics),
                    },
                )
                return JSONResponse(
                    {
                        "detail": [
                            {
                                key: item[key]
                                for key in ("type", "loc", "msg")
                                if key in item
                            }
                            for item in errors
                        ]
                    },
                    status_code=422,
                    headers={"Cache-Control": "no-store"},
                )

        return handle


async def get_image_service(request: Request, settings: SettingsDep) -> ImageService:
    service = getattr(request.app.state, "image_service", None)
    if service is None:
        from api.images.runtime import create_image_service

        service = create_image_service(settings)
        request.app.state.image_service = service
    return service


ServiceDep = Annotated[ImageService, Depends(get_image_service)]


def create_image_router(prefix: str, authorize: Callable) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=["images"], route_class=ImageRoute)
    OwnerDep = Annotated[str, Depends(authorize)]

    def public_asset(asset: ImageAsset) -> AssetResponse:
        return AssetResponse(
            **asset.model_dump(), content_url=f"/api{prefix}/assets/{asset.id}/content"
        )

    @router.get("/providers", response_model=list[ProviderInfo])
    async def providers(owner: OwnerDep, service: ServiceDep) -> list[ProviderInfo]:
        return service.provider_info()

    @router.post("/assets", response_model=AssetResponse, status_code=201)
    async def upload(
        owner: OwnerDep,
        service: ServiceDep,
        file: Annotated[UploadFile, File()],
        purpose: Annotated[Literal["image", "mask"], Form()] = "image",
    ) -> AssetResponse:
        try:
            content = await file.read(service.config.max_upload_bytes + 1)
            return public_asset(
                await service.upload(owner, content, file.filename or "image", purpose)
            )
        finally:
            await file.close()

    @router.get("/assets", response_model=list[AssetResponse])
    async def assets(
        owner: OwnerDep,
        service: ServiceDep,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ) -> list[AssetResponse]:
        return [
            public_asset(asset)
            for asset in await service.store.list_assets(owner, limit)
        ]

    @router.get("/assets/{asset_id}", response_model=AssetResponse)
    async def asset(
        asset_id: UUID, owner: OwnerDep, service: ServiceDep
    ) -> AssetResponse:
        return public_asset(await service.store.get_asset(owner, str(asset_id)))

    @router.get("/assets/{asset_id}/content")
    async def content(
        asset_id: UUID, owner: OwnerDep, service: ServiceDep, download: bool = False
    ) -> Response:
        data = await service.store.get_content(owner, str(asset_id))
        return Response(
            data,
            media_type="image/png",
            headers={
                "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{asset_id}.png"'
            },
        )

    @router.post(
        "/assets/{asset_id}/edits", response_model=AssetResponse, status_code=201
    )
    async def edit(
        asset_id: UUID, payload: EditRequest, owner: OwnerDep, service: ServiceDep
    ) -> AssetResponse:
        return public_asset(await service.edit(owner, str(asset_id), payload))

    @router.get("/assets/{asset_id}/comments", response_model=list[ImageComment])
    async def comments(
        asset_id: UUID, owner: OwnerDep, service: ServiceDep
    ) -> list[ImageComment]:
        return await service.store.list_comments(owner, str(asset_id))

    @router.post(
        "/assets/{asset_id}/comments", response_model=ImageComment, status_code=201
    )
    async def comment(
        asset_id: UUID, payload: CommentCreate, owner: OwnerDep, service: ServiceDep
    ) -> ImageComment:
        return await service.comment(owner, str(asset_id), payload)

    @router.delete("/assets/{asset_id}/comments/{comment_id}", status_code=204)
    async def delete_comment(
        asset_id: UUID, comment_id: UUID, owner: OwnerDep, service: ServiceDep
    ) -> Response:
        await service.store.delete_comment(owner, str(asset_id), str(comment_id))
        return Response(status_code=204)

    return router


images_router = create_image_router("/images", browser_image_owner)
image_service_router = create_image_router("/v1/images", service_image_owner)
