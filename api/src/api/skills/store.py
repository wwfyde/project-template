"""Transactional, owner-scoped metadata storage for immutable skill bundles."""

import time

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models.skill import SkillObjectDeletionRecord, SkillRecord, SkillVersionRecord
from api.skills.contracts import (
    DeletedSkill,
    DeletedSkillVersion,
    Skill,
    SkillFailure,
    SkillFile,
    SkillList,
    SkillVersion,
    SkillVersionList,
    SortOrder,
    StoredVersion,
)


def _not_found() -> SkillFailure:
    return SkillFailure("skill_not_found", "Skill resource not found.", 404)


def _skill(record: SkillRecord) -> Skill:
    return Skill(
        id=record.id,
        created_at=record.created_at,
        name=record.name,
        description=record.description,
        default_version=str(record.default_version),
        latest_version=str(record.latest_version),
    )


def _version(record: SkillVersionRecord) -> SkillVersion:
    return SkillVersion(
        id=record.id,
        skill_id=record.skill_id,
        version=str(record.version),
        created_at=record.created_at,
        name=record.name,
        description=record.description,
    )


def _number(version: str, skill: SkillRecord, *, aliases: bool = True) -> int:
    if aliases and version == "latest":
        return skill.latest_version
    if not version.isascii() or not version.isdecimal() or len(version) > 10:
        raise SkillFailure("invalid_version", "Version must be a positive integer string.")
    number = int(version)
    if number < 1 or number > 2_147_483_647 or str(number) != version:
        raise SkillFailure("invalid_version", "Version must be a positive integer string.")
    return number


class PostgresSkillStore:
    """Parent row locks serialize version numbers, pointers and cascading deletes."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _queue_delete(self, db: AsyncSession, key: str) -> None:
        await db.execute(
            insert(SkillObjectDeletionRecord)
            .values(archive_key=key)
            .on_conflict_do_nothing(index_elements=["archive_key"])
        )

    async def _require_skill(
        self,
        db: AsyncSession,
        owner: str,
        skill_id: str,
        *,
        write: bool = False,
        lock: bool = False,
    ) -> SkillRecord:
        query = select(SkillRecord).where(SkillRecord.id == skill_id, SkillRecord.owner == owner)
        if write or lock:
            query = query.with_for_update(read=not write)
        result = await db.execute(query)
        skill = result.scalar_one_or_none()
        if skill is None:
            raise _not_found()
        return skill

    async def _require_version(
        self,
        db: AsyncSession,
        skill: SkillRecord,
        version: str | None,
        *,
        aliases: bool = True,
    ) -> SkillVersionRecord:
        number = (
            skill.default_version if version is None else _number(version, skill, aliases=aliases)
        )
        result = await db.execute(
            select(SkillVersionRecord).where(
                SkillVersionRecord.skill_id == skill.id, SkillVersionRecord.version == number
            )
        )
        record = result.scalar_one_or_none()
        if record is None:
            raise _not_found()
        return record

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
    ) -> Skill:
        try:
            async with self.sessions.begin() as db:
                record = SkillRecord(
                    id=skill_id,
                    owner=owner,
                    created_at=created_at,
                    name=name,
                    description=description,
                    default_version=1,
                    latest_version=1,
                    next_version=2,
                )
                db.add(record)
                await db.flush()
                db.add(
                    SkillVersionRecord(
                        id=version_id,
                        skill_id=skill_id,
                        version=1,
                        created_at=created_at,
                        name=name,
                        description=description,
                        archive_key=archive_key,
                        files=[file.model_dump() for file in files],
                    )
                )
                public = _skill(record)
            return public
        except IntegrityError as exc:
            raise SkillFailure("skill_conflict", "Skill could not be created.", 409) from exc

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
    ) -> SkillVersion:
        async with self.sessions.begin() as db:
            skill = await self._require_skill(db, owner, skill_id, write=True)
            version = skill.next_version
            record = SkillVersionRecord(
                id=version_id,
                skill_id=skill_id,
                version=version,
                created_at=created_at,
                name=name,
                description=description,
                archive_key=archive_key,
                files=[file.model_dump() for file in files],
            )
            db.add(record)
            skill.latest_version = version
            skill.next_version = version + 1
            if make_default:
                skill.default_version = version
                skill.name, skill.description = name, description
            public = _version(record)
        return public

    async def get_skill(self, owner: str, skill_id: str) -> Skill:
        async with self.sessions.begin() as db:
            return _skill(await self._require_skill(db, owner, skill_id))

    async def list_skills(
        self,
        owner: str,
        after: str | None = None,
        limit: int = 20,
        order: SortOrder = "desc",
    ) -> SkillList:
        async with self.sessions.begin() as db:
            query = select(SkillRecord).where(SkillRecord.owner == owner)
            if after is not None:
                cursor = await self._require_skill(db, owner, after)
                if order == "asc":
                    after_condition = or_(
                        SkillRecord.created_at > cursor.created_at,
                        and_(
                            SkillRecord.created_at == cursor.created_at, SkillRecord.id > cursor.id
                        ),
                    )
                else:
                    after_condition = or_(
                        SkillRecord.created_at < cursor.created_at,
                        and_(
                            SkillRecord.created_at == cursor.created_at, SkillRecord.id < cursor.id
                        ),
                    )
                query = query.where(after_condition)
            order_by = (
                (SkillRecord.created_at.asc(), SkillRecord.id.asc())
                if order == "asc"
                else (SkillRecord.created_at.desc(), SkillRecord.id.desc())
            )
            result = await db.execute(query.order_by(*order_by).limit(limit + 1))
            records = list(result.scalars())
            data = [_skill(record) for record in records[:limit]]
            return SkillList(
                data=data,
                first_id=data[0].id if data else None,
                last_id=data[-1].id if data else None,
                has_more=len(records) > limit,
            )

    async def get_version(
        self,
        owner: str,
        skill_id: str,
        version: str | None = None,
    ) -> StoredVersion:
        async with self.sessions.begin() as db:
            skill = await self._require_skill(db, owner, skill_id, lock=True)
            record = await self._require_version(db, skill, version)
            return StoredVersion(
                version=_version(record),
                archive_key=record.archive_key,
                files=[SkillFile.model_validate(file) for file in record.files],
            )

    async def list_versions(
        self,
        owner: str,
        skill_id: str,
        after: str | None = None,
        limit: int = 20,
        order: SortOrder = "desc",
    ) -> SkillVersionList:
        async with self.sessions.begin() as db:
            skill = await self._require_skill(db, owner, skill_id, lock=True)
            query = select(SkillVersionRecord).where(SkillVersionRecord.skill_id == skill.id)
            if after is not None:
                result = await db.execute(query.where(SkillVersionRecord.id == after))
                cursor = result.scalar_one_or_none()
                if cursor is None:
                    # A valid cursor from another owned skill is a client error.
                    # Foreign owners' IDs remain indistinguishable from absent IDs.
                    other = await db.execute(
                        select(SkillVersionRecord.id)
                        .join(SkillRecord, SkillRecord.id == SkillVersionRecord.skill_id)
                        .where(SkillVersionRecord.id == after, SkillRecord.owner == owner)
                    )
                    if other.scalar_one_or_none() is not None:
                        raise SkillFailure(
                            "invalid_cursor", "Pagination cursor belongs to another skill.", 400
                        )
                    raise _not_found()
                query = query.where(
                    SkillVersionRecord.version > cursor.version
                    if order == "asc"
                    else SkillVersionRecord.version < cursor.version
                )
            query = query.order_by(
                SkillVersionRecord.version.asc()
                if order == "asc"
                else SkillVersionRecord.version.desc()
            )
            result = await db.execute(query.limit(limit + 1))
            records = list(result.scalars())
            data = [_version(record) for record in records[:limit]]
            return SkillVersionList(
                data=data,
                first_id=data[0].id if data else None,
                last_id=data[-1].id if data else None,
                has_more=len(records) > limit,
            )

    async def set_default(self, owner: str, skill_id: str, version: str) -> Skill:
        async with self.sessions.begin() as db:
            skill = await self._require_skill(db, owner, skill_id, write=True)
            record = await self._require_version(db, skill, version, aliases=False)
            skill.default_version = record.version
            skill.name, skill.description = record.name, record.description
            public = _skill(skill)
        return public

    async def delete_skill(self, owner: str, skill_id: str) -> DeletedSkill:
        async with self.sessions.begin() as db:
            await self._require_skill(db, owner, skill_id, write=True)
            result = await db.execute(
                select(SkillVersionRecord.archive_key).where(
                    SkillVersionRecord.skill_id == skill_id
                )
            )
            for key in result.scalars():
                await self._queue_delete(db, key)
            await db.execute(delete(SkillRecord).where(SkillRecord.id == skill_id))
        return DeletedSkill(id=skill_id)

    async def delete_version(
        self,
        owner: str,
        skill_id: str,
        version: str,
    ) -> DeletedSkillVersion:
        async with self.sessions.begin() as db:
            skill = await self._require_skill(db, owner, skill_id, write=True)
            record = await self._require_version(db, skill, version, aliases=False)
            result = await db.execute(
                select(SkillVersionRecord.version)
                .where(SkillVersionRecord.skill_id == skill_id, SkillVersionRecord.id != record.id)
                .order_by(SkillVersionRecord.version.desc())
                .limit(1)
            )
            remaining_latest = result.scalar_one_or_none()
            if remaining_latest is not None and record.version == skill.default_version:
                raise SkillFailure(
                    "default_version", "Set another default before deleting this version.", 400
                )
            public = DeletedSkillVersion(id=record.id, version=str(record.version))
            await self._queue_delete(db, record.archive_key)
            if remaining_latest is None:
                await db.execute(delete(SkillRecord).where(SkillRecord.id == skill_id))
            else:
                skill.latest_version = remaining_latest
                await db.execute(
                    delete(SkillVersionRecord).where(SkillVersionRecord.id == record.id)
                )
        return public

    async def queue_delete(self, key: str) -> None:
        async with self.sessions.begin() as db:
            await self._queue_delete(db, key)

    async def pending_deletes(self, limit: int = 100) -> list[str]:
        async with self.sessions.begin() as db:
            result = await db.execute(
                select(SkillObjectDeletionRecord.archive_key)
                .where(
                    ~select(SkillVersionRecord.id)
                    .where(SkillVersionRecord.archive_key == SkillObjectDeletionRecord.archive_key)
                    .exists()
                )
                .order_by(
                    SkillObjectDeletionRecord.last_attempt_at, SkillObjectDeletionRecord.archive_key
                )
                .limit(limit)
            )
            return list(result.scalars())

    async def defer_delete(self, key: str) -> None:
        async with self.sessions.begin() as db:
            await db.execute(
                update(SkillObjectDeletionRecord)
                .where(SkillObjectDeletionRecord.archive_key == key)
                .values(last_attempt_at=time.time_ns())
            )

    async def acknowledge_delete(self, key: str) -> None:
        async with self.sessions.begin() as db:
            await db.execute(
                delete(SkillObjectDeletionRecord).where(
                    SkillObjectDeletionRecord.archive_key == key
                )
            )
