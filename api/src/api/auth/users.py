"""PostgreSQL is the source of truth for users and resource ownership."""

from typing import Protocol
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.auth.schemas import AuthUser, ProviderIdentity
from api.models.user import ResourceOwner, User, UserIdentity


class UserRepository(Protocol):
    async def resolve(
        self, identity: ProviderIdentity, *, tenant_id: str, allow_signup: bool
    ) -> User: ...
    async def get(self, user_id: str, provider: str) -> User | None: ...
    async def own(self, kind: str, resource_id: str, user: AuthUser) -> None: ...
    async def owns(self, kind: str, resource_id: str, user: AuthUser) -> bool: ...
    async def owned_ids(self, kind: str, user: AuthUser) -> set[str]: ...


class PostgresUserRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def get(self, user_id: str, provider: str) -> User | None:
        async with self.sessions.begin() as db:
            result = await db.execute(
                select(User)
                .join(UserIdentity)
                .where(User.id == user_id, UserIdentity.provider == provider)
            )
            return result.scalars().first()

    async def resolve(
        self, identity: ProviderIdentity, *, tenant_id: str, allow_signup: bool
    ) -> User:
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
                    tenant_id=tenant_id,
                    display_name=identity.display_name,
                    avatar_url=identity.avatar_url,
                    email=identity.email,
                    phone=identity.phone,
                    is_active=True,
                    auth_version=1,
                )
                db.add(user)
                await db.flush()
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
            # Rollback both inserts before finding the committed winner.
            async with self.sessions.begin() as db:
                user = (await db.execute(statement)).scalar_one_or_none()
                if user is None:
                    raise
                if not user.is_active:
                    raise HTTPException(403, "Account is disabled")
                return user

    async def own(self, kind: str, resource_id: str, user: AuthUser) -> None:
        async with self.sessions.begin() as db:
            db.add(
                ResourceOwner(
                    resource_type=kind,
                    resource_id=resource_id,
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                )
            )

    async def owns(self, kind: str, resource_id: str, user: AuthUser) -> bool:
        async with self.sessions.begin() as db:
            owner = await db.get(ResourceOwner, (kind, resource_id))
            return (
                owner is not None
                and owner.user_id == user.id
                and owner.tenant_id == user.tenant_id
            )

    async def owned_ids(self, kind: str, user: AuthUser) -> set[str]:
        async with self.sessions.begin() as db:
            result = await db.execute(
                select(ResourceOwner.resource_id).where(
                    ResourceOwner.resource_type == kind,
                    ResourceOwner.user_id == user.id,
                    ResourceOwner.tenant_id == user.tenant_id,
                )
            )
            return set(result.scalars())


def public_user(user: User, provider: str) -> AuthUser:
    return AuthUser(
        id=user.id,
        tenant_id=user.tenant_id,
        provider=provider,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        email=user.email,
        phone=user.phone,
    )
