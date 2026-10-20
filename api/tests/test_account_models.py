from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.models import Account, AccountMember, Base, ResourceOwner, User


@pytest.fixture
def connection() -> Iterator[Connection]:
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
        Base.metadata.create_all(
            connection,
            tables=[
                User.__table__,
                Account.__table__,
                AccountMember.__table__,
                ResourceOwner.__table__,
            ],
        )
        connection.execute(
            sa.insert(User),
            [
                {"id": "alice", "display_name": "Alice"},
                {"id": "bob", "display_name": "Bob"},
            ],
        )
        yield connection
    engine.dispose()


def test_personal_account_defaults_and_user_relationship(
    connection: Connection,
) -> None:
    connection.execute(
        sa.insert(Account).values(id="personal-alice", personal_user_id="alice")
    )
    assert "tenant_id" not in User.__table__.columns
    with Session(connection) as session:
        user = session.get(User, "alice")
        assert user is not None
        assert user.personal_account is not None
        assert user.personal_account.id == "personal-alice"
        assert user.personal_account.structure == "personal"
        assert user.personal_account.is_active is True


@pytest.mark.parametrize(
    "values",
    [
        {"id": "missing-owner"},
        {"id": "unknown-structure", "structure": "team", "personal_user_id": "alice"},
        {
            "id": "workspace-owner",
            "structure": "workspace",
            "personal_user_id": "alice",
        },
    ],
)
def test_account_structure_and_personal_owner_are_constrained(
    connection: Connection, values: dict[str, str]
) -> None:
    with pytest.raises(IntegrityError):
        connection.execute(sa.insert(Account).values(**values))


def test_only_one_personal_account_per_user(connection: Connection) -> None:
    connection.execute(
        sa.insert(Account).values(id="alice-one", personal_user_id="alice")
    )
    with pytest.raises(IntegrityError):
        connection.execute(
            sa.insert(Account).values(id="alice-two", personal_user_id="alice")
        )


def test_workspace_memberships_are_unique_and_roles_are_constrained(
    connection: Connection,
) -> None:
    connection.execute(sa.insert(Account).values(id="shared", structure="workspace"))
    connection.execute(
        sa.insert(AccountMember).values(
            account_id="shared", user_id="alice", role="owner"
        )
    )
    connection.execute(
        sa.insert(AccountMember).values(account_id="shared", user_id="bob")
    )
    assert (
        connection.execute(
            sa.select(AccountMember.role).where(AccountMember.user_id == "bob")
        ).scalar_one()
        == "member"
    )
    with pytest.raises(IntegrityError):
        connection.execute(
            sa.insert(AccountMember).values(account_id="shared", user_id="bob")
        )
    with pytest.raises(IntegrityError):
        connection.execute(sa.update(AccountMember).values(role="superuser"))


def test_personal_account_prevents_cascading_user_deletion(
    connection: Connection,
) -> None:
    connection.execute(
        sa.insert(Account).values(id="alice-one", personal_user_id="alice")
    )
    with pytest.raises(IntegrityError):
        connection.execute(sa.delete(User).where(User.id == "alice"))


def test_resource_owner_requires_an_existing_account(connection: Connection) -> None:
    with pytest.raises(IntegrityError):
        connection.execute(
            sa.insert(ResourceOwner).values(
                resource_type="conversation",
                resource_id="conversation-one",
                user_id="alice",
                account_id="unknown",
            )
        )
