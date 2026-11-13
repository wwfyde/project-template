"""Persistence, pagination, ownership and rollback on real SQL tables.

SQLite exercises transactions and constraints; PostgreSQL lock SQL is checked separately.
"""

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from api.models.skill import SkillObjectDeletionRecord, SkillRecord, SkillVersionRecord
from api.skills.contracts import SkillFailure, SkillFile
from api.skills.store import PostgresSkillStore
from sqlalchemy import Engine, Table, create_engine, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

OWNER = "user:account-a:user-a"
OTHER_OWNER = "user:account-b:user-a"
FILES = [SkillFile(path="SKILL.md", size=24, media_type="text/markdown", sha256="a" * 64)]
TABLES = [SkillRecord.__table__, SkillVersionRecord.__table__, SkillObjectDeletionRecord.__table__]


class SqliteSessionFactory:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.fail_commit = False
        self.queries: list[object] = []

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[AsyncSession]:
        with Session(self.engine) as session, session.begin():
            database = MagicMock(spec=AsyncSession)

            def execute(query: object) -> object:
                self.queries.append(query)
                return session.execute(query)

            database.execute = AsyncMock(side_effect=execute)
            database.add = session.add
            database.flush = AsyncMock(side_effect=session.flush)
            yield cast(AsyncSession, database)
            if self.fail_commit:
                session.flush()
                raise RuntimeError("injected commit failure")


@pytest.fixture
def sessions() -> Iterator[SqliteSessionFactory]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    for table in TABLES:
        cast(Table, table).create(engine)
    try:
        yield SqliteSessionFactory(engine)
    finally:
        engine.dispose()


@pytest.fixture
def store(sessions: SqliteSessionFactory) -> PostgresSkillStore:
    return PostgresSkillStore(cast(async_sessionmaker[AsyncSession], sessions))


async def create(
    store: PostgresSkillStore, skill_id: str = "skill_a", created_at: int = 100
) -> None:
    await store.create(
        OWNER,
        skill_id,
        f"{skill_id}_v1",
        created_at,
        "first",
        "First version",
        f"{skill_id}/v1.zip",
        FILES,
    )


async def add(store: PostgresSkillStore, number: int, *, default: bool = False) -> None:
    await store.create_version(
        OWNER,
        "skill_a",
        f"skill_a_v{number}",
        100 + number,
        f"version-{number}",
        f"Description {number}",
        f"skill_a/v{number}.zip",
        FILES,
        make_default=default,
    )


@pytest.mark.asyncio
async def test_default_metadata_content_and_versions_are_independent(
    store: PostgresSkillStore,
) -> None:
    await create(store)
    await add(store, 2)
    skill = await store.get_skill(OWNER, "skill_a")
    assert (skill.name, skill.default_version, skill.latest_version) == ("first", "1", "2")
    assert (await store.get_version(OWNER, "skill_a")).archive_key == "skill_a/v1.zip"
    assert (await store.get_version(OWNER, "skill_a", "latest")).version.version == "2"
    skill = await store.set_default(OWNER, "skill_a", "2")
    assert (skill.name, skill.description, skill.default_version) == (
        "version-2",
        "Description 2",
        "2",
    )
    first = await store.get_version(OWNER, "skill_a", "1")
    assert first.version.name == "first"
    first.files[0].path = "mutated"
    assert (await store.get_version(OWNER, "skill_a", "1")).files[0].path == "SKILL.md"
    await add(store, 3, default=True)
    assert (await store.get_skill(OWNER, "skill_a")).default_version == "3"


@pytest.mark.asyncio
async def test_owner_is_required_on_every_lookup_and_mutation(store: PostgresSkillStore) -> None:
    await create(store)
    await add(store, 2)
    operations = [
        lambda: store.get_skill(OTHER_OWNER, "skill_a"),
        lambda: store.get_version(OTHER_OWNER, "skill_a", "1"),
        lambda: store.list_versions(OTHER_OWNER, "skill_a"),
        lambda: store.list_skills(OTHER_OWNER, after="skill_a"),
        lambda: store.set_default(OTHER_OWNER, "skill_a", "2"),
        lambda: store.delete_version(OTHER_OWNER, "skill_a", "2"),
        lambda: store.delete_skill(OTHER_OWNER, "skill_a"),
        lambda: store.create_version(
            OTHER_OWNER,
            "skill_a",
            "foreign",
            200,
            "foreign",
            "Foreign",
            "foreign.zip",
            FILES,
        ),
    ]
    for operation in operations:
        with pytest.raises(SkillFailure) as error:
            await operation()
        assert (error.value.status, error.value.code) == (404, "skill_not_found")
    assert not (await store.list_skills(OTHER_OWNER)).data
    assert (await store.get_skill(OWNER, "skill_a")).latest_version == "2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "order,expected",
    [("asc", ["skill_a", "skill_b", "skill_c"]), ("desc", ["skill_c", "skill_b", "skill_a"])],
)
async def test_timestamp_cursor_is_stable_when_timestamps_tie(
    store: PostgresSkillStore,
    order: str,
    expected: list[str],
) -> None:
    for skill_id in ["skill_b", "skill_c", "skill_a"]:
        await create(store, skill_id)
    first = await store.list_skills(OWNER, limit=2, order=order)
    assert [skill.id for skill in first.data] == expected[:2]
    assert first.first_id == expected[0] and first.last_id == expected[1] and first.has_more
    second = await store.list_skills(OWNER, after=first.last_id, limit=2, order=order)
    assert [skill.id for skill in second.data] == expected[2:]
    assert not second.has_more
    empty = await store.list_skills(OWNER, limit=0)
    assert empty.data == [] and empty.first_id is None and empty.last_id is None and empty.has_more


@pytest.mark.asyncio
async def test_version_pagination_is_numeric_and_cursor_is_version_id(
    store: PostgresSkillStore,
) -> None:
    await create(store)
    for number in range(2, 13):
        await add(store, number)
    page = await store.list_versions(OWNER, "skill_a", limit=3)
    assert [version.version for version in page.data] == ["12", "11", "10"]
    assert page.has_more and page.last_id == "skill_a_v10"
    page = await store.list_versions(OWNER, "skill_a", after=page.last_id, limit=2)
    assert [version.version for version in page.data] == ["9", "8"]
    page = await store.list_versions(OWNER, "skill_a", order="asc", limit=2)
    assert [version.version for version in page.data] == ["1", "2"]
    await create(store, "skill_b")
    with pytest.raises(SkillFailure) as error:
        await store.list_versions(OWNER, "skill_a", after="skill_b_v1")
    assert (error.value.status, error.value.code) == (400, "invalid_cursor")
    await store.create(
        OTHER_OWNER,
        "skill_foreign",
        "skill_foreign_v1",
        100,
        "foreign",
        "Foreign",
        "skill_foreign/v1.zip",
        FILES,
    )
    for cursor in ["missing-version", "skill_foreign_v1"]:
        with pytest.raises(SkillFailure) as error:
            await store.list_versions(OWNER, "skill_a", after=cursor)
        assert (error.value.status, error.value.code) == (404, "skill_not_found")


@pytest.mark.asyncio
async def test_delete_rules_and_version_numbers_are_never_reused(store: PostgresSkillStore) -> None:
    await create(store)
    await add(store, 2)
    with pytest.raises(SkillFailure) as error:
        await store.delete_version(OWNER, "skill_a", "1")
    assert error.value.status == 400
    assert await store.pending_deletes() == []
    deleted = await store.delete_version(OWNER, "skill_a", "2")
    assert deleted.model_dump() == {
        "id": "skill_a_v2",
        "object": "skill.version.deleted",
        "deleted": True,
        "version": "2",
    }
    assert (await store.get_skill(OWNER, "skill_a")).latest_version == "1"
    await add(store, 3)
    assert (await store.get_skill(OWNER, "skill_a")).latest_version == "3"
    await store.delete_version(OWNER, "skill_a", "3")
    await store.delete_version(OWNER, "skill_a", "1")
    with pytest.raises(SkillFailure):
        await store.get_skill(OWNER, "skill_a")
    assert await store.pending_deletes() == ["skill_a/v1.zip", "skill_a/v2.zip", "skill_a/v3.zip"]


@pytest.mark.asyncio
async def test_cascade_delete_and_idempotent_outbox(
    store: PostgresSkillStore, sessions: SqliteSessionFactory
) -> None:
    await create(store)
    await add(store, 2)
    await store.queue_delete("skill_a/v1.zip")
    await store.queue_delete("skill_a/v1.zip")
    # A failed commit acknowledgement must not cause a still-referenced object to be removed.
    assert await store.pending_deletes() == []
    deleted = await store.delete_skill(OWNER, "skill_a")
    assert deleted.deleted is True
    assert await store.pending_deletes() == ["skill_a/v1.zip", "skill_a/v2.zip"]
    with Session(sessions.engine) as db:
        assert db.scalars(select(SkillVersionRecord)).all() == []
    await store.acknowledge_delete("skill_a/v1.zip")
    await store.acknowledge_delete("skill_a/v1.zip")
    assert await store.pending_deletes(limit=1) == ["skill_a/v2.zip"]


@pytest.mark.asyncio
async def test_failed_transactions_keep_pointers_and_deletion_outbox_atomic(
    store: PostgresSkillStore,
    sessions: SqliteSessionFactory,
) -> None:
    await create(store)
    sessions.fail_commit = True
    with pytest.raises(RuntimeError, match="commit failure"):
        await add(store, 2, default=True)
    sessions.fail_commit = False
    assert (await store.get_skill(OWNER, "skill_a")).latest_version == "1"
    await add(store, 2)
    sessions.fail_commit = True
    with pytest.raises(RuntimeError, match="commit failure"):
        await store.delete_skill(OWNER, "skill_a")
    sessions.fail_commit = False
    assert (await store.get_skill(OWNER, "skill_a")).latest_version == "2"
    assert await store.pending_deletes() == []


@pytest.mark.asyncio
async def test_failed_deletions_move_behind_unattempted_work(store: PostgresSkillStore) -> None:
    keys = [f"skills/{number:03}.zip" for number in range(101)]
    for key in keys:
        await store.queue_delete(key)
    first = await store.pending_deletes()
    assert first == keys[:100]
    for key in first:
        await store.defer_delete(key)
    second = await store.pending_deletes()
    assert second[0] == keys[100]
    await store.acknowledge_delete(second[0])
    assert len(await store.pending_deletes()) == 100
    # A repeated enqueue cannot reset the failed key's place in the queue.
    await store.queue_delete(keys[99])
    assert (await store.pending_deletes())[-1] == keys[99]
    # Concurrent workers may already have acknowledged a failing worker's key.
    await store.defer_delete("already-removed.zip")


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["latest", "0", "01", "-1", "1.0", "１２", "999999999999999"])
async def test_mutations_require_a_concrete_canonical_version(
    store: PostgresSkillStore, version: str
) -> None:
    await create(store)
    for mutation in [store.set_default, store.delete_version]:
        with pytest.raises(SkillFailure) as error:
            await mutation(OWNER, "skill_a", version)
        assert error.value.status == 400


@pytest.mark.asyncio
async def test_postgres_mutations_lock_the_parent_before_allocating_or_deleting(
    store: PostgresSkillStore,
    sessions: SqliteSessionFactory,
) -> None:
    await create(store)
    sessions.queries.clear()
    await add(store, 2)
    sql = str(sessions.queries[0].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql and "skill.owner" in sql
    sessions.queries.clear()
    await store.get_version(OWNER, "skill_a")
    sql = str(sessions.queries[0].compile(dialect=postgresql.dialect()))
    assert "FOR SHARE" in sql


def test_migration_round_trip_matches_model_columns() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/a42e9c71b603_skills.py"
    spec = spec_from_file_location("skills_migration", path)
    assert spec and spec.loader
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                inspector = inspect(connection)
                assert set(inspector.get_table_names()) == {
                    "skill",
                    "skill_version",
                    "skill_object_deletion",
                }
                for table in TABLES:
                    assert {column["name"] for column in inspector.get_columns(table.name)} == set(
                        table.columns.keys()
                    )
                migration.downgrade()
                assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
