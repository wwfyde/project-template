"""Persistence for application-owned agent sessions and turns."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AgentSessionRecord(Base):
    __tablename__ = "agent_session"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    document: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    active_turn_id: Mapped[str | None] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentTurnRecord(Base):
    __tablename__ = "agent_turn"
    __table_args__ = (
        Index("ix_agent_turn_session_created_at", "session_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("agent_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    document: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
