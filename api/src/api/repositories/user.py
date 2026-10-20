"""PostgreSQL is the source of truth for users and resource ownership."""

from typing import Protocol
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.models import Account, ResourceOwner, User, UserIdentity
from api.repositories.account import (
    AccountRepository,
    accessible_account,
    create_personal_account,
)
from api.schemas.auth import AuthUser, ProviderIdentity


class UserRepository(Protocol):
    async def resolve(
        self, identity: ProviderIdentity, *, allow_signup: bool
    ) -> User: ...
    async def get(self, user_id: str, provider: str) -> User | None: ...
    async def account(self, user_id: str, account_id: str) -> Account | None: ...
    async def own(self, kind: str, resource_id: str, user: AuthUser) -> None: ...
    async def owns(self, kind: str, resource_id: str, user: AuthUser) -> bool: ...
    async def owned_ids(self, kind: str, user: AuthUser) -> set[str]: ...


class PostgresUserRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def account(self, user_id: str, account_id: str) -> Account | None:
        return await AccountRepository(self.sessions).get(user_id, account_id)

    async def get(self, user_id: str, provider: str) -> User | None:
        async with self.sessions.begin() as db:
            result = await db.execute(
                select(User)
                .join(UserIdentity)
                .where(User.id == user_id, UserIdentity.provider == provider)
            )
            return result.scalars().first()

    async def resolve(self, identity: ProviderIdentity, *, allow_signup: bool) -> User:
        statement = (
            select(User)
            .join(UserIdentity)
            .where(
                UserIdentity.provider == identity.provider,
                UserIdentity.subject == identity.subject,
            )
        )
        try:
            async with self.sessions.begin() as db:
                user = (await db.execute(statement)).scalar_one_or_none()
                if user is not None:
                    if not user.is_active:
                        raise HTTPException(403, "Account is disabled")
                    return user
                if not allow_signup:
                    raise HTTPException(403, "Account registration is disabled")
                user = User(
                    id=str(uuid4()),
                    display_name=identity.display_name,
                    avatar_url=identity.avatar_url,
                    email=identity.email,
                    phone=identity.phone,
                    is_active=True,
                    auth_version=1,
                )
                db.add(user)
                await db.flush()
                await create_personal_account(db, user)
                db.add(
                    UserIdentity(
                        id=str(uuid4()),
                        user_id=user.id,
                        provider=identity.provider,
                        subject=identity.subject,
                    )
                )
            return user
        except IntegrityError:
            # Concurrent first logins race on the provider/subject constraint.
            # Roll back user, account and membership before finding the winner.
            async with self.sessions.begin() as db:
                user = (await db.execute(statement)).scalar_one_or_none()
                if user is None:
                    raise
                if not user.is_active:
                    raise HTTPException(403, "Account is disabled")
                return user

    async def own(self, kind: str, resource_id: str, user: AuthUser) -> None:
        async with self.sessions.begin() as db:
            account = (
                await db.execute(accessible_account(user.id, user.account_id))
            ).scalar_one_or_none()
            if account is None:
                raise HTTPException(403, "Account is unavailable")
            db.add(
                ResourceOwner(
                    resource_type=kind,
                    resource_id=resource_id,
                    user_id=user.id,
                    account_id=user.account_id,
                )
            )

    async def owns(self, kind: str, resource_id: str, user: AuthUser) -> bool:
        async with self.sessions.begin() as db:
            owner = await db.execute(
                self._owned_resources(kind, user).where(
                    ResourceOwner.resource_id == resource_id
                )
            )
            return owner.scalar_one_or_none() is not None

    async def owned_ids(self, kind: str, user: AuthUser) -> set[str]:
        async with self.sessions.begin() as db:
            result = await db.execute(self._owned_resources(kind, user))
            return set(result.scalars())

    @staticmethod
    def _owned_resources(kind: str, user: AuthUser) -> Select[tuple[str]]:
        return select(ResourceOwner.resource_id).where(
            ResourceOwner.resource_type == kind,
            ResourceOwner.user_id == user.id,
            ResourceOwner.account_id.in_(
                accessible_account(user.id, user.account_id).with_only_columns(
                    Account.id
                )
            ),
        )


def public_user(user: User, provider: str, account: Account | None = None) -> AuthUser:
    account = account or user.personal_account
    if account is None or not account.is_active:
        raise HTTPException(401, "Account is unavailable")
    return AuthUser(
        id=user.id,
        account_id=account.id,
        provider=provider,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        email=user.email,
        phone=user.phone,
    )
