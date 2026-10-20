"""A user's membership and role in an account."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AccountMember(Base):
    __tablename__ = "account_member"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name="ck_account_member_role"
        ),
    )

    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("account.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20), default="member", server_default="member", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
