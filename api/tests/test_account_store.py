"""Real transactions cover identity ownership and account mutation races."""

import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from api.repositories import user_security as store
from api.repositories.user_security import AccountError, AccountStore
from api.repositories.password import PasswordRepository
from api.schemas.auth import ProviderIdentity
from api.models import Account, AccountMember, PasswordCredential, User, UserIdentity

PASSWORD = "my-test-password"
NEW_PASSWORD = "my-new-password"


class DatabaseFactory:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.statements: list[Executable] = []

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[AsyncSession]:
        with Session(self.engine, expire_on_commit=False) as session, session.begin():

            def execute(statement: Executable) -> object:
                self.statements.append(statement)
                return session.execute(statement)

            database = MagicMock(spec=AsyncSession)
            database.execute = AsyncMock(side_effect=execute)
            database.flush = AsyncMock(side_effect=session.flush)
            database.add = session.add
            yield cast(AsyncSession, database)


@pytest.fixture
def database() -> Iterator[Engine]:
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        for model in (User, Account, AccountMember, UserIdentity, PasswordCredential):
            model.__table__.create(connection)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(database: Engine) -> DatabaseFactory:
    return DatabaseFactory(database)


@pytest.fixture
def repository(factory: DatabaseFactory) -> AccountStore:
    return AccountStore(cast(async_sessionmaker[AsyncSession], factory))


@pytest.fixture
def passwords(factory: DatabaseFactory) -> PasswordRepository:
    return PasswordRepository(cast(async_sessionmaker[AsyncSession], factory))


def oauth_identity(
    provider: str = "google", subject: str = "google-alice"
) -> ProviderIdentity:
    return ProviderIdentity(
        provider=provider,
        subject=subject,
        display_name="Provider display name",
        email="alice@example.com",
        avatar_url="https://example.com/provider.png",
    )


def seed_user(
    database: Engine,
    *,
    user_id: str = "alice",
    provider: str = "google",
    subject: str = "google-alice",
) -> User:
    with Session(database, expire_on_commit=False) as db, db.begin():
        user = User(
            id=user_id,
            personal_account=Account(
                id=f"personal-{user_id}",
                personal_user_id=user_id,
                structure="personal",
                is_active=True,
            ),
            display_name="Local Alice",
            avatar_url="https://example.com/local.png",
            email="alice@example.com",
            phone="123456789",
            is_active=True,
            auth_version=1,
        )
        db.add(user)
        db.flush()
        db.add(
            AccountMember(
                account_id=user.personal_account.id, user_id=user.id, role="owner"
            )
        )
        db.add(
            UserIdentity(
                id=f"identity-{user_id}",
                user_id=user_id,
                provider=provider,
                subject=subject,
            )
        )
    return user


async def seed_password(passwords: PasswordRepository) -> User:
    return await passwords.create_user("alice", PASSWORD, display_name="Local Alice")


def assert_error(
    error: pytest.ExceptionInfo[AccountError], code: str, status: int
) -> None:
    assert error.value.code == code
    assert error.value.status == status


@pytest.mark.asyncio
async def test_link_keeps_user_profile_and_does_not_merge_matching_email(
    repository: AccountStore, database: Engine
) -> None:
    user = seed_user(database)
    other = seed_user(
        database, user_id="bob", provider="dingtalk", subject="dingtalk-bob"
    )
    linked = await repository.link_identity(
        user.id,
        user.personal_account.id,
        1,
        oauth_identity("dingtalk", "new-dingtalk-alice"),
    )
    assert (linked.id, linked.auth_version) == (user.id, 2)
    snapshot = await repository.snapshot(user.id, user.personal_account.id)
    assert [item.provider for item in snapshot.identities] == ["dingtalk", "google"]
    assert snapshot.username is None
    assert snapshot.user.display_name == "Local Alice"
    assert snapshot.user.avatar_url == "https://example.com/local.png"
    assert snapshot.user.email == "alice@example.com"
    assert snapshot.user.phone == "123456789"
    assert (
        await repository.snapshot(other.id, other.personal_account.id)
    ).user.auth_version == 1
    with Session(database) as db:
        assert len(db.scalars(select(User)).all()) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("shared_workspace", [False, True])
async def test_identity_already_claimed_by_any_user_is_a_conflict(
    repository: AccountStore, database: Engine, shared_workspace: bool
) -> None:
    user = seed_user(database)
    seed_user(
        database,
        user_id="bob",
        provider="dingtalk",
        subject="taken",
    )
    account_id = user.personal_account.id
    if shared_workspace:
        with Session(database) as db, db.begin():
            db.add(
                Account(id="shared-workspace", structure="workspace", is_active=True)
            )
            db.flush()
            db.add_all(
                [
                    AccountMember(
                        account_id="shared-workspace", user_id=user.id, role="owner"
                    ),
                    AccountMember(
                        account_id="shared-workspace", user_id="bob", role="member"
                    ),
                ]
            )
        account_id = "shared-workspace"
    with pytest.raises(AccountError) as error:
        await repository.link_identity(
            user.id, account_id, 1, oauth_identity("dingtalk", "taken")
        )
    assert_error(error, "identity_conflict", 409)
    assert (
        await repository.snapshot(user.id, user.personal_account.id)
    ).user.auth_version == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("subject", ["google-alice", "another-google-account"])
async def test_one_identity_per_provider_even_for_a_different_subject(
    repository: AccountStore, database: Engine, subject: str
) -> None:
    user = seed_user(database)
    with pytest.raises(AccountError) as error:
        await repository.link_identity(
            user.id, user.personal_account.id, 1, oauth_identity(subject=subject)
        )
    assert_error(error, "provider_already_linked", 409)


@pytest.mark.asyncio
async def test_verify_identity_never_auto_links_a_new_identity(
    repository: AccountStore, database: Engine
) -> None:
    user = seed_user(database)
    verified = await repository.verify_identity(
        user.id, user.personal_account.id, 1, oauth_identity()
    )
    assert (verified.id, verified.auth_version) == (user.id, 1)
    with pytest.raises(AccountError) as error:
        await repository.verify_identity(
            user.id, user.personal_account.id, 1, oauth_identity("dingtalk", "new")
        )
    assert_error(error, "identity_not_linked", 403)
    assert (
        len((await repository.snapshot(user.id, user.personal_account.id)).identities)
        == 1
    )


@pytest.mark.asyncio
async def test_verify_rejects_identity_owned_by_other_user(
    repository: AccountStore, database: Engine
) -> None:
    user = seed_user(database)
    seed_user(database, user_id="bob", subject="google-bob")
    with pytest.raises(AccountError) as error:
        await repository.verify_identity(
            user.id, user.personal_account.id, 1, oauth_identity(subject="google-bob")
        )
    assert_error(error, "identity_not_linked", 403)


@pytest.mark.asyncio
async def test_profile_changes_only_cosmetic_fields_and_keeps_auth_version(
    repository: AccountStore, database: Engine
) -> None:
    user = seed_user(database)
    updated = await repository.profile(
        user.id,
        user.personal_account.id,
        1,
        {
            "display_name": "Alice Updated",
            "avatar_url": None,
        },
    )
    assert updated.auth_version == 1
    snapshot = await repository.snapshot(user.id, user.personal_account.id)
    assert snapshot.user.display_name == "Alice Updated"
    assert snapshot.user.avatar_url is None
    assert snapshot.user.email == user.email
    assert [item.id for item in snapshot.identities] == ["identity-alice"]
    with pytest.raises(AccountError) as error:
        await repository.profile(
            user.id, user.personal_account.id, 1, {"tenant_id": "other"}
        )
    assert_error(error, "invalid_profile", 422)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["account", "inactive", "missing"])
async def test_snapshot_rejects_unavailable_user(
    repository: AccountStore, database: Engine, failure: str
) -> None:
    user = seed_user(database)
    if failure == "inactive":
        with Session(database) as db, db.begin():
            db.get(User, user.id).is_active = False
    with pytest.raises(AccountError) as error:
        await repository.snapshot(
            "missing" if failure == "missing" else user.id,
            "other-account" if failure == "account" else user.personal_account.id,
        )
    assert_error(error, "account_unavailable", 401)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["profile", "link", "verify", "unlink", "password"])
@pytest.mark.parametrize("failure", ["account", "inactive", "version"])
async def test_mutations_enforce_user_account_active_and_expected_version(
    repository: AccountStore, database: Engine, method: str, failure: str
) -> None:
    user = seed_user(database)
    if failure == "inactive":
        with Session(database) as db, db.begin():
            db.get(User, user.id).is_active = False
    account_id = "other-account" if failure == "account" else user.personal_account.id
    version = 7 if failure == "version" else 1
    with pytest.raises(AccountError) as error:
        match method:
            case "profile":
                await repository.profile(
                    user.id, account_id, version, {"display_name": "Changed"}
                )
            case "link":
                await repository.link_identity(
                    user.id, account_id, version, oauth_identity("dingtalk", "new")
                )
            case "verify":
                await repository.verify_identity(
                    user.id, account_id, version, oauth_identity()
                )
            case "unlink":
                await repository.unlink_identity(
                    user.id, account_id, version, "identity-alice", {"google"}
                )
            case "password":
                await repository.set_password(
                    user.id,
                    account_id,
                    version,
                    username="alice",
                    password=PASSWORD,
                    current_password=None,
                )
    assert_error(
        error,
        "account_changed" if failure == "version" else "account_unavailable",
        409 if failure == "version" else 401,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [{"google"}, {"google", "phone"}, set()])
async def test_cannot_remove_last_available_login(
    repository: AccountStore, database: Engine, enabled: set[str]
) -> None:
    user = seed_user(database)
    await repository.link_identity(
        user.id, user.personal_account.id, 1, oauth_identity("dingtalk", "new")
    )
    with pytest.raises(AccountError) as error:
        await repository.unlink_identity(
            user.id, user.personal_account.id, 2, "identity-alice", enabled
        )
    assert_error(error, "last_login_method", 409)
    assert (
        len((await repository.snapshot(user.id, user.personal_account.id)).identities)
        == 2
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_state", ["missing", "wrong_subject"])
async def test_password_identity_without_matching_credential_cannot_preserve_login(
    repository: AccountStore, database: Engine, credential_state: str
) -> None:
    user = seed_user(database)
    with Session(database) as db, db.begin():
        db.add(
            UserIdentity(
                id="password-id", user_id=user.id, provider="password", subject="alice"
            )
        )
        if credential_state == "wrong_subject":
            db.add(
                PasswordCredential(
                    user_id=user.id, username="different", hashed_password="hash"
                )
            )
    with pytest.raises(AccountError) as error:
        await repository.unlink_identity(
            user.id,
            user.personal_account.id,
            1,
            "identity-alice",
            {"google", "password"},
        )
    assert_error(error, "last_login_method", 409)


@pytest.mark.asyncio
async def test_unlink_checks_identity_ownership(
    repository: AccountStore, database: Engine
) -> None:
    user = seed_user(database)
    seed_user(database, user_id="bob", subject="bob-google")
    with pytest.raises(AccountError) as error:
        await repository.unlink_identity(
            user.id, user.personal_account.id, 1, "identity-bob", {"google"}
        )
    assert_error(error, "identity_not_linked", 404)


@pytest.mark.asyncio
async def test_two_removals_with_same_version_cannot_remove_both_logins(
    repository: AccountStore, database: Engine
) -> None:
    user = seed_user(database)
    await repository.link_identity(
        user.id, user.personal_account.id, 1, oauth_identity("dingtalk", "new")
    )
    identities = (
        await repository.snapshot(user.id, user.personal_account.id)
    ).identities
    first = await repository.unlink_identity(
        user.id, user.personal_account.id, 2, identities[0].id, {"google", "dingtalk"}
    )
    assert first.auth_version == 3
    with pytest.raises(AccountError) as stale:
        await repository.unlink_identity(
            user.id,
            user.personal_account.id,
            2,
            identities[1].id,
            {"google", "dingtalk"},
        )
    assert_error(stale, "account_changed", 409)
    with pytest.raises(AccountError) as last:
        await repository.unlink_identity(
            user.id,
            user.personal_account.id,
            3,
            identities[1].id,
            {"google", "dingtalk"},
        )
    assert_error(last, "last_login_method", 409)
    assert (
        len((await repository.snapshot(user.id, user.personal_account.id)).identities)
        == 1
    )


@pytest.mark.asyncio
async def test_first_password_adds_login_to_same_user_in_worker_thread(
    repository: AccountStore,
    database: Engine,
    passwords: PasswordRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = seed_user(database)
    main_thread = threading.get_ident()
    hash_threads: list[int] = []
    original = store.hash_password

    def tracked_hash(password: str) -> str:
        hash_threads.append(threading.get_ident())
        return original(password)

    monkeypatch.setattr(store, "hash_password", tracked_hash)
    updated = await repository.set_password(
        user.id,
        user.personal_account.id,
        1,
        username=" ALICE ",
        password=PASSWORD,
        current_password=None,
    )
    assert (updated.id, updated.auth_version) == (user.id, 2)
    assert len(hash_threads) == 1 and hash_threads[0] != main_thread
    assert (await passwords.authenticate("alice", PASSWORD)).id == user.id
    snapshot = await repository.snapshot(user.id, user.personal_account.id)
    assert snapshot.username == "alice"
    assert {item.provider for item in snapshot.identities} == {"google", "password"}


@pytest.mark.asyncio
async def test_password_change_requires_current_password_and_keeps_username(
    repository: AccountStore, passwords: PasswordRepository
) -> None:
    user = await seed_password(passwords)
    for current, code in [
        (None, "current_password_required"),
        ("wrong", "invalid_current_password"),
    ]:
        with pytest.raises(AccountError) as error:
            await repository.set_password(
                user.id,
                user.personal_account.id,
                1,
                username=None,
                password=NEW_PASSWORD,
                current_password=current,
            )
        assert_error(error, code, 400)
    with pytest.raises(AccountError) as rename:
        await repository.set_password(
            user.id,
            user.personal_account.id,
            1,
            username="bob",
            password=NEW_PASSWORD,
            current_password=PASSWORD,
        )
    assert_error(rename, "username_immutable", 422)
    updated = await repository.set_password(
        user.id,
        user.personal_account.id,
        1,
        username=None,
        password=NEW_PASSWORD,
        current_password=PASSWORD,
    )
    assert updated.auth_version == 2
    assert await passwords.authenticate("alice", PASSWORD) is None
    assert (await passwords.authenticate("alice", NEW_PASSWORD)).id == user.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "username,password,code",
    [
        (None, PASSWORD, "username_required"),
        ("a", PASSWORD, "invalid_username"),
        ("alice", "short", "invalid_password"),
    ],
)
async def test_first_password_validation(
    repository: AccountStore,
    database: Engine,
    username: str | None,
    password: str,
    code: str,
) -> None:
    user = seed_user(database)
    with pytest.raises(AccountError) as error:
        await repository.set_password(
            user.id,
            user.personal_account.id,
            1,
            username=username,
            password=password,
            current_password=None,
        )
    assert_error(error, code, 422)
    assert (
        await repository.snapshot(user.id, user.personal_account.id)
    ).username is None


@pytest.mark.asyncio
async def test_existing_username_cannot_be_claimed_or_merged(
    repository: AccountStore, database: Engine, passwords: PasswordRepository
) -> None:
    owner = await seed_password(passwords)
    user = seed_user(database)
    with pytest.raises(AccountError) as error:
        await repository.set_password(
            user.id,
            user.personal_account.id,
            1,
            username="ALICE",
            password=NEW_PASSWORD,
            current_password=None,
        )
    assert_error(error, "username_conflict", 409)
    assert (await passwords.authenticate("alice", PASSWORD)).id == owner.id
    snapshot = await repository.snapshot(user.id, user.personal_account.id)
    assert snapshot.username is None
    assert snapshot.user.auth_version == 1
    assert len(snapshot.identities) == 1


@pytest.mark.asyncio
async def test_unlink_password_deletes_credential_and_invalidates_old_version(
    repository: AccountStore, passwords: PasswordRepository, database: Engine
) -> None:
    user = await seed_password(passwords)
    await repository.link_identity(
        user.id, user.personal_account.id, 1, oauth_identity()
    )
    identity = next(
        item
        for item in (
            await repository.snapshot(user.id, user.personal_account.id)
        ).identities
        if item.provider == "password"
    )
    changed = await repository.unlink_identity(
        user.id, user.personal_account.id, 2, identity.id, {"google", "password"}
    )
    assert changed.auth_version == 3
    assert await passwords.authenticate("alice", PASSWORD) is None
    with Session(database) as db:
        assert db.get(PasswordCredential, user.id) is None
    assert (
        await repository.snapshot(user.id, user.personal_account.id)
    ).username is None


@pytest.mark.asyncio
async def test_enabled_matching_password_allows_unlinking_oauth(
    repository: AccountStore, database: Engine
) -> None:
    user = seed_user(database)
    await repository.set_password(
        user.id,
        user.personal_account.id,
        1,
        username="alice",
        password=PASSWORD,
        current_password=None,
    )
    changed = await repository.unlink_identity(
        user.id, user.personal_account.id, 2, "identity-alice", {"google", "password"}
    )
    assert changed.auth_version == 3
    assert [
        item.provider
        for item in (
            await repository.snapshot(user.id, user.personal_account.id)
        ).identities
    ] == ["password"]


@pytest.mark.asyncio
@pytest.mark.parametrize("bump_version", [True, False])
async def test_password_reset_during_verification_cannot_be_overwritten(
    repository: AccountStore,
    database: Engine,
    passwords: PasswordRepository,
    monkeypatch: pytest.MonkeyPatch,
    bump_version: bool,
) -> None:
    user = await seed_password(passwords)
    original = store.run_in_threadpool
    interleaved = False

    async def interleave(func: Callable[..., object], *args: object) -> object:
        nonlocal interleaved
        result = await original(func, *args)
        if func is store.verify_password and not interleaved:
            interleaved = True
            await passwords.set_password("alice", "administrator-reset-password")
            if not bump_version:
                with Session(database) as db, db.begin():
                    db.get(User, user.id).auth_version = 1
        return result

    monkeypatch.setattr(store, "run_in_threadpool", interleave)
    with pytest.raises(AccountError) as error:
        await repository.set_password(
            user.id,
            user.personal_account.id,
            1,
            username=None,
            password=NEW_PASSWORD,
            current_password=PASSWORD,
        )
    assert_error(error, "account_changed", 409)
    assert (
        await passwords.authenticate("alice", "administrator-reset-password")
    ).id == user.id
    assert await passwords.authenticate("alice", NEW_PASSWORD) is None


@pytest.mark.asyncio
async def test_first_password_rechecks_version_after_hashing(
    repository: AccountStore, database: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = seed_user(database)
    original = store.run_in_threadpool

    async def interleave(func: Callable[..., object], *args: object) -> object:
        result = await original(func, *args)
        if func is store.hash_password:
            await repository.link_identity(
                user.id, user.personal_account.id, 1, oauth_identity("dingtalk", "new")
            )
        return result

    monkeypatch.setattr(store, "run_in_threadpool", interleave)
    with pytest.raises(AccountError) as error:
        await repository.set_password(
            user.id,
            user.personal_account.id,
            1,
            username="alice",
            password=PASSWORD,
            current_password=None,
        )
    assert_error(error, "account_changed", 409)
    assert (
        await repository.snapshot(user.id, user.personal_account.id)
    ).username is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["unlink", "set_password"])
async def test_password_mutations_use_postgres_user_then_credential_locks(
    repository: AccountStore,
    passwords: PasswordRepository,
    factory: DatabaseFactory,
    operation: str,
) -> None:
    user = await seed_password(passwords)
    await repository.link_identity(
        user.id, user.personal_account.id, 1, oauth_identity()
    )
    password_identity = next(
        item
        for item in (
            await repository.snapshot(user.id, user.personal_account.id)
        ).identities
        if item.provider == "password"
    )
    factory.statements.clear()
    if operation == "unlink":
        await repository.unlink_identity(
            user.id,
            user.personal_account.id,
            2,
            password_identity.id,
            {"google", "password"},
        )
    else:
        await repository.set_password(
            user.id,
            user.personal_account.id,
            2,
            username=None,
            password=NEW_PASSWORD,
            current_password=PASSWORD,
        )
    locked_sql = [
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in factory.statements
        if getattr(statement, "_for_update_arg", None) is not None
    ]
    assert len(locked_sql) == 2
    assert 'FROM "user"' in locked_sql[0]
    assert "FROM password_credential" in locked_sql[1]
    assert all(sql.endswith("FOR UPDATE") for sql in locked_sql)


@pytest.mark.asyncio
async def test_link_and_profile_lock_user_row(
    repository: AccountStore, database: Engine, factory: DatabaseFactory
) -> None:
    user = seed_user(database)
    await repository.link_identity(
        user.id, user.personal_account.id, 1, oauth_identity("dingtalk", "new")
    )
    await repository.profile(
        user.id, user.personal_account.id, 2, {"display_name": "Updated"}
    )
    locked_sql = [
        str(statement.compile(dialect=postgresql.dialect()))
        for statement in factory.statements
        if getattr(statement, "_for_update_arg", None) is not None
    ]
    assert len(locked_sql) == 2
    assert all(
        'FROM "user"' in sql and sql.endswith("FOR UPDATE") for sql in locked_sql
    )
