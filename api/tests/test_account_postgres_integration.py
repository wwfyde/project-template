"""Opt-in account races against a disposable PostgreSQL server.

Set TEST_ACCOUNT_POSTGRES_DSN to an isolated PostgreSQL + psycopg DSN and run
``uv run pytest tests/test_account_postgres_integration.py -q`` from api/.
Each test creates a random schema, sets its own connection search_path, and
drops only that schema. The application's configured database is never used.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Table, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.repositories.user_security import AccountError, AccountStore
from api.repositories.password import PasswordRepository
from api.schemas.auth import ProviderIdentity
from api.models import (
    Account,
    AccountMember,
    PasswordCredential,
    ResourceOwner,
    User,
    UserIdentity,
)

POSTGRES_DSN = os.getenv("TEST_ACCOUNT_POSTGRES_DSN")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not POSTGRES_DSN,
        reason="Set TEST_ACCOUNT_POSTGRES_DSN to an isolated PostgreSQL server",
    ),
]
PASSWORD = "initial-test-password"
RESET_PASSWORD = "reset-test-password"


@dataclass(frozen=True)
class Database:
    sessions: async_sessionmaker[AsyncSession]
    administration: AsyncEngine
    application_name: str


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    assert POSTGRES_DSN is not None
    assert POSTGRES_DSN.startswith("postgresql+psycopg://")
    assert make_url(POSTGRES_DSN).host == "127.0.0.1", (
        "Use a disposable loopback database"
    )
    # Identifier consists only of a fixed prefix and a generated hex UUID.
    # Never substitute an environment-provided schema or database identifier.
    schema = f"test_account_{uuid4().hex}"
    administration = create_async_engine(POSTGRES_DSN)
    engine = create_async_engine(
        POSTGRES_DSN,
        connect_args={
            "application_name": schema,
            "options": (
                f"-c search_path={schema} -c lock_timeout=10000 "
                "-c statement_timeout=15000"
            ),
        },
        pool_size=5,
        max_overflow=0,
    )
    created = False
    try:
        async with administration.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        async with engine.begin() as connection:
            for model in (
                User,
                Account,
                AccountMember,
                UserIdentity,
                PasswordCredential,
                ResourceOwner,
            ):
                await connection.run_sync(cast(Table, model.__table__).create)
        yield Database(
            sessions=async_sessionmaker(engine, expire_on_commit=False),
            administration=administration,
            application_name=schema,
        )
    finally:
        await engine.dispose()
        try:
            if created:
                async with administration.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            await administration.dispose()


def identity(provider: str, subject: str) -> ProviderIdentity:
    return ProviderIdentity(
        provider=provider,
        subject=subject,
        display_name="Provider profile",
        email="matching-email@example.com",
    )


async def seed_oauth_user(database: Database, name: str) -> User:
    async with database.sessions.begin() as db:
        user = User(
            id=str(uuid4()),
            personal_account=Account(
                id=str(uuid4()), structure="personal", is_active=True
            ),
            display_name=name,
            email="matching-email@example.com",
            is_active=True,
            auth_version=1,
        )
        db.add(user)
        await db.flush()
        db.add(
            AccountMember(
                account_id=user.personal_account.id, user_id=user.id, role="owner"
            )
        )
        db.add(
            UserIdentity(
                id=str(uuid4()),
                user_id=user.id,
                provider="dingtalk",
                subject=name,
            )
        )
        db.add(
            ResourceOwner(
                resource_type="conversation",
                resource_id=f"resource-{user.id}",
                user_id=user.id,
                account_id=user.personal_account.id,
            )
        )
    return user


async def assert_resource_owner(database: Database, user: User) -> None:
    async with database.sessions.begin() as db:
        owner = await db.get(ResourceOwner, ("conversation", f"resource-{user.id}"))
        assert owner is not None
        assert (owner.user_id, owner.account_id) == (user.id, user.personal_account.id)


async def wait_for_blocked_transactions(database: Database, count: int) -> None:
    """Observe real PostgreSQL lock waits before releasing the blocking row."""
    async with asyncio.timeout(8):
        async with database.administration.connect() as connection:
            while True:
                # A fresh transaction avoids PostgreSQL statistics snapshots
                # retaining a previous observation throughout this polling loop.
                result = await connection.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE application_name = :name AND wait_event_type = 'Lock'"
                    ),
                    {"name": database.application_name},
                )
                waiting = result.scalar_one()
                await connection.commit()
                if waiting >= count:
                    return
                await asyncio.sleep(0.01)


async def finish_tasks(*tasks: asyncio.Task[object]) -> list[object]:
    async with asyncio.timeout(12):
        return list(await asyncio.gather(*tasks, return_exceptions=True))


async def cancel_unfinished(*tasks: asyncio.Task[object]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def test_two_accounts_racing_for_one_identity_have_exactly_one_winner(
    database: Database,
) -> None:
    alice = await seed_oauth_user(database, "Alice")
    bob = await seed_oauth_user(database, "Bob")
    barrier = asyncio.Barrier(2)

    class ConcurrentStore(AccountStore):
        async def _identities(
            self, db: AsyncSession, user_id: str
        ) -> list[UserIdentity]:
            identities = await super()._identities(db, user_id)
            # Both real transactions have queried the unclaimed identity and
            # locked different User rows before either attempts its insert.
            await barrier.wait()
            return identities

    store = ConcurrentStore(database.sessions)
    claim = identity("google", "shared-google-subject")
    tasks = [
        asyncio.create_task(
            store.link_identity(user.id, user.personal_account.id, 1, claim)
        )
        for user in (alice, bob)
    ]
    try:
        results = await finish_tasks(*tasks)
    finally:
        await cancel_unfinished(*tasks)
    winners = [result for result in results if isinstance(result, User)]
    failures = [result for result in results if isinstance(result, AccountError)]
    assert len(winners) == len(failures) == 1, results
    assert (failures[0].code, failures[0].status) == ("identity_conflict", 409)
    assert winners[0].auth_version == 2
    async with database.sessions.begin() as db:
        claimed = (
            (
                await db.execute(
                    select(UserIdentity).where(UserIdentity.provider == "google")
                )
            )
            .scalars()
            .one()
        )
        assert claimed.user_id == winners[0].id
        users = (await db.execute(select(User))).scalars().all()
        assert len(users) == 2
        assert {user.auth_version for user in users} == {1, 2}
        assert {user.display_name for user in users} == {"Alice", "Bob"}
    await assert_resource_owner(database, alice)
    await assert_resource_owner(database, bob)


async def test_concurrent_oauth_unlinks_serialize_and_cannot_remove_all_logins(
    database: Database,
) -> None:
    user = await seed_oauth_user(database, "Alice")
    store = AccountStore(database.sessions)
    await store.link_identity(
        user.id, user.personal_account.id, 1, identity("google", "alice-google")
    )
    snapshot = await store.snapshot(user.id, user.personal_account.id)
    tasks: list[asyncio.Task[User]] = []
    try:
        async with database.sessions.begin() as blocker:
            await blocker.execute(
                select(User).where(User.id == user.id).with_for_update()
            )
            tasks = [
                asyncio.create_task(
                    store.unlink_identity(
                        user.id,
                        user.personal_account.id,
                        2,
                        linked.id,
                        {"google", "dingtalk"},
                    )
                )
                for linked in snapshot.identities
            ]
            await wait_for_blocked_transactions(database, 2)
        results = await finish_tasks(*tasks)
    finally:
        await cancel_unfinished(*tasks)
    successes = [result for result in results if isinstance(result, User)]
    failures = [result for result in results if isinstance(result, AccountError)]
    assert len(successes) == len(failures) == 1, results
    assert (failures[0].code, failures[0].status) == ("account_changed", 409)
    remaining = await store.snapshot(user.id, user.personal_account.id)
    assert remaining.user.auth_version == 3
    assert len(remaining.identities) == 1
    with pytest.raises(AccountError) as error:
        await store.unlink_identity(
            user.id,
            user.personal_account.id,
            3,
            remaining.identities[0].id,
            {"google", "dingtalk"},
        )
    assert error.value.code == "last_login_method"
    await assert_resource_owner(database, user)


@pytest.mark.parametrize("first", ["reset", "link"])
async def test_concurrent_password_reset_and_link_preserve_versions_and_ownership(
    database: Database,
    first: str,
) -> None:
    passwords = PasswordRepository(database.sessions)
    store = AccountStore(database.sessions)
    user = await passwords.create_user(
        "alice",
        PASSWORD,
        display_name="Alice",
    )
    async with database.sessions.begin() as db:
        db.add(
            ResourceOwner(
                resource_type="conversation",
                resource_id=f"resource-{user.id}",
                user_id=user.id,
                account_id=user.personal_account.id,
            )
        )
    tasks: dict[str, asyncio.Task[object]] = {}

    def start(operation: str) -> asyncio.Task[object]:
        if operation == "reset":
            return asyncio.create_task(passwords.set_password("alice", RESET_PASSWORD))
        return asyncio.create_task(
            store.link_identity(
                user.id,
                user.personal_account.id,
                1,
                identity("google", "alice-google"),
            )
        )

    try:
        async with database.sessions.begin() as blocker:
            await blocker.execute(
                select(User).where(User.id == user.id).with_for_update()
            )
            tasks[first] = start(first)
            await wait_for_blocked_transactions(database, 1)
            second = "link" if first == "reset" else "reset"
            tasks[second] = start(second)
            await wait_for_blocked_transactions(database, 2)
        results = await finish_tasks(tasks["reset"], tasks["link"])
    finally:
        await cancel_unfinished(*tasks.values())
    assert results[0] is None, results
    linked = results[1]
    assert isinstance(linked, User | AccountError), results
    if isinstance(linked, AccountError):
        assert (linked.code, linked.status) == ("account_changed", 409)
    final = await store.snapshot(user.id, user.personal_account.id)
    assert final.user.auth_version == 2 + int(isinstance(linked, User))
    assert {item.provider for item in final.identities} == (
        {"password", "google"} if isinstance(linked, User) else {"password"}
    )
    assert await passwords.authenticate("alice", PASSWORD) is None
    authenticated = await passwords.authenticate("alice", RESET_PASSWORD)
    assert authenticated is not None
    assert (authenticated.id, authenticated.auth_version) == (
        user.id,
        final.user.auth_version,
    )
    await assert_resource_owner(database, user)
