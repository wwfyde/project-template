"""Local credentials belong to stable users, independently of OAuth."""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PasswordCredential(Base):
    __tablename__ = "password_credential"
    __table_args__ = (
        UniqueConstraint("username", name="uq_password_credential_username"),
    )

    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    username: Mapped[str] = mapped_column(String(64))
    hashed_password: Mapped[str] = mapped_column(String(255))
