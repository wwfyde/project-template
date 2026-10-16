"""Local password credentials associated with stable authentication users.

Revision ID: da72e4b18c09
Revises: c36f109ab672
"""

from alembic import op
import sqlalchemy as sa

revision = "da72e4b18c09"
down_revision = "c36f109ab672"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_password_credential",
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("auth_user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.UniqueConstraint("username", name="uq_auth_password_username"),
    )


def downgrade() -> None:
    op.drop_table("auth_password_credential")
