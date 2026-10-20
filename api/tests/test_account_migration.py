import os
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection, make_url

from api.models import (
    Account,
    AccountMember,
    PasswordCredential,
    ResourceOwner,
    User,
    UserIdentity,
)


def _migration(filename: str, connection: Connection) -> ModuleType:
    path = Path(__file__).parents[1] / "alembic" / "versions" / filename
    spec = spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(connection))
    return module


@contextmanager
def _migration_connection(backend: str) -> Iterator[Connection]:
    if backend == "sqlite":
        # SQLite batch ALTER requires foreign keys disabled during table rebuilds.
        engine = sa.create_engine("sqlite://")
        try:
            with engine.begin() as connection:
                yield connection
        finally:
            engine.dispose()
        return

    dsn = os.getenv("TEST_ACCOUNT_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Set TEST_ACCOUNT_POSTGRES_DSN to a disposable loopback PostgreSQL")
    assert dsn.startswith("postgresql+psycopg://")
    assert make_url(dsn).host == "127.0.0.1"
    schema = f"test_account_migration_{uuid4().hex}"
    administration = sa.create_engine(dsn)
    engine = sa.create_engine(
        dsn,
        connect_args={
            "options": (
                f"-c search_path={schema} -c lock_timeout=10000 "
                "-c statement_timeout=15000"
            ),
        },
    )
    created = False
    try:
        with administration.begin() as connection:
            connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
            created = True
        with engine.begin() as connection:
            yield connection
    finally:
        engine.dispose()
        try:
            if created:
                with administration.begin() as connection:
                    connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            administration.dispose()


def _assert_foreign_keys_valid(connection: Connection) -> None:
    if connection.dialect.name == "sqlite":
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []


@pytest.fixture(params=["sqlite", "postgresql"])
def legacy_database(request: pytest.FixtureRequest) -> Iterator[Connection]:
    with _migration_connection(request.param) as connection:
        _migration("c36f109ab672_auth_users.py", connection).upgrade()
        _migration("da72e4b18c09_password_credentials.py", connection).upgrade()
        connection.execute(
            sa.text(
                "INSERT INTO auth_user "
                "(id, tenant_id, display_name, is_active, auth_version) "
                "VALUES (:id, :tenant_id, :display_name, true, 1)"
            ),
            [
                {"id": "alice", "tenant_id": "default", "display_name": "Alice"},
                {"id": "bob", "tenant_id": "default", "display_name": "Bob"},
            ],
        )
        connection.execute(
            sa.text(
                "INSERT INTO auth_resource_owner "
                "(resource_type, resource_id, user_id, tenant_id) "
                "VALUES ('conversation', :resource_id, :user_id, 'default')"
            ),
            [
                {"resource_id": "conversation-alice", "user_id": "alice"},
                {"resource_id": "conversation-bob", "user_id": "bob"},
            ],
        )
        connection.execute(
            sa.text(
                "INSERT INTO auth_identity (id, user_id, provider, subject) "
                "VALUES ('identity-alice', 'alice', 'google', 'external-alice')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO auth_password_credential (user_id, username, hashed_password) "
                "VALUES ('bob', 'bob', 'unchanged-password-hash')"
            )
        )
        yield connection


def test_migration_separates_shared_legacy_tenants_and_restores_them(
    legacy_database: Connection,
) -> None:
    migration = _migration("e28b47a1d902_user_accounts.py", legacy_database)
    migration.upgrade()
    accounts = (
        legacy_database.execute(
            sa.text("SELECT id, personal_user_id, structure FROM account")
        )
        .mappings()
        .all()
    )
    assert len(accounts) == 2
    assert len({account["id"] for account in accounts}) == 2
    assert all(account["id"] != "default" for account in accounts)
    assert all(account["structure"] == "personal" for account in accounts)
    owners = legacy_database.execute(
        sa.text(
            "SELECT resource.user_id, account.personal_user_id, member.role "
            "FROM resource_owner AS resource "
            "JOIN account ON account.id = resource.account_id "
            "JOIN account_member AS member ON member.account_id = account.id"
        )
    ).all()
    assert set(owners) == {("alice", "alice", "owner"), ("bob", "bob", "owner")}
    assert (
        legacy_database.execute(
            sa.text("SELECT hashed_password FROM password_credential")
        ).scalar_one()
        == "unchanged-password-hash"
    )
    assert (
        legacy_database.execute(
            sa.text("SELECT subject FROM user_identity")
        ).scalar_one()
        == "external-alice"
    )
    _assert_foreign_keys_valid(legacy_database)
    assert "tenant_id" not in {
        column["name"] for column in sa.inspect(legacy_database).get_columns("user")
    }
    assert (
        legacy_database.execute(
            sa.text('SELECT DISTINCT auth_version FROM "user"')
        ).scalar_one()
        == 2
    )

    migration.downgrade()
    assert legacy_database.execute(
        sa.text("SELECT id, tenant_id FROM auth_user ORDER BY id")
    ).all() == [("alice", "default"), ("bob", "default")]
    assert legacy_database.execute(
        sa.text("SELECT user_id, tenant_id FROM auth_resource_owner ORDER BY user_id")
    ).all() == [("alice", "default"), ("bob", "default")]
    assert (
        legacy_database.execute(
            sa.text("SELECT hashed_password FROM auth_password_credential")
        ).scalar_one()
        == "unchanged-password-hash"
    )
    _assert_foreign_keys_valid(legacy_database)
    assert "_account_legacy_scope" not in sa.inspect(legacy_database).get_table_names()


@pytest.mark.parametrize("invalid_owner", ["wrong-tenant", "missing-user"])
def test_upgrade_rejects_inconsistent_resource_scope_before_changes(
    legacy_database: Connection, invalid_owner: str
) -> None:
    if invalid_owner == "wrong-tenant":
        legacy_database.execute(
            sa.text(
                "UPDATE auth_resource_owner SET tenant_id = 'other-tenant' "
                "WHERE user_id = 'alice'"
            )
        )
    else:
        if legacy_database.dialect.name == "postgresql":
            pytest.skip("PostgreSQL foreign keys prevent orphaned legacy owners")
        legacy_database.execute(
            sa.text(
                "UPDATE auth_resource_owner SET user_id = 'missing-user' "
                "WHERE user_id = 'alice'"
            )
        )
    migration = _migration("e28b47a1d902_user_accounts.py", legacy_database)
    with pytest.raises(RuntimeError, match="scope is inconsistent"):
        migration.upgrade()
    assert "auth_user" in sa.inspect(legacy_database).get_table_names()
    assert "account" not in sa.inspect(legacy_database).get_table_names()
    assert (
        legacy_database.execute(
            sa.text("SELECT COUNT(*) FROM auth_resource_owner")
        ).scalar_one()
        == 2
    )


def test_downgrade_rejects_workspace_before_changes(
    legacy_database: Connection,
) -> None:
    migration = _migration("e28b47a1d902_user_accounts.py", legacy_database)
    migration.upgrade()
    legacy_database.execute(
        sa.text("INSERT INTO account (id, structure) VALUES ('workspace', 'workspace')")
    )
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        migration.downgrade()
    assert "account" in sa.inspect(legacy_database).get_table_names()
    assert "auth_user" not in sa.inspect(legacy_database).get_table_names()
    assert "tenant_id" not in {
        column["name"] for column in sa.inspect(legacy_database).get_columns("user")
    }


def test_downgrade_rejects_reassigned_resource_ownership(
    legacy_database: Connection,
) -> None:
    migration = _migration("e28b47a1d902_user_accounts.py", legacy_database)
    migration.upgrade()
    legacy_database.execute(
        sa.text(
            "UPDATE resource_owner SET account_id = "
            "(SELECT id FROM account WHERE personal_user_id = 'bob') "
            "WHERE user_id = 'alice'"
        )
    )
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        migration.downgrade()
    assert "account" in sa.inspect(legacy_database).get_table_names()


def test_downgrade_assigns_new_users_their_personal_account_scope(
    legacy_database: Connection,
) -> None:
    migration = _migration("e28b47a1d902_user_accounts.py", legacy_database)
    migration.upgrade()
    legacy_database.execute(
        sa.text(
            'INSERT INTO "user" (id, display_name, is_active, auth_version) '
            "VALUES ('carol', 'Carol', true, 1)"
        )
    )
    legacy_database.execute(
        sa.text(
            "INSERT INTO account (id, personal_user_id) "
            "VALUES ('personal-carol', 'carol')"
        )
    )
    legacy_database.execute(
        sa.text(
            "INSERT INTO account_member (account_id, user_id, role) "
            "VALUES ('personal-carol', 'carol', 'owner')"
        )
    )
    legacy_database.execute(
        sa.text(
            "INSERT INTO resource_owner (resource_type, resource_id, user_id, account_id) "
            "VALUES ('conversation', 'conversation-carol', 'carol', 'personal-carol')"
        )
    )
    migration.downgrade()
    assert (
        legacy_database.execute(
            sa.text("SELECT tenant_id FROM auth_user WHERE id = 'carol'")
        ).scalar_one()
        == "personal-carol"
    )
    assert (
        legacy_database.execute(
            sa.text("SELECT tenant_id FROM auth_resource_owner WHERE user_id = 'carol'")
        ).scalar_one()
        == "personal-carol"
    )


def test_migration_schema_matches_account_models(legacy_database: Connection) -> None:
    migration = _migration("e28b47a1d902_user_accounts.py", legacy_database)
    migration.upgrade()
    metadata = sa.MetaData()
    for model in (
        User,
        Account,
        AccountMember,
        UserIdentity,
        PasswordCredential,
        ResourceOwner,
    ):
        model.__table__.to_metadata(metadata)
    context = MigrationContext.configure(
        legacy_database,
        opts={
            "compare_server_default": True,
            "include_object": lambda obj, name, type_, reflected, compare_to: (
                type_ != "table" or name != "_account_legacy_scope"
            ),
        },
    )
    assert compare_metadata(context, metadata) == []
