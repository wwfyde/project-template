"""Account changes preserve the stable user and serialize on its database row.

All credential writers lock User before PasswordCredential, matching the login
and administrator password-reset repository. Expensive password work happens
outside those locks and is rechecked against the locked credential snapshot.
"""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.repositories.password import (
    hash_password,
    normalize_username,
    validate_new_password,
    verify_password,
)
from api.schemas.auth import ProviderIdentity
from api.models import Account, PasswordCredential, User, UserIdentity
from api.repositories.account import accessible_account


class AccountError(ValueError):
    """A safe, stable account failure without secrets or upstream responses."""

    def __init__(self, code: str, status: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


@dataclass(frozen=True)
class AccountSnapshot:
    user: User
    account: Account
    identities: list[UserIdentity]
    username: str | None


class AccountStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def _user(
        self,
        db: AsyncSession,
        user_id: str,
        account_id: str,
        expected_version: int | None = None,
        *,
        lock: bool = False,
    ) -> User:
        statement = select(User).where(User.id == user_id)
        if lock:
            statement = statement.with_for_update()
        user = (await db.execute(statement)).scalar_one_or_none()
        if user is None or not user.is_active:
            raise AccountError("account_unavailable", 401, "Account is unavailable")
        await self._account(db, user_id, account_id)
        if expected_version is not None and user.auth_version != expected_version:
            raise AccountError(
                "account_changed", 409, "Account changed; sign in again and retry"
            )
        return user

    async def _account(
        self, db: AsyncSession, user_id: str, account_id: str
    ) -> Account:
        account = (
            await db.execute(accessible_account(user_id, account_id))
        ).scalar_one_or_none()
        if account is None:
            raise AccountError("account_unavailable", 401, "Account is unavailable")
        return account

    async def _identities(self, db: AsyncSession, user_id: str) -> list[UserIdentity]:
        return list(
            (
                await db.execute(
                    select(UserIdentity)
                    .where(UserIdentity.user_id == user_id)
                    .order_by(UserIdentity.provider, UserIdentity.id)
                )
            ).scalars()
        )

    async def _credential(
        self, db: AsyncSession, user_id: str, *, lock: bool = False
    ) -> PasswordCredential | None:
        statement = select(PasswordCredential).where(
            PasswordCredential.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return (await db.execute(statement)).scalar_one_or_none()

    async def snapshot(self, user_id: str, account_id: str) -> AccountSnapshot:
        async with self.sessions.begin() as db:
            user = await self._user(db, user_id, account_id)
            identities = await self._identities(db, user_id)
            credential = await self._credential(db, user_id)
            return AccountSnapshot(
                user=user,
                account=await self._account(db, user_id, account_id),
                identities=identities,
                username=credential.username if credential else None,
            )

    async def profile(
        self,
        user_id: str,
        account_id: str,
        expected_version: int,
        updates: dict[str, str | None],
    ) -> User:
        if updates.keys() - {"display_name", "avatar_url"}:
            raise AccountError("invalid_profile", 422, "Unsupported profile field")
        async with self.sessions.begin() as db:
            user = await self._user(
                db, user_id, account_id, expected_version, lock=True
            )
            for name, value in updates.items():
                setattr(user, name, value)
        return user

    async def link_identity(
        self,
        user_id: str,
        account_id: str,
        expected_version: int,
        identity: ProviderIdentity,
    ) -> User:
        if identity.provider == "password":
            raise AccountError(
                "invalid_provider", 422, "Use password settings for this provider"
            )
        try:
            async with self.sessions.begin() as db:
                user = await self._user(
                    db, user_id, account_id, expected_version, lock=True
                )
                existing = (
                    await db.execute(
                        select(UserIdentity).where(
                            UserIdentity.provider == identity.provider,
                            UserIdentity.subject == identity.subject,
                        )
                    )
                ).scalar_one_or_none()
                if existing is not None and existing.user_id != user_id:
                    raise AccountError(
                        "identity_conflict", 409, "Identity belongs to another account"
                    )
                if any(
                    item.provider == identity.provider
                    for item in await self._identities(db, user_id)
                ):
                    raise AccountError(
                        "provider_already_linked", 409, "Provider is already linked"
                    )
                db.add(
                    UserIdentity(
                        id=str(uuid4()),
                        user_id=user_id,
                        provider=identity.provider,
                        subject=identity.subject,
                    )
                )
                user.auth_version += 1
            return user
        except IntegrityError as exc:
            # Different users have different row locks. The global provider /
            # subject unique constraint decides a simultaneous identity claim.
            raise AccountError(
                "identity_conflict", 409, "Identity belongs to another account"
            ) from exc

    async def verify_identity(
        self,
        user_id: str,
        account_id: str,
        expected_version: int,
        identity: ProviderIdentity,
    ) -> User:
        async with self.sessions.begin() as db:
            user = await self._user(
                db, user_id, account_id, expected_version, lock=True
            )
            if not any(
                item.provider == identity.provider and item.subject == identity.subject
                for item in await self._identities(db, user_id)
            ):
                raise AccountError(
                    "identity_not_linked", 403, "Identity is not linked to this account"
                )
        return user

    async def unlink_identity(
        self,
        user_id: str,
        account_id: str,
        expected_version: int,
        identity_id: str,
        enabled_providers: set[str],
    ) -> User:
        async with self.sessions.begin() as db:
            user = await self._user(
                db, user_id, account_id, expected_version, lock=True
            )
            credential = await self._credential(db, user_id, lock=True)
            identities = await self._identities(db, user_id)
            target = next((item for item in identities if item.id == identity_id), None)
            if target is None:
                raise AccountError("identity_not_linked", 404, "Identity was not found")
            if not any(
                item.id != identity_id
                and item.provider in enabled_providers
                and (
                    item.provider != "password"
                    or (
                        credential is not None
                        and credential.username == item.subject
                        and bool(credential.hashed_password)
                    )
                )
                for item in identities
            ):
                raise AccountError(
                    "last_login_method", 409, "Keep at least one available login method"
                )
            if target.provider == "password":
                await db.execute(
                    delete(PasswordCredential).where(
                        PasswordCredential.user_id == user_id
                    )
                )
            await db.execute(
                delete(UserIdentity).where(
                    UserIdentity.id == identity_id, UserIdentity.user_id == user_id
                )
            )
            user.auth_version += 1
        return user

    async def set_password(
        self,
        user_id: str,
        account_id: str,
        expected_version: int,
        *,
        username: str | None,
        password: str,
        current_password: str | None,
    ) -> User:
        try:
            validate_new_password(password)
        except ValueError as exc:
            raise AccountError("invalid_password", 422, str(exc)) from exc
        if username is not None:
            try:
                username = normalize_username(username)
            except ValueError as exc:
                raise AccountError("invalid_username", 422, str(exc)) from exc

        async with self.sessions.begin() as db:
            await self._user(db, user_id, account_id, expected_version)
            credential = await self._credential(db, user_id)
            old_username = credential.username if credential else None
            old_hash = credential.hashed_password if credential else None
        if old_username is not None and old_hash is not None:
            if username is not None and username != old_username:
                raise AccountError(
                    "username_immutable", 422, "An existing username cannot be changed"
                )
            username = old_username
            if current_password is None:
                raise AccountError(
                    "current_password_required", 400, "Current password is required"
                )
            if not await run_in_threadpool(verify_password, current_password, old_hash):
                raise AccountError(
                    "invalid_current_password", 400, "Current password is incorrect"
                )
        elif username is None:
            raise AccountError("username_required", 422, "Username is required")
        hashed_password = await run_in_threadpool(hash_password, password)

        try:
            async with self.sessions.begin() as db:
                user = await self._user(
                    db, user_id, account_id, expected_version, lock=True
                )
                credential = await self._credential(db, user_id, lock=True)
                if (credential.username if credential else None) != old_username or (
                    credential.hashed_password if credential else None
                ) != old_hash:
                    raise AccountError(
                        "account_changed",
                        409,
                        "Account changed; sign in again and retry",
                    )
                password_identities = [
                    item
                    for item in await self._identities(db, user_id)
                    if item.provider == "password"
                ]
                if credential is not None:
                    if len(password_identities) != 1 or (
                        password_identities[0].subject != credential.username
                    ):
                        raise AccountError(
                            "account_changed",
                            409,
                            "Account changed; sign in again and retry",
                        )
                    credential.hashed_password = hashed_password
                else:
                    if password_identities:
                        raise AccountError(
                            "account_changed",
                            409,
                            "Account changed; sign in again and retry",
                        )
                    db.add(
                        UserIdentity(
                            id=str(uuid4()),
                            user_id=user_id,
                            provider="password",
                            subject=username,
                        )
                    )
                    db.add(
                        PasswordCredential(
                            user_id=user_id,
                            username=username,
                            hashed_password=hashed_password,
                        )
                    )
                user.auth_version += 1
            return user
        except IntegrityError as exc:
            raise AccountError(
                "username_conflict", 409, "Username is already in use"
            ) from exc
