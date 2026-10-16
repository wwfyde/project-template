"""Stable users, external identities and ownership of existing resources.

Revision ID: c36f109ab672
Revises: 8d50b113df31
"""

from alembic import op
import sqlalchemy as sa

revision = "c36f109ab672"
down_revision = "8d50b113df31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_user",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("avatar_url", sa.String(2048)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(32)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_auth_user_tenant_id", "auth_user", ["tenant_id"])
    op.create_table(
        "auth_identity",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("auth_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.UniqueConstraint(
            "provider", "subject", name="uq_auth_identity_provider_subject"
        ),
    )
    op.create_index("ix_auth_identity_user_id", "auth_identity", ["user_id"])
    op.create_table(
        "auth_resource_owner",
        sa.Column("resource_type", sa.String(32), primary_key=True),
        sa.Column("resource_id", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("auth_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(128), nullable=False),
    )
    op.create_index(
        "ix_auth_resource_owner_user_id", "auth_resource_owner", ["user_id"]
    )
    op.create_index(
        "ix_auth_resource_owner_tenant_id", "auth_resource_owner", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_table("auth_resource_owner")
    op.drop_table("auth_identity")
    op.drop_table("auth_user")
