"""Exercise actual relational constraints/transactions without external services."""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import Engine, create_engine, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from api.auth.schemas import ProviderIdentity
from api.auth.users import PostgresUserRepository, public_user
from api.models.user import ResourceOwner, User, UserIdentity


class DatabaseFactory:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncSession]:
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            database = MagicMock(spec=AsyncSession)
            database.execute = AsyncMock(side_effect=session.execute)
            database.get = AsyncMock(side_effect=session.get)
            database.flush = AsyncMock(side_effect=session.flush)
            database.add = session.add
            yield cast(AsyncSession, database)


@pytest.fixture
def database() -> Iterator[Engine]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for model in (User, UserIdentity, ResourceOwner):
            model.__table__.create(connection)
    yield engine
    engine.dispose()


@pytest.fixture
def users(database: Engine) -> PostgresUserRepository:
    return PostgresUserRepository(
        cast(async_sessionmaker[AsyncSession], DatabaseFactory(database))
    )


def identity(subject: str, provider: str = "google") -> ProviderIdentity:
    return ProviderIdentity(
        provider=provider,
        subject=subject,
        display_name="测试用户",
        email="shared@example.com",
    )


@pytest.mark.asyncio
async def test_identity_is_stable_and_email_does_not_link_accounts(
    users: PostgresUserRepository,
) -> None:
    first = await users.resolve(
        identity("one"), tenant_id="tenant-a", allow_signup=True
    )
    same = await users.resolve(
        identity("one"), tenant_id="changed-default", allow_signup=False
    )
    other = await users.resolve(
        identity("two"), tenant_id="tenant-a", allow_signup=True
    )
    other_provider = await users.resolve(
        identity("one", "dingtalk"), tenant_id="tenant-a", allow_signup=True
    )
    assert first.id == same.id
    assert same.tenant_id == "tenant-a"
    assert len({first.id, other.id, other_provider.id}) == 3
    assert await users.get(first.id, "dingtalk") is None
    assert (await users.get(first.id, "google")).id == first.id


@pytest.mark.asyncio
async def test_disabled_user_and_closed_signup(
    users: PostgresUserRepository, database: Engine
) -> None:
    with pytest.raises(HTTPException) as error:
        await users.resolve(identity("new"), tenant_id="tenant-a", allow_signup=False)
    assert error.value.status_code == 403
    user = await users.resolve(
        identity("existing"), tenant_id="tenant-a", allow_signup=True
    )
    with Session(database) as session, session.begin():
        session.get(User, user.id).is_active = False
    with pytest.raises(HTTPException) as error:
        await users.resolve(
            identity("existing"), tenant_id="tenant-a", allow_signup=True
        )
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_resource_ownership_scopes_user_tenant_and_resource_kind(
    users: PostgresUserRepository,
) -> None:
    first = public_user(
        await users.resolve(identity("one"), tenant_id="tenant-a", allow_signup=True),
        "google",
    )
    second = public_user(
        await users.resolve(identity("two"), tenant_id="tenant-a", allow_signup=True),
        "google",
    )
    await users.own("conversation", "resource-1", first)
    assert await users.owns("conversation", "resource-1", first)
    assert not await users.owns("conversation", "resource-1", second)
    assert not await users.owns("agent_session", "resource-1", first)
    assert not await users.owns("conversation", "legacy-resource", first)
    assert not await users.owns(
        "conversation", "resource-1", first.model_copy(update={"tenant_id": "other"})
    )
    assert await users.owned_ids("conversation", first) == {"resource-1"}
    assert await users.owned_ids("conversation", second) == set()


@pytest.mark.asyncio
async def test_signup_rolls_back_user_if_identity_insert_fails(
    users: PostgresUserRepository, database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = identity("one")
    # Invalid provider subject fails the DB NOT NULL constraint after user flush.
    monkeypatch.setattr(original, "subject", None)
    with pytest.raises(Exception):
        await users.resolve(original, tenant_id="tenant-a", allow_signup=True)
    with Session(database) as session:
        assert not session.scalars(select(User)).all()
        assert not session.scalars(select(UserIdentity)).all()


def test_migration_upgrade_and_downgrade() -> None:
    path = Path(__file__).parents[1] / "alembic/versions/c36f109ab672_auth_users.py"
    spec = spec_from_file_location("auth_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            inspector = inspect(connection)
            assert set(inspector.get_table_names()) == {
                "auth_user",
                "auth_identity",
                "auth_resource_owner",
            }
            assert inspector.get_unique_constraints("auth_identity")[0][
                "column_names"
            ] == ["provider", "subject"]
            assert module.down_revision == "8d50b113df31"
            module.downgrade()
            assert inspect(connection).get_table_names() == []
    finally:
        engine.dispose()
