"""Skill metadata and immutable file manifests; archive bytes live in object storage."""

from typing import Any

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SkillRecord(Base):
    __tablename__ = "skill"
    __table_args__ = (
        Index("ix_skill_owner_created_at", "owner", "created_at", "id"),
        CheckConstraint("default_version > 0", name="ck_skill_default_version"),
        CheckConstraint("latest_version > 0", name="ck_skill_latest_version"),
        CheckConstraint("next_version > latest_version", name="ck_skill_next_version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    default_version: Mapped[int] = mapped_column(Integer, nullable=False)
    latest_version: Mapped[int] = mapped_column(Integer, nullable=False)
    next_version: Mapped[int] = mapped_column(Integer, nullable=False)


class SkillVersionRecord(Base):
    __tablename__ = "skill_version"
    __table_args__ = (
        Index("uq_skill_version_number", "skill_id", "version", unique=True),
        CheckConstraint("version > 0", name="ck_skill_version_number"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    skill_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("skill.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(1024), nullable=False)
    archive_key: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    files: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )


class SkillObjectDeletionRecord(Base):
    """Durable outbox: a failed object deletion can be retried after metadata commits."""

    __tablename__ = "skill_object_deletion"

    archive_key: Mapped[str] = mapped_column(String(1024), primary_key=True)
    last_attempt_at: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
