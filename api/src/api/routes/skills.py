"""OpenAI-shaped Skills endpoints with application authentication and preview extensions."""

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import Message

from api.dependencies.auth import CurrentUserDep
from api.schemas.auth import AuthUser
from api.skills.bundles import (
    MAX_ARCHIVE_BYTES,
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_REQUEST_BYTES,
    MAX_TOTAL_BYTES,
    SkillBundle,
    bundle_from_files,
    bundle_from_zip,
)
from api.skills.contracts import (
    DeletedSkill,
    DeletedSkillVersion,
    Skill,
    SkillFailure,
    SkillList,
    SkillVersion,
    SkillVersionList,
    SortOrder,
)
from api.skills.preview import SkillFilePreview, SkillTree
from api.skills.service import SkillService


class SkillRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def handle(request: Request) -> Response:
            receive = request._receive
            received = 0

            async def bounded_receive() -> Message:
                nonlocal received
                message = await receive()
                if message["type"] == "http.request":
                    received += len(message.get("body", b""))
                    if received > MAX_REQUEST_BYTES:
                        raise SkillFailure(
                            "request_too_large", "Skill request exceeds 51 MiB.", 413
                        )
                return message

            request._receive = bounded_receive
            try:
                response = await handler(request)
            except SkillFailure as exc:
                response = JSONResponse(
                    {"detail": {"code": exc.code, "message": exc.message}},
                    status_code=exc.status,
                )
            except RequestValidationError:
                response = JSONResponse(
                    {
                        "detail": {
                            "code": "invalid_request",
                            "message": "Invalid request parameters.",
                        }
                    },
                    status_code=422,
                )
            except SQLAlchemyError:
                response = JSONResponse(
                    {
                        "detail": {
                            "code": "skill_store_unavailable",
                            "message": "Skill storage is unavailable.",
                        }
                    },
                    status_code=503,
                )
            except HTTPException as exc:
                response = JSONResponse(
                    {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
                )
            finally:
                request._receive = receive
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        return handle


skills_router = APIRouter(prefix="/skills", tags=["skills"], route_class=SkillRoute)


def get_skill_service(request: Request) -> SkillService:
    service = getattr(request.app.state, "skill_service", None)
    if service is None:
        from api.core.config import settings
        from api.skills.runtime import create_skill_service

        service = create_skill_service(settings)
        request.app.state.skill_service = service
    return service


ServiceDep = Annotated[SkillService, Depends(get_skill_service)]
Limit = Annotated[int, Query(ge=0, le=100)]
Cursor = Annotated[str | None, Query(max_length=128)]
FilePath = Annotated[str, Query(min_length=1, max_length=1024)]


def _owner(user: AuthUser) -> str:
    return f"user:{user.account_id}:{user.id}"


def _upload_schema(*, version: bool = False) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "files": {"type": "string", "format": "binary", "description": "Single ZIP bundle."},
        "files[]": {
            "type": "array",
            "maxItems": 500,
            "items": {"type": "string", "format": "binary"},
        },
    }
    if version:
        properties["default"] = {"type": "boolean", "default": False}
    return {
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": properties,
                        "oneOf": [{"required": ["files"]}, {"required": ["files[]"]}],
                        "additionalProperties": False,
                    }
                }
            },
        }
    }


async def _upload(request: Request, *, version: bool = False) -> tuple[SkillBundle, bool]:
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "multipart/form-data"
    ):
        raise SkillFailure("invalid_content_type", "Upload skills as multipart/form-data.", 415)
    async with request.form(max_files=MAX_FILES, max_fields=1, max_part_size=1024) as form:
        allowed = {"files", "files[]", "default"} if version else {"files", "files[]"}
        if set(form) - allowed or len(form.getlist("default")) > 1:
            raise SkillFailure("invalid_upload", "Unexpected or duplicate upload fields.")
        make_default = form.get("default", "false")
        if make_default not in ("true", "false", "1", "0"):
            raise SkillFailure("invalid_default", "default must be a boolean.")
        zipped, directory = form.getlist("files"), form.getlist("files[]")
        if bool(zipped) == bool(directory):
            raise SkillFailure(
                "invalid_upload", "Use either one files ZIP or repeated files[] parts."
            )
        if zipped:
            if len(zipped) != 1 or not isinstance(zipped[0], UploadFile):
                raise SkillFailure("invalid_upload", "files must contain one ZIP upload.")
            content = await zipped[0].read(MAX_ARCHIVE_BYTES + 1)
            bundle = await run_in_threadpool(bundle_from_zip, content)
        else:
            files: list[tuple[str, bytes]] = []
            total = 0
            for item in directory:
                if not isinstance(item, UploadFile) or not item.filename:
                    raise SkillFailure("invalid_upload", "files[] must contain named file uploads.")
                content = await item.read(MAX_FILE_BYTES + 1)
                total += len(content)
                if len(content) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                    raise SkillFailure(
                        "invalid_upload", "Files exceed the skill bundle size limits."
                    )
                files.append((item.filename, content))
            bundle = await run_in_threadpool(bundle_from_files, files)
        return bundle, make_default in ("true", "1")


class SetSkillDefault(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    default_version: str = Field(min_length=1, max_length=10, pattern=r"^[1-9][0-9]*$")


@skills_router.post("", response_model=Skill, openapi_extra=_upload_schema())
async def create_skill(request: Request, user: CurrentUserDep, service: ServiceDep) -> Skill:
    bundle, _ = await _upload(request)
    return await service.create(_owner(user), bundle)


@skills_router.get("", response_model=SkillList)
async def list_skills(
    user: CurrentUserDep,
    service: ServiceDep,
    after: Cursor = None,
    limit: Limit = 20,
    order: SortOrder = "desc",
) -> SkillList:
    return await service.store.list_skills(_owner(user), after, limit, order)


@skills_router.get("/{skill_id}", response_model=Skill)
async def get_skill(skill_id: str, user: CurrentUserDep, service: ServiceDep) -> Skill:
    return await service.store.get_skill(_owner(user), skill_id)


@skills_router.post("/{skill_id}", response_model=Skill)
async def set_default(
    skill_id: str,
    payload: SetSkillDefault,
    user: CurrentUserDep,
    service: ServiceDep,
) -> Skill:
    return await service.store.set_default(_owner(user), skill_id, payload.default_version)


@skills_router.delete("/{skill_id}", response_model=DeletedSkill)
async def delete_skill(skill_id: str, user: CurrentUserDep, service: ServiceDep) -> DeletedSkill:
    return await service.delete_skill(_owner(user), skill_id)


async def _download(
    service: SkillService, owner: str, skill_id: str, version: str | None = None
) -> Response:
    content, saved = await service.content(owner, skill_id, version)
    return Response(
        content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{saved.skill_id}-v{saved.version}.zip"',
        },
    )


@skills_router.get(
    "/{skill_id}/content",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def get_content(skill_id: str, user: CurrentUserDep, service: ServiceDep) -> Response:
    return await _download(service, _owner(user), skill_id)


@skills_router.post(
    "/{skill_id}/versions", response_model=SkillVersion, openapi_extra=_upload_schema(version=True)
)
async def create_version(
    skill_id: str,
    request: Request,
    user: CurrentUserDep,
    service: ServiceDep,
) -> SkillVersion:
    await service.store.get_skill(_owner(user), skill_id)
    bundle, make_default = await _upload(request, version=True)
    return await service.create_version(_owner(user), skill_id, bundle, make_default)


@skills_router.get("/{skill_id}/versions", response_model=SkillVersionList)
async def list_versions(
    skill_id: str,
    user: CurrentUserDep,
    service: ServiceDep,
    after: Cursor = None,
    limit: Limit = 20,
    order: SortOrder = "desc",
) -> SkillVersionList:
    return await service.store.list_versions(_owner(user), skill_id, after, limit, order)


@skills_router.get("/{skill_id}/versions/{version}", response_model=SkillVersion)
async def get_version(
    skill_id: str, version: str, user: CurrentUserDep, service: ServiceDep
) -> SkillVersion:
    return (await service.store.get_version(_owner(user), skill_id, version)).version


@skills_router.delete("/{skill_id}/versions/{version}", response_model=DeletedSkillVersion)
async def delete_version(
    skill_id: str, version: str, user: CurrentUserDep, service: ServiceDep
) -> DeletedSkillVersion:
    return await service.delete_version(_owner(user), skill_id, version)


@skills_router.get(
    "/{skill_id}/versions/{version}/content",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def get_version_content(
    skill_id: str, version: str, user: CurrentUserDep, service: ServiceDep
) -> Response:
    return await _download(service, _owner(user), skill_id, version)


@skills_router.get("/{skill_id}/tree", response_model=SkillTree)
async def get_tree(skill_id: str, user: CurrentUserDep, service: ServiceDep) -> SkillTree:
    return await service.tree(_owner(user), skill_id)


@skills_router.get("/{skill_id}/versions/{version}/tree", response_model=SkillTree)
async def get_version_tree(
    skill_id: str, version: str, user: CurrentUserDep, service: ServiceDep
) -> SkillTree:
    return await service.tree(_owner(user), skill_id, version)


@skills_router.get("/{skill_id}/files", response_model=SkillFilePreview)
async def get_file(
    skill_id: str, user: CurrentUserDep, service: ServiceDep, path: FilePath
) -> SkillFilePreview:
    return await service.file(_owner(user), skill_id, path)


@skills_router.get("/{skill_id}/versions/{version}/files", response_model=SkillFilePreview)
async def get_version_file(
    skill_id: str,
    version: str,
    user: CurrentUserDep,
    service: ServiceDep,
    path: FilePath,
) -> SkillFilePreview:
    return await service.file(_owner(user), skill_id, path, version)
