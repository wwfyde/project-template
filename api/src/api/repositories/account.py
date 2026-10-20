"""Account containers and membership, independent of login credentials."""

from uuid import uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm.attributes import set_committed_value

from api.models import Account, AccountMember, User


async def create_personal_account(db: AsyncSession, user: User) -> Account:
    """Provision the personal container inside the user creation transaction."""
    account = Account(
        id=str(uuid4()),
        structure="personal",
        personal_user_id=user.id,
        is_active=True,
    )
    db.add(account)
    await db.flush()
    db.add(AccountMember(account_id=account.id, user_id=user.id, role="owner"))
    set_committed_value(user, "personal_account", account)
    return account


def accessible_account(user_id: str, account_id: str) -> Select[tuple[Account]]:
    return (
        select(Account)
        .join(AccountMember, AccountMember.account_id == Account.id)
        .where(
            Account.id == account_id,
            Account.is_active.is_(True),
            AccountMember.user_id == user_id,
            (Account.structure == "workspace") | (Account.personal_user_id == user_id),
        )
    )


class AccountRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get(self, user_id: str, account_id: str) -> Account | None:
        async with self.sessions.begin() as db:
            return (
                await db.execute(accessible_account(user_id, account_id))
            ).scalar_one_or_none()

    async def list_for_user(self, user_id: str) -> list[Account]:
        async with self.sessions.begin() as db:
            return list(
                (
                    await db.execute(
                        select(Account)
                        .join(AccountMember, AccountMember.account_id == Account.id)
                        .where(
                            AccountMember.user_id == user_id,
                            Account.is_active.is_(True),
                            (Account.structure == "workspace")
                            | (Account.personal_user_id == user_id),
                        )
                        .order_by(Account.created_at, Account.id)
                    )
                ).scalars()
            )

    async def create_workspace(self, user_id: str, name: str) -> Account:
        name = name.strip()
        if not name or len(name) > 255:
            raise ValueError("Workspace name must contain 1 to 255 characters")
        async with self.sessions.begin() as db:
            user = (
                await db.execute(
                    select(User).where(User.id == user_id).with_for_update()
                )
            ).scalar_one_or_none()
            if user is None or not user.is_active:
                raise ValueError("User is unavailable")
            account = Account(
                id=str(uuid4()), name=name, structure="workspace", is_active=True
            )
            db.add(account)
            await db.flush()
            db.add(AccountMember(account_id=account.id, user_id=user_id, role="owner"))
        return account
