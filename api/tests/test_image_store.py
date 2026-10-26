"""Image storage contracts against memory and transactional SQLite.

SQLite verifies serialization, constraints and rollback, not PostgreSQL locking.
"""

from collections.abc import AsyncGenerator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pytest import FixtureRequest
from sqlalchemy import Engine, Table, create_engine, delete, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from api.images.contracts import ImageAsset, ImageComment, ImageFailure, ImageStore
from api.images.store import InMemoryImageStore, PostgresImageStore
from api.models.image_asset import ImageAssetRecord, ImageCommentRecord

NOW = datetime(2026, 10, 23, tzinfo=UTC)
OWNER = "user:account-a:user-a"
OTHER_OWNER = "service:client-b"


class SqliteSessionFactory:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.fail_commit = False

    @asynccontextmanager
    async def begin(self) -> AsyncGenerator[AsyncSession]:
        with Session(self.engine) as session, session.begin():
            database = MagicMock(spec=AsyncSession)
            database.execute = AsyncMock(side_effect=session.execute)
            database.add = session.add
            yield cast(AsyncSession, database)
            if self.fail_commit:
                session.flush()
                raise RuntimeError("injected commit failure")


@pytest.fixture
def sqlite_factory() -> Iterator[SqliteSessionFactory]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    cast(Table, ImageAssetRecord.__table__).create(engine)
    cast(Table, ImageCommentRecord.__table__).create(engine)
    try:
        yield SqliteSessionFactory(engine)
    finally:
        engine.dispose()


@pytest.fixture(params=["memory", "database"])
def store(request: FixtureRequest, sqlite_factory: SqliteSessionFactory) -> ImageStore:
    if request.param == "memory":
        return InMemoryImageStore()
    return PostgresImageStore(cast(async_sessionmaker[AsyncSession], sqlite_factory))


def asset(identifier: str = "asset-a", seconds: int = 0) -> ImageAsset:
    return ImageAsset(
        id=identifier,
        filename="photo.png",
        width=10,
        height=20,
        created_at=NOW + timedelta(seconds=seconds),
    )


def comment(
    identifier: str = "comment-a", asset_id: str = "asset-a", seconds: int = 0
) -> ImageComment:
    return ImageComment(
        id=identifier,
        asset_id=asset_id,
        text="Move this title",
        x=0.25,
        y=0.75,
        created_at=NOW + timedelta(seconds=seconds),
    )


@pytest.mark.asyncio
async def test_assets_are_immutable_and_return_defensive_copies(
    store: ImageStore,
) -> None:
    original = asset()
    await store.create_asset(OWNER, original, b"private image bytes")
    original.filename = "caller-mutation.png"
    saved = await store.get_asset(OWNER, original.id)
    assert saved.filename == "photo.png"
    assert saved.created_at == NOW
    saved.filename = "read-mutation.png"
    assert (await store.get_asset(OWNER, original.id)).filename == "photo.png"
    assert await store.get_content(OWNER, original.id) == b"private image bytes"
    with pytest.raises(ImageFailure) as failure:
        await store.create_asset(OWNER, asset(), b"overwritten")
    assert failure.value.status == 409
    assert await store.get_content(OWNER, original.id) == b"private image bytes"


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_id", ["asset-a", "missing"])
async def test_foreign_and_missing_assets_have_identical_404s(
    store: ImageStore, asset_id: str
) -> None:
    await store.create_asset(OWNER, asset(), b"private")
    operations = (
        lambda: store.get_asset(OTHER_OWNER, asset_id),
        lambda: store.get_content(OTHER_OWNER, asset_id),
        lambda: store.list_comments(OTHER_OWNER, asset_id),
        lambda: store.add_comment(OTHER_OWNER, comment(asset_id=asset_id)),
        lambda: store.delete_comment(OTHER_OWNER, asset_id, "comment-a"),
    )
    for operation in operations:
        with pytest.raises(ImageFailure) as failure:
            await operation()
        assert (failure.value.status, failure.value.code, failure.value.message) == (
            404,
            "image_not_found",
            "Image resource not found.",
        )
    assert await store.list_assets(OTHER_OWNER, 50) == []


@pytest.mark.asyncio
async def test_foreign_asset_ids_and_parent_references_cannot_be_claimed(
    store: ImageStore,
) -> None:
    await store.create_asset(OWNER, asset(), b"private")
    with pytest.raises(ImageFailure) as duplicate:
        await store.create_asset(OTHER_OWNER, asset(), b"foreign replacement")
    assert duplicate.value.status == 404
    derived = asset("derived")
    derived.parent_id = "asset-a"
    with pytest.raises(ImageFailure) as parent:
        await store.create_asset(OTHER_OWNER, derived, b"derived")
    assert parent.value.status == 404
    assert await store.list_assets(OTHER_OWNER, 50) == []
    await store.create_asset(OWNER, derived, b"derived")
    assert (await store.get_asset(OWNER, "derived")).parent_id == "asset-a"


@pytest.mark.asyncio
async def test_asset_listing_is_owned_recent_first_and_bounded(
    store: ImageStore,
) -> None:
    for item in (asset("a", 1), asset("b", 1), asset("c", 2)):
        await store.create_asset(OWNER, item, item.id.encode())
    await store.create_asset(OTHER_OWNER, asset("foreign", 3), b"private")
    recent = await store.list_assets(OWNER, 2)
    assert [item.id for item in recent] == ["c", "b"]
    recent[0].filename = "mutation.png"
    assert (await store.get_asset(OWNER, "c")).filename == "photo.png"
    assert await store.list_assets(OWNER, 0) == []
    assert await store.list_assets(OWNER, -1) == []


@pytest.mark.asyncio
async def test_masks_stay_private_and_are_hidden_from_the_gallery(
    store: ImageStore,
) -> None:
    await store.create_asset(OWNER, asset(), b"image")
    mask = asset("mask", 1).model_copy(update={"purpose": "mask"})
    await store.create_asset(OWNER, mask, b"mask bytes")
    assert [item.id for item in await store.list_assets(OWNER, 1)] == ["asset-a"]
    assert (await store.get_asset(OWNER, "mask")).purpose == "mask"
    assert await store.get_content(OWNER, "mask") == b"mask bytes"
    with pytest.raises(ImageFailure) as failure:
        await store.get_content(OTHER_OWNER, "mask")
    assert failure.value.status == 404


@pytest.mark.asyncio
async def test_comments_are_ordered_copied_and_deleted_by_asset(
    store: ImageStore,
) -> None:
    await store.create_asset(OWNER, asset(), b"image")
    await store.create_asset(OWNER, asset("other-asset"), b"other")
    first = comment("b", seconds=1)
    await store.add_comment(OWNER, first)
    first.text = "caller mutation"
    await store.add_comment(OWNER, comment("a", seconds=1))
    await store.add_comment(OWNER, comment("early", seconds=0))
    comments = await store.list_comments(OWNER, "asset-a")
    assert [item.id for item in comments] == ["early", "a", "b"]
    assert comments[-1].text == "Move this title"
    comments[-1].text = "read mutation"
    assert (await store.list_comments(OWNER, "asset-a"))[-1].text == "Move this title"
    with pytest.raises(ImageFailure) as failure:
        await store.delete_comment(OWNER, "other-asset", "b")
    assert failure.value.status == 404
    await store.delete_comment(OWNER, "asset-a", "b")
    assert [item.id for item in await store.list_comments(OWNER, "asset-a")] == [
        "early",
        "a",
    ]
    with pytest.raises(ImageFailure) as missing:
        await store.delete_comment(OWNER, "asset-a", "b")
    assert missing.value.status == 404


@pytest.mark.asyncio
async def test_comment_id_collisions_do_not_cross_owner_or_asset(
    store: ImageStore,
) -> None:
    await store.create_asset(OWNER, asset(), b"image")
    await store.create_asset(OWNER, asset("same-owner"), b"image")
    await store.create_asset(OTHER_OWNER, asset("foreign"), b"image")
    await store.add_comment(OWNER, comment())
    with pytest.raises(ImageFailure) as duplicate:
        await store.add_comment(OWNER, comment())
    assert duplicate.value.status == 409
    for owner, image_id in ((OWNER, "same-owner"), (OTHER_OWNER, "foreign")):
        with pytest.raises(ImageFailure) as forbidden:
            await store.add_comment(owner, comment(asset_id=image_id))
        assert forbidden.value.status == 404
        assert await store.list_comments(owner, image_id) == []
    assert len(await store.list_comments(OWNER, "asset-a")) == 1


@pytest.mark.asyncio
async def test_database_rolls_back_asset_bytes_and_comments(
    sqlite_factory: SqliteSessionFactory,
) -> None:
    store = PostgresImageStore(cast(async_sessionmaker[AsyncSession], sqlite_factory))
    sqlite_factory.fail_commit = True
    with pytest.raises(RuntimeError, match="injected commit failure"):
        await store.create_asset(OWNER, asset(), b"never persisted")
    sqlite_factory.fail_commit = False
    assert await store.list_assets(OWNER, 20) == []
    await store.create_asset(OWNER, asset(), b"image")
    sqlite_factory.fail_commit = True
    with pytest.raises(RuntimeError, match="injected commit failure"):
        await store.add_comment(OWNER, comment())
    sqlite_factory.fail_commit = False
    assert await store.list_comments(OWNER, "asset-a") == []
    await store.add_comment(OWNER, comment())
    sqlite_factory.fail_commit = True
    with pytest.raises(RuntimeError, match="injected commit failure"):
        await store.delete_comment(OWNER, "asset-a", "comment-a")
    sqlite_factory.fail_commit = False
    assert len(await store.list_comments(OWNER, "asset-a")) == 1


@pytest.mark.asyncio
async def test_database_comment_foreign_key_cascades(
    sqlite_factory: SqliteSessionFactory,
) -> None:
    store = PostgresImageStore(cast(async_sessionmaker[AsyncSession], sqlite_factory))
    await store.create_asset(OWNER, asset(), b"image")
    await store.add_comment(OWNER, comment())
    with Session(sqlite_factory.engine) as db, db.begin():
        db.execute(delete(ImageAssetRecord).where(ImageAssetRecord.id == "asset-a"))
        assert db.execute(select(ImageCommentRecord)).scalars().all() == []


def test_postgres_ddl_uses_private_bytes_jsonb_and_comment_cascade() -> None:
    ddl = {
        model.__tablename__: str(
            CreateTable(cast(Table, model.__table__)).compile(
                dialect=postgresql.dialect()
            )
        )
        for model in (ImageAssetRecord, ImageCommentRecord)
    }
    assert "content BYTEA NOT NULL" in ddl["image_asset"]
    assert all("document JSONB NOT NULL" in value for value in ddl.values())
    assert all("TIMESTAMP WITH TIME ZONE" in value for value in ddl.values())
    assert "ON DELETE CASCADE" in ddl["image_comment"]


def test_migration_round_trip_matches_models_and_current_head() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/f31a78c4d6e2_image_assets.py"
    spec = spec_from_file_location("image_assets_migration", path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "e28b47a1d902"
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                inspector = inspect(connection)
                assert set(inspector.get_table_names()) == {
                    "image_asset",
                    "image_comment",
                }
                for model in (ImageAssetRecord, ImageCommentRecord):
                    assert {
                        column["name"]
                        for column in inspector.get_columns(model.__tablename__)
                    } == set(model.__table__.columns.keys())
                    assert {
                        index["name"]
                        for index in inspector.get_indexes(model.__tablename__)
                    } == {index.name for index in model.__table__.indexes}
                migration.downgrade()
                assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
