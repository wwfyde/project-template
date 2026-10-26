"""Persist private image assets and positioned comments.

Revision ID: f31a78c4d6e2
Revises: e28b47a1d902
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f31a78c4d6e2"
down_revision = "e28b47a1d902"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "image_asset",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("purpose", sa.String(10), server_default="image", nullable=False),
        sa.Column(
            "document",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "purpose IN ('image', 'mask')", name="ck_image_asset_purpose"
        ),
    )
    op.create_index(
        "ix_image_asset_owner_created_at", "image_asset", ["owner", "created_at", "id"]
    )
    op.create_table(
        "image_comment",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "asset_id",
            sa.String(36),
            sa.ForeignKey("image_asset.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column(
            "document",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_image_comment_owner", "image_comment", ["owner"])
    op.create_index(
        "ix_image_comment_asset_created_at",
        "image_comment",
        ["asset_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_image_comment_asset_created_at", table_name="image_comment")
    op.drop_index("ix_image_comment_owner", table_name="image_comment")
    op.drop_table("image_comment")
    op.drop_index("ix_image_asset_owner_created_at", table_name="image_asset")
    op.drop_table("image_asset")
