import uuid
from datetime import datetime

from sqlalchemy import UUID, Boolean, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Agent(Base):
    __tablename__ = "agent"
    __table_args__ = (
        Index("idx_agent_name", "name"),
        Index("idx_agent_api_key_hash", "api_key_hash"),
        Index("idx_agent_claim_token", "claim_token"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuidv7()"),
        comment="ID",
    )
    name: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, comment="Name"
    )
    display_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Display name"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Description"
    )
    avatar_url: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Avatar URL"
    )
    metadata = mapped_column(Text, nullable=True, comment="Metadata")

    api_key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="API key hash"
    )
    claim_token: Mapped[str | None] = mapped_column(
        String(80), nullable=True, comment="Claim token"
    )
    verification_code: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="Verification code"
    )

    status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        default="pending_claim",
        server_default=text("'pending_claim'"),
        comment="Status",
    )
    is_claimed: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        default=False,
        server_default=text("false"),
        comment="Is claimed",
    )
    is_active: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        default=True,
        server_default=text("true"),
        comment="Is active",
    )

    karma: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0, server_default=text("0"), comment="Karma"
    )
    follower_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        server_default=text("0"),
        comment="Follower count",
    )
    following_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=0,
        server_default=text("0"),
        comment="Following count",
    )

    owner_twitter_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Twitter/X ID"
    )
    owner_twitter_handle: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Twitter/X handle"
    )

    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=func.now(),
        server_default=func.now(),
        comment="Created at",
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
        comment="Updated at",
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Claimed at"
    )
    last_active: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=func.now(),
        server_default=func.now(),
        comment="Last active",
    )
