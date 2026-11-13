"""Application-owned Skills API contracts and persistence boundaries."""

from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

type SortOrder = Literal["asc", "desc"]


class Skill(BaseModel):
    id: str
    object: Literal["skill"] = "skill"
    created_at: int
    name: str
    description: str
    default_version: str
    latest_version: str


class SkillVersion(BaseModel):
    id: str
    object: Literal["skill.version"] = "skill.version"
    created_at: int
    name: str
    description: str
    skill_id: str
    version: str


class SkillList(BaseModel):
    object: Literal["list"] = "list"
    data: list[Skill]
    first_id: str | None
    last_id: str | None
    has_more: bool


class SkillVersionList(BaseModel):
    object: Literal["list"] = "list"
    data: list[SkillVersion]
    first_id: str | None
    last_id: str | None
    has_more: bool


class DeletedSkill(BaseModel):
    id: str
    object: Literal["skill.deleted"] = "skill.deleted"
    deleted: Literal[True] = True


class DeletedSkillVersion(BaseModel):
    id: str
    object: Literal["skill.version.deleted"] = "skill.version.deleted"
    deleted: Literal[True] = True
    version: str


class SkillFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    size: int = Field(ge=0)
    media_type: str
    sha256: str


class SkillFailure(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class StoredVersion:
    version: SkillVersion
    archive_key: str
    files: list[SkillFile]


class ObjectStorage(Protocol):
    async def put(self, key: str, content: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class SkillStore(Protocol):
    async def create(
        self,
        owner: str,
        skill_id: str,
        version_id: str,
        created_at: int,
        name: str,
        description: str,
        archive_key: str,
        files: list[SkillFile],
    ) -> Skill: ...
    async def create_version(
        self,
        owner: str,
        skill_id: str,
        version_id: str,
        created_at: int,
        name: str,
        description: str,
        archive_key: str,
        files: list[SkillFile],
        make_default: bool = False,
    ) -> SkillVersion: ...
    async def get_skill(self, owner: str, skill_id: str) -> Skill: ...
    async def list_skills(
        self,
        owner: str,
        after: str | None = None,
        limit: int = 20,
        order: SortOrder = "desc",
    ) -> SkillList: ...
    async def get_version(
        self,
        owner: str,
        skill_id: str,
        version: str | None = None,
    ) -> StoredVersion: ...
    async def list_versions(
        self,
        owner: str,
        skill_id: str,
        after: str | None = None,
        limit: int = 20,
        order: SortOrder = "desc",
    ) -> SkillVersionList: ...
    async def set_default(self, owner: str, skill_id: str, version: str) -> Skill: ...
    async def delete_skill(self, owner: str, skill_id: str) -> DeletedSkill: ...
    async def delete_version(
        self,
        owner: str,
        skill_id: str,
        version: str,
    ) -> DeletedSkillVersion: ...
    async def queue_delete(self, key: str) -> None: ...
    async def pending_deletes(self, limit: int = 100) -> list[str]: ...
    async def defer_delete(self, key: str) -> None: ...
    async def acknowledge_delete(self, key: str) -> None: ...
