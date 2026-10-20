"""Resource ownership includes both its account and its creating user."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ResourceOwner(Base):
    """Unmapped legacy resources remain inaccessible and cannot be claimed."""

    __tablename__ = "resource_owner"

    resource_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    resource_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("account.id", ondelete="CASCADE"), index=True
    )
