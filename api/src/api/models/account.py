"""Accounts own resources; their structure determines how people participate."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint(
            "structure IN ('personal', 'workspace')", name="ck_account_structure"
        ),
        CheckConstraint(
            "(structure = 'personal' AND personal_user_id IS NOT NULL) OR "
            "(structure = 'workspace' AND personal_user_id IS NULL)",
            name="ck_account_personal_user",
        ),
        UniqueConstraint("personal_user_id", name="uq_account_personal_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    structure: Mapped[str] = mapped_column(
        String(20), default="personal", server_default="personal", nullable=False
    )
    personal_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="RESTRICT")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
