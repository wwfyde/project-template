"""Persist agent sessions and leased turns.

Revision ID: 8d50b113df31
Revises: 56f837de55b5
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "8d50b113df31"
down_revision: str | Sequence[str] | None = "56f837de55b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_session",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column(
            "document",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("active_turn_id", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "agent_turn",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column(
            "document",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_session.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_turn_session_created_at",
        "agent_turn",
        ["session_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_turn_session_created_at", table_name="agent_turn")
    op.drop_table("agent_turn")
    op.drop_table("agent_session")
