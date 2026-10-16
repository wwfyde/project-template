"""Validate credentials, relational constraints and password-reset races."""

import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import bcrypt
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from api.auth import passwords
from api.auth.passwords import (
    PasswordRepository,
    PasswordUserExists,
    PasswordUserNotFound,
    normalize_username,
    validate_new_password,
)
from api.models.user import PasswordCredential, User, UserIdentity

PASSWORD = "my-test-password"
NEW_PASSWORD = "my-new-password"


class DatabaseFactory:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncSession]:
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            database = MagicMock(spec=AsyncSession)
            database.execute = AsyncMock(side_effect=session.execute)
            database.flush = AsyncMock(side_effect=session.flush)
            database.add = session.add
            yield cast(AsyncSession, database)


@pytest.fixture
def database() -> Iterator[Engine]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for model in (User, UserIdentity, PasswordCredential):
            model.__table__.create(connection)
    yield engine
    engine.dispose()


@pytest.fixture
def repository(database: Engine) -> PasswordRepository:
    return PasswordRepository(
        cast(async_sessionmaker[AsyncSession], DatabaseFactory(database))
    )


async def create_user(repository: PasswordRepository, username: str = "alice") -> User:
    return await repository.create_user(
        username, PASSWORD, display_name="Alice", tenant_id="tenant-a"
    )


@pytest.mark.parametrize(
    "username", ["ab", "a" * 65, "张三abc", "a b", "a\nb", "Kelvin", "\u00a0alice"]
)
def test_invalid_username(username: str) -> None:
    with pytest.raises(ValueError, match="Username"):
        normalize_username(username)


def test_username_normalization() -> None:
    assert normalize_username("  Alice.Example@ACME-Test_1  ") == (
        "alice.example@acme-test_1"
    )


@pytest.mark.parametrize("password", ["", "short", "a" * 1025, "\ud800" * 12])
def test_new_password_limits(password: str) -> None:
    with pytest.raises(ValueError, match="Password"):
        validate_new_password(password)


def test_new_password_preserves_spaces_and_accepts_unicode() -> None:
    assert validate_new_password("  spaced password  ") == "  spaced password  "
    assert validate_new_password("🔐" * 1024) == "🔐" * 1024


@pytest.mark.asyncio
async def test_create_and_authenticate_stable_normalized_identity(
    repository: PasswordRepository, database: Engine
) -> None:
    user = await create_user(repository, " ALICE ")
    authenticated = await repository.authenticate(" Alice ", PASSWORD)
    assert authenticated is not None
    assert authenticated.id == user.id
    assert authenticated.tenant_id == "tenant-a"
    assert authenticated.auth_version == 1
    with Session(database) as db:
        credential = db.get(PasswordCredential, user.id)
        assert credential.username == "alice"
        assert credential.hashed_password.startswith("$argon2id$")
        assert PASSWORD not in credential.hashed_password
        identity = db.scalars(select(UserIdentity)).one()
        assert (identity.user_id, identity.provider, identity.subject) == (
            user.id,
            "password",
            "alice",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("tenant_id", ["", "a" * 65, "tenant a", "租户", "tenant\n"])
async def test_create_rejects_invalid_tenant_without_persisting_user(
    repository: PasswordRepository, database: Engine, tenant_id: str
) -> None:
    with pytest.raises(ValueError, match="Tenant ID"):
        await repository.create_user(
            "alice", PASSWORD, display_name="Alice", tenant_id=tenant_id
        )
    with Session(database) as db:
        assert not db.scalars(select(User)).all()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name", ["", "   ", "a" * 256, "Alice\n", "A\u0085B", "\ud800"]
)
async def test_create_rejects_invalid_display_name_without_persisting_user(
    repository: PasswordRepository, database: Engine, name: str
) -> None:
    with pytest.raises(ValueError, match="Display name"):
        await repository.create_user(
            "alice", PASSWORD, display_name=name, tenant_id="tenant-a"
        )
    with Session(database) as db:
        assert not db.scalars(select(User)).all()


@pytest.mark.asyncio
async def test_create_trims_display_name_and_accepts_tenant_boundaries(
    repository: PasswordRepository,
) -> None:
    tenant_id = "Acme_" + "1" * 58 + "-"
    user = await repository.create_user(
        "alice", PASSWORD, display_name="  测试用户  ", tenant_id=tenant_id
    )
    assert user.display_name == "测试用户"
    assert user.tenant_id == tenant_id


@pytest.mark.asyncio
async def test_duplicate_username_rolls_back_all_new_rows(
    repository: PasswordRepository, database: Engine
) -> None:
    user = await create_user(repository)
    with pytest.raises(PasswordUserExists):
        await create_user(repository, " ALICE ")
    with Session(database) as db:
        assert [item.id for item in db.scalars(select(User)).all()] == [user.id]
        assert len(db.scalars(select(UserIdentity)).all()) == 1
        assert len(db.scalars(select(PasswordCredential)).all()) == 1


@pytest.mark.asyncio
async def test_failures_do_not_create_users_and_disabled_is_rejected(
    repository: PasswordRepository, database: Engine
) -> None:
    assert await repository.authenticate("missing", PASSWORD) is None
    user = await create_user(repository)
    assert await repository.authenticate("alice", "wrong") is None
    assert await repository.authenticate("alice", "") is None
    assert await repository.authenticate("alice", "x" * 1025) is None
    assert await repository.authenticate("a", PASSWORD) is None
    with Session(database) as db, db.begin():
        db.get(User, user.id).is_active = False
    assert await repository.authenticate("alice", PASSWORD) is None
    with Session(database) as db:
        assert len(db.scalars(select(User)).all()) == 1


@pytest.mark.asyncio
async def test_missing_password_identity_cannot_authenticate(
    repository: PasswordRepository, database: Engine
) -> None:
    await create_user(repository)
    with Session(database) as db, db.begin():
        identity = db.scalars(select(UserIdentity)).one()
        identity.provider = "google"
    assert await repository.authenticate("alice", PASSWORD) is None


@pytest.mark.asyncio
async def test_missing_accounts_still_verify_in_worker_thread(
    repository: PasswordRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    current_thread = threading.get_ident()
    calls: list[tuple[int, str]] = []
    original = passwords._verify_password

    def track(password: str, hashed_password: str) -> tuple[bool, str | None]:
        calls.append((threading.get_ident(), hashed_password))
        return original(password, hashed_password)

    monkeypatch.setattr(passwords, "_verify_password", track)
    assert await repository.authenticate("missing", PASSWORD) is None
    assert len(calls) == 1
    assert calls[0][0] != current_thread
    assert calls[0][1] == passwords._DUMMY_HASH


@pytest.mark.asyncio
async def test_bcrypt_credentials_upgrade_without_changing_user_or_version(
    repository: PasswordRepository, database: Engine
) -> None:
    user = await create_user(repository)
    legacy_password = "short"
    with Session(database) as db, db.begin():
        db.get(PasswordCredential, user.id).hashed_password = bcrypt.hashpw(
            legacy_password.encode(), bcrypt.gensalt(rounds=4)
        ).decode()
    result = await repository.authenticate("alice", legacy_password)
    assert result is not None
    assert (result.id, result.auth_version) == (user.id, 1)
    with Session(database) as db:
        assert db.get(PasswordCredential, user.id).hashed_password.startswith(
            "$argon2id$"
        )
    assert (await repository.authenticate("alice", legacy_password)).id == user.id


@pytest.mark.asyncio
async def test_bcrypt_never_truncates_overlong_utf8_password(
    repository: PasswordRepository, database: Engine
) -> None:
    user = await create_user(repository)
    legacy_password = "🔐" * 18  # Exactly 72 bytes, despite being 18 characters.
    hashed = bcrypt.hashpw(legacy_password.encode(), bcrypt.gensalt(rounds=4)).decode()
    with Session(database) as db, db.begin():
        db.get(PasswordCredential, user.id).hashed_password = hashed
    assert await repository.authenticate("alice", legacy_password + "suffix") is None
    with Session(database) as db:
        assert db.get(PasswordCredential, user.id).hashed_password == hashed
    assert (await repository.authenticate("alice", legacy_password)).id == user.id


@pytest.mark.asyncio
@pytest.mark.parametrize("hashed", ["corrupt", "$2b$12$broken", "$argon2id$broken"])
async def test_corrupt_hash_is_an_authentication_failure(
    repository: PasswordRepository, database: Engine, hashed: str
) -> None:
    user = await create_user(repository)
    with Session(database) as db, db.begin():
        db.get(PasswordCredential, user.id).hashed_password = hashed
    assert await repository.authenticate("alice", PASSWORD) is None


@pytest.mark.asyncio
async def test_reset_invalidates_old_versions_and_uses_normalized_username(
    repository: PasswordRepository, database: Engine
) -> None:
    user = await create_user(repository)
    await repository.set_password(" ALICE ", NEW_PASSWORD)
    assert await repository.authenticate("alice", PASSWORD) is None
    current = await repository.authenticate("alice", NEW_PASSWORD)
    assert current is not None
    assert (current.id, current.auth_version) == (user.id, 2)
    await repository.set_password("alice", NEW_PASSWORD)
    with Session(database) as db:
        assert db.get(User, user.id).auth_version == 3
    with pytest.raises(PasswordUserNotFound):
        await repository.set_password("missing", NEW_PASSWORD)


@pytest.mark.asyncio
async def test_password_reset_during_verify_does_not_authorize_old_password(
    repository: PasswordRepository,
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(repository)
    original = passwords.run_in_threadpool
    reset = False

    async def interleave(func: Callable[..., object], *args: object) -> object:
        nonlocal reset
        result = await original(func, *args)
        if func is passwords._verify_password and not reset:
            reset = True
            await repository.set_password("alice", NEW_PASSWORD)
        return result

    monkeypatch.setattr(passwords, "run_in_threadpool", interleave)
    assert await repository.authenticate("alice", PASSWORD) is None
    with Session(database) as db:
        assert db.get(User, user.id).auth_version == 2
    assert (await repository.authenticate("alice", NEW_PASSWORD)).id == user.id


@pytest.mark.asyncio
async def test_legacy_upgrade_does_not_overwrite_concurrent_reset(
    repository: PasswordRepository,
    database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await create_user(repository)
    with Session(database) as db, db.begin():
        db.get(PasswordCredential, user.id).hashed_password = bcrypt.hashpw(
            PASSWORD.encode(), bcrypt.gensalt(rounds=4)
        ).decode()
    original = passwords.run_in_threadpool
    reset = False

    async def interleave(func: Callable[..., object], *args: object) -> object:
        nonlocal reset
        result = await original(func, *args)
        if func is passwords._verify_password and not reset:
            upgraded_hash = cast(tuple[bool, str | None], result)[1]
            assert upgraded_hash is not None and upgraded_hash.startswith("$argon2id$")
            reset = True
            await repository.set_password("alice", NEW_PASSWORD)
        return result

    monkeypatch.setattr(passwords, "run_in_threadpool", interleave)
    assert await repository.authenticate("alice", PASSWORD) is None
    current = await repository.authenticate("alice", NEW_PASSWORD)
    assert current is not None
    assert (current.id, current.auth_version) == (user.id, 2)


def test_password_migration_upgrade_and_downgrade() -> None:
    path = (
        Path(__file__).parents[1]
        / "alembic/versions/da72e4b18c09_password_credentials.py"
    )
    spec = spec_from_file_location("password_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            User.__table__.create(connection)
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            inspector = inspect(connection)
            assert inspector.get_unique_constraints("auth_password_credential")[0][
                "column_names"
            ] == ["username"]
            foreign_key = inspector.get_foreign_keys("auth_password_credential")[0]
            assert foreign_key["referred_table"] == "auth_user"
            assert foreign_key["options"]["ondelete"] == "CASCADE"
            assert module.down_revision == "c36f109ab672"
            module.downgrade()
            assert inspect(connection).get_table_names() == ["auth_user"]
    finally:
        engine.dispose()
