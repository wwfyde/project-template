"""Local users are stable; external provider subjects are separate identities."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class User(Base):
    __tablename__ = "auth_user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(String(2048))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserIdentity(Base):
    __tablename__ = "auth_identity"
    __table_args__ = (
        UniqueConstraint(
            "provider", "subject", name="uq_auth_identity_provider_subject"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("auth_user.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(80))
    subject: Mapped[str] = mapped_column(String(255))


class PasswordCredential(Base):
    """Local credentials belong to stable users, independently of OAuth."""

    __tablename__ = "auth_password_credential"
    __table_args__ = (UniqueConstraint("username", name="uq_auth_password_username"),)

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("auth_user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    username: Mapped[str] = mapped_column(String(64))
    hashed_password: Mapped[str] = mapped_column(String(255))


class ResourceOwner(Base):
    """Ownership for existing resources without rewriting their storage engines.

    Legacy resources without a mapping are inaccessible. No automatic claiming
    by a caller-supplied ID; mappings are written only during resource creation.
    """

    __tablename__ = "auth_resource_owner"

    resource_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("auth_user.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), index=True)
