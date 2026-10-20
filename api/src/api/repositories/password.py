"""Password verification and provisioning share the application's user store.

Credential changes are serialized under user-then-credential row locks. Login
verifies a snapshot outside a transaction and rechecks it under those locks, so a
concurrent password reset cannot authorize an old password with a new version.
"""

import re
import unicodedata
from uuid import uuid4

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from api.models import PasswordCredential, User, UserIdentity
from api.repositories.account import create_personal_account

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024
MAX_PASSWORD_BYTES = 4096
_USERNAME = re.compile(r"[a-z0-9_.@-]{3,64}\Z", re.ASCII)
_PASSWORD_HASH = PasswordHash((Argon2Hasher(), BcryptHasher()))
# A public dummy hash equalizes the expensive work for nonexistent accounts.
# It never represents a user credential and cannot authenticate an account.
_DUMMY_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$3ONIIcBtkzipo/s0SznQ4g"
    "$+XSs4+gucu+48hs/fwgKtYBMyflOznFPWEdVo6tg2ys"
)


class PasswordUserExists(ValueError):
    pass


class PasswordUserNotFound(ValueError):
    pass


def normalize_username(username: str) -> str:
    if not username.isascii():
        raise ValueError("Username must contain only ASCII characters")
    normalized = username.strip().lower()
    if not _USERNAME.fullmatch(normalized):
        raise ValueError(
            "Username must contain 3 to 64 ASCII letters, numbers, _, ., @ or -"
        )
    return normalized


def _valid_login_password(password: str) -> bool:
    try:
        return (
            0 < len(password) <= MAX_PASSWORD_LENGTH
            and len(password.encode("utf-8")) <= MAX_PASSWORD_BYTES
        )
    except UnicodeEncodeError:
        return False


def validate_new_password(password: str) -> str:
    if not _valid_login_password(password) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            "Password must contain 12 to 1024 characters and at most 4096 UTF-8 bytes"
        )
    return password


def _verify_password(password: str, hashed_password: str) -> tuple[bool, str | None]:
    # Legacy bcrypt silently truncates in some versions. Reject rather than
    # accepting a different password that shares the same first 72 bytes.
    if (
        hashed_password.startswith(("$2a$", "$2b$", "$2y$"))
        and len(password.encode("utf-8")) > 72
    ):
        _PASSWORD_HASH.verify(password, _DUMMY_HASH)
        return False, None
    try:
        return _PASSWORD_HASH.verify_and_update(password, hashed_password)
    except UnknownHashError, ValueError:
        # A corrupt credential is an authentication failure, not a server error.
        _PASSWORD_HASH.verify(password, _DUMMY_HASH)
        return False, None


def hash_password(password: str) -> str:
    """Hash a validated new password; callers must run this in a worker thread."""
    return _PASSWORD_HASH.hash(validate_new_password(password))


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify an existing credential without persisting an optional hash upgrade."""
    if not _valid_login_password(password):
        return False
    return _verify_password(password, hashed_password)[0]


class PasswordRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def authenticate(self, username: str, password: str) -> User | None:
        if not _valid_login_password(password):
            return None
        try:
            username = normalize_username(username)
        except ValueError:
            await run_in_threadpool(_verify_password, password, _DUMMY_HASH)
            return None
        async with self.sessions.begin() as db:
            row = (
                await db.execute(
                    select(User, PasswordCredential)
                    .join(PasswordCredential)
                    .join(UserIdentity, UserIdentity.user_id == User.id)
                    .where(
                        PasswordCredential.username == username,
                        UserIdentity.provider == "password",
                        UserIdentity.subject == username,
                    )
                )
            ).one_or_none()
            if row is not None:
                user, credential = row
                user_id = user.id
                version = user.auth_version
                hashed_password = credential.hashed_password
            else:
                hashed_password = _DUMMY_HASH
        valid, upgraded_hash = await run_in_threadpool(
            _verify_password, password, hashed_password
        )
        if row is None or not valid:
            return None

        async with self.sessions.begin() as db:
            # Match set_password's lock ordering. Hashing never holds DB locks.
            user = (
                await db.execute(
                    select(User).where(User.id == user_id).with_for_update()
                )
            ).scalar_one_or_none()
            credential = (
                await db.execute(
                    select(PasswordCredential)
                    .where(PasswordCredential.user_id == user_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if (
                user is None
                or credential is None
                or not user.is_active
                or user.auth_version != version
                or credential.username != username
                or credential.hashed_password != hashed_password
            ):
                return None
            if upgraded_hash is not None:
                # CAS also protects against a concurrent credential writer that
                # does not participate in the repository's locking convention.
                result = await db.execute(
                    update(PasswordCredential)
                    .where(
                        PasswordCredential.user_id == user_id,
                        PasswordCredential.hashed_password == hashed_password,
                    )
                    .values(hashed_password=upgraded_hash)
                    .returning(PasswordCredential.user_id)
                )
                if result.scalar_one_or_none() is None:
                    return None
            return user

    async def create_user(
        self,
        username: str,
        password: str,
        *,
        display_name: str,
    ) -> User:
        username = normalize_username(username)
        validate_new_password(password)
        if any(unicodedata.category(char) in {"Cc", "Cs"} for char in display_name):
            raise ValueError(
                "Display name cannot contain control or invalid Unicode characters"
            )
        display_name = display_name.strip()
        if not display_name or len(display_name) > 255:
            raise ValueError("Display name must contain 1 to 255 characters")
        hashed_password = await run_in_threadpool(_PASSWORD_HASH.hash, password)
        try:
            async with self.sessions.begin() as db:
                user = User(
                    id=str(uuid4()),
                    display_name=display_name,
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
                        provider="password",
                        subject=username,
                    )
                )
                db.add(
                    PasswordCredential(
                        user_id=user.id,
                        username=username,
                        hashed_password=hashed_password,
                    )
                )
            return user
        except IntegrityError as exc:
            async with self.sessions.begin() as db:
                existing = (
                    await db.execute(
                        select(UserIdentity.user_id).where(
                            UserIdentity.provider == "password",
                            UserIdentity.subject == username,
                        )
                    )
                ).scalar_one_or_none()
            if existing is not None:
                raise PasswordUserExists("Username already exists") from exc
            raise

    async def set_password(self, username: str, password: str) -> None:
        username = normalize_username(username)
        validate_new_password(password)
        hashed_password = await run_in_threadpool(_PASSWORD_HASH.hash, password)
        async with self.sessions.begin() as db:
            user_id = (
                await db.execute(
                    select(PasswordCredential.user_id).where(
                        PasswordCredential.username == username
                    )
                )
            ).scalar_one_or_none()
            if user_id is None:
                raise PasswordUserNotFound("Username does not exist")
            user = (
                await db.execute(
                    select(User).where(User.id == user_id).with_for_update()
                )
            ).scalar_one_or_none()
            credential = (
                await db.execute(
                    select(PasswordCredential)
                    .where(PasswordCredential.user_id == user_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if user is None or credential is None or credential.username != username:
                raise PasswordUserNotFound("Username does not exist")
            credential.hashed_password = hashed_password
            user.auth_version += 1
