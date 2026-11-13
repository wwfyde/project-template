"""Exercise real metadata transactions and failed object-store coordination."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import cast
from unittest.mock import AsyncMock

import pytest
from api.skills.bundles import SkillBundle, bundle_from_files
from api.skills.contracts import Skill, SkillFailure
from api.skills.service import SkillService
from api.skills.store import PostgresSkillStore
from sqlalchemy import Table, create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import StaticPool
from test_skill_store import OWNER, TABLES, SqliteSessionFactory


class FakeObjects:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.gets: list[str] = []
        self.deletes: list[str] = []
        self.fail_delete = False
        self.failed_keys: set[str] = set()
        self.fail_put_after_write = False

    async def put(self, key: str, content: bytes) -> None:
        self.puts.append(key)
        self.data[key] = content
        if self.fail_put_after_write:
            raise SkillFailure("object_storage_unavailable", "Upload acknowledgement lost.", 503)

    async def get(self, key: str) -> bytes:
        self.gets.append(key)
        if key not in self.data:
            raise SkillFailure("object_storage_unavailable", "Object unavailable.", 503)
        return self.data[key]

    async def delete(self, key: str) -> None:
        self.deletes.append(key)
        if self.fail_delete or key in self.failed_keys:
            raise SkillFailure("object_storage_unavailable", "Temporary deletion failure.", 503)
        self.data.pop(key, None)


@dataclass
class SkillEnvironment:
    sessions: SqliteSessionFactory
    store: PostgresSkillStore
    objects: FakeObjects
    service: SkillService


@pytest.fixture
def skill_env() -> Iterator[SkillEnvironment]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    for table in TABLES:
        cast(Table, table).create(engine)
    sessions = SqliteSessionFactory(engine)
    store = PostgresSkillStore(cast(async_sessionmaker[AsyncSession], sessions))
    objects = FakeObjects()
    try:
        yield SkillEnvironment(sessions, store, objects, SkillService(store, objects))
    finally:
        engine.dispose()


def sample_bundle(
    name: str = "report-helper", extra: list[tuple[str, bytes]] | None = None
) -> SkillBundle:
    manifest = f"---\nname: {name}\ndescription: Generate a report.\n---\nRead references.\n"
    return bundle_from_files([("report-helper/SKILL.md", manifest.encode()), *(extra or [])])


@pytest.mark.asyncio
async def test_failed_database_commit_compensates_uploaded_object(
    skill_env: SkillEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = skill_env.store.create

    async def fail_once(*args: object, **kwargs: object) -> Skill:
        skill_env.sessions.fail_commit = True
        try:
            return await original(*args, **kwargs)
        finally:
            skill_env.sessions.fail_commit = False

    monkeypatch.setattr(skill_env.store, "create", fail_once)
    with pytest.raises(RuntimeError, match="commit failure"):
        await skill_env.service.create(OWNER, sample_bundle())
    assert skill_env.objects.puts == skill_env.objects.deletes
    assert not skill_env.objects.data
    assert not (await skill_env.store.list_skills(OWNER)).data
    assert await skill_env.store.pending_deletes() == []


@pytest.mark.asyncio
async def test_lost_upload_acknowledgement_and_failed_cleanup_are_durably_retried(
    skill_env: SkillEnvironment,
) -> None:
    skill_env.objects.fail_put_after_write = True
    skill_env.objects.fail_delete = True
    with pytest.raises(SkillFailure, match="acknowledgement lost"):
        await skill_env.service.create(OWNER, sample_bundle())
    assert await skill_env.store.pending_deletes() == skill_env.objects.puts
    assert skill_env.objects.data
    assert not (await skill_env.store.list_skills(OWNER)).data

    skill_env.objects.fail_delete = False
    restarted = SkillService(skill_env.store, skill_env.objects)
    await restarted.cleanup()
    assert not skill_env.objects.data
    assert await skill_env.store.pending_deletes() == []


@pytest.mark.asyncio
async def test_failed_object_deletion_does_not_restore_revoked_metadata(
    skill_env: SkillEnvironment,
) -> None:
    skill = await skill_env.service.create(OWNER, sample_bundle())
    await skill_env.service.create_version(OWNER, skill.id, sample_bundle("new-version"))
    skill_env.objects.fail_delete = True
    await skill_env.service.delete_skill(OWNER, skill.id)
    await skill_env.service.cleanup()
    with pytest.raises(SkillFailure) as error:
        await skill_env.store.get_skill(OWNER, skill.id)
    assert error.value.status == 404
    assert len(await skill_env.store.pending_deletes()) == 2
    assert len(skill_env.objects.data) == 2

    skill_env.objects.fail_delete = False
    await SkillService(skill_env.store, skill_env.objects).cleanup()
    assert not skill_env.objects.data
    assert await skill_env.store.pending_deletes() == []


@pytest.mark.asyncio
async def test_continuously_failed_cleanup_batch_does_not_starve_later_objects(
    skill_env: SkillEnvironment,
) -> None:
    keys = [f"object-{number:03}.zip" for number in range(101)]
    skill_env.objects.failed_keys = set(keys[:100])
    for key in keys:
        skill_env.objects.data[key] = b"obsolete archive"
        await skill_env.store.queue_delete(key)
    await skill_env.service.cleanup()
    assert keys[100] in skill_env.objects.data
    await skill_env.service.cleanup()
    assert keys[100] not in skill_env.objects.data
    assert len(skill_env.objects.data) == 100
    assert set(await skill_env.store.pending_deletes()) == skill_env.objects.failed_keys


@pytest.mark.asyncio
async def test_uncertain_commit_acknowledgement_preserves_referenced_archive(
    skill_env: SkillEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = skill_env.store.create

    async def commit_then_fail(*args: object, **kwargs: object) -> Skill:
        await original(*args, **kwargs)
        raise RuntimeError("commit acknowledgement lost")

    monkeypatch.setattr(skill_env.store, "create", commit_then_fail)
    bundle = sample_bundle()
    with pytest.raises(RuntimeError, match="acknowledgement lost"):
        await skill_env.service.create(OWNER, bundle)
    skill = (await skill_env.store.list_skills(OWNER)).data[0]
    assert not skill_env.objects.deletes
    assert await skill_env.store.pending_deletes() == []
    content, version = await skill_env.service.content(OWNER, skill.id)
    assert content == bundle.archive and version.version == "1"
    await skill_env.service.delete_skill(OWNER, skill.id)
    await skill_env.service.cleanup()
    assert not skill_env.objects.data


@pytest.mark.asyncio
async def test_foreign_owner_and_missing_file_are_rejected_before_object_io(
    skill_env: SkillEnvironment,
) -> None:
    skill = await skill_env.service.create(OWNER, sample_bundle())
    with pytest.raises(SkillFailure) as error:
        await skill_env.service.create_version("another-owner", skill.id, sample_bundle())
    assert error.value.status == 404 and len(skill_env.objects.puts) == 1
    for path in ["report-helper/missing.md", "../outside"]:
        with pytest.raises(SkillFailure):
            await skill_env.service.file(OWNER, skill.id, path)
    assert not skill_env.objects.gets
    tree = await skill_env.service.tree(OWNER, skill.id)
    assert tree.file_count == 1 and not skill_env.objects.gets


@pytest.mark.asyncio
async def test_corrupt_or_replaced_archive_never_returns_unverified_preview(
    skill_env: SkillEnvironment,
) -> None:
    skill = await skill_env.service.create(OWNER, sample_bundle())
    key = skill_env.objects.puts[0]
    for invalid_content in [b"corrupt ZIP", sample_bundle("tampered-version").archive]:
        skill_env.objects.data[key] = invalid_content
        with pytest.raises(SkillFailure) as error:
            await skill_env.service.file(OWNER, skill.id, "report-helper/SKILL.md")
        assert (error.value.status, error.value.code) == (503, "skill_content_unavailable")


@pytest.mark.asyncio
async def test_failed_new_version_keeps_existing_default_and_cleans_only_new_object(
    skill_env: SkillEnvironment, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill = await skill_env.service.create(OWNER, sample_bundle())
    original_archive = dict(skill_env.objects.data)
    monkeypatch.setattr(
        skill_env.store, "create_version", AsyncMock(side_effect=RuntimeError("transaction failed"))
    )
    with pytest.raises(RuntimeError, match="transaction failed"):
        await skill_env.service.create_version(OWNER, skill.id, sample_bundle("new-version"), True)
    assert skill_env.objects.data == original_archive
    saved = await skill_env.store.get_skill(OWNER, skill.id)
    assert (saved.default_version, saved.latest_version, saved.name) == ("1", "1", "report-helper")
