"""Private image bytes and comments, separate from the public file directory."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ImageAssetRecord(Base):
    __tablename__ = "image_asset"
    __table_args__ = (
        CheckConstraint("purpose IN ('image', 'mask')", name="ck_image_asset_purpose"),
        Index("ix_image_asset_owner_created_at", "owner", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(10), nullable=False, default="image", server_default="image"
    )
    document: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ImageCommentRecord(Base):
    __tablename__ = "image_comment"
    __table_args__ = (
        Index("ix_image_comment_owner", "owner"),
        Index("ix_image_comment_asset_created_at", "asset_id", "created_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("image_asset.id", ondelete="CASCADE"), nullable=False
    )
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    document: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
