"""Persist versioned skills and a durable object-deletion outbox.

Revision ID: a42e9c71b603
Revises: f31a78c4d6e2
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a42e9c71b603"
down_revision = "f31a78c4d6e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(1024), nullable=False),
        sa.Column("default_version", sa.Integer(), nullable=False),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("next_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("default_version > 0", name="ck_skill_default_version"),
        sa.CheckConstraint("latest_version > 0", name="ck_skill_latest_version"),
        sa.CheckConstraint("next_version > latest_version", name="ck_skill_next_version"),
    )
    op.create_index("ix_skill_owner_created_at", "skill", ["owner", "created_at", "id"])
    op.create_table(
        "skill_version",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "skill_id",
            sa.String(64),
            sa.ForeignKey("skill.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(1024), nullable=False),
        sa.Column("archive_key", sa.String(1024), unique=True, nullable=False),
        sa.Column(
            "files", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        sa.CheckConstraint("version > 0", name="ck_skill_version_number"),
    )
    op.create_index(
        "uq_skill_version_number", "skill_version", ["skill_id", "version"], unique=True
    )
    op.create_table(
        "skill_object_deletion",
        sa.Column("archive_key", sa.String(1024), primary_key=True),
        sa.Column("last_attempt_at", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("skill_object_deletion")
    op.drop_index("uq_skill_version_number", table_name="skill_version")
    op.drop_table("skill_version")
    op.drop_index("ix_skill_owner_created_at", table_name="skill")
    op.drop_table("skill")
