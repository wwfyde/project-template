"""Global users, personal/workspace accounts, and account memberships.

Revision ID: e28b47a1d902
Revises: da72e4b18c09

The private legacy-scope table retains original tenant identifiers for rollback.
Upgrade rejects inconsistent ownership before making any changes. Downgrade
rejects account state the old one-tenant-per-user schema cannot represent.
This data migration requires an online connection; offline SQL is unsupported.
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import Connection

revision = "e28b47a1d902"
down_revision = "da72e4b18c09"
branch_labels = None
depends_on = None


def _require_online() -> Connection:
    if op.get_context().as_sql:
        raise RuntimeError(
            "The user/account data migration requires an online connection"
        )
    return op.get_bind()


def _check_legacy_ownership(connection: Connection) -> None:
    inconsistent = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM auth_resource_owner AS resource "
            "LEFT JOIN auth_user AS person ON person.id = resource.user_id "
            "WHERE person.id IS NULL OR resource.tenant_id <> person.tenant_id"
        )
    ).scalar_one()
    if inconsistent:
        raise RuntimeError(
            f"Cannot migrate {inconsistent} resource ownership rows whose user/tenant "
            "scope is inconsistent. Reconcile them before upgrading; no rows were changed."
        )


def _check_personal_only(connection: Connection) -> None:
    checks = (
        "SELECT COUNT(*) FROM account WHERE structure <> 'personal'",
        "SELECT COUNT(*) FROM account_member AS member "
        "JOIN account ON account.id = member.account_id "
        "WHERE member.role <> 'owner' OR member.user_id <> account.personal_user_id",
        'SELECT COUNT(*) FROM "user" AS person '
        "LEFT JOIN account ON account.personal_user_id = person.id "
        "WHERE account.id IS NULL",
        "SELECT COUNT(*) FROM account "
        "LEFT JOIN account_member AS member ON member.account_id = account.id "
        "AND member.user_id = account.personal_user_id AND member.role = 'owner' "
        "WHERE member.user_id IS NULL",
        "SELECT COUNT(*) FROM resource_owner AS resource "
        "JOIN account ON account.id = resource.account_id "
        "WHERE resource.user_id <> account.personal_user_id",
        'SELECT COUNT(*) FROM account JOIN "user" AS person '
        "ON person.id = account.personal_user_id "
        "WHERE account.is_active = false OR "
        "(account.name IS NOT NULL AND account.name <> person.display_name)",
    )
    if any(connection.execute(sa.text(query)).scalar_one() for query in checks):
        raise RuntimeError(
            "Cannot downgrade accounts that contain workspace, shared membership, "
            "reassigned ownership, or account-specific state. Export or reconcile "
            "that state before downgrading; no rows were changed."
        )


def _rename_unique(
    table: str, old_name: str, new_name: str, columns: list[str]
) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(old_name, type_="unique")
        batch.create_unique_constraint(new_name, columns)


def _rename_index(table: str, old_name: str, new_name: str, column: str) -> None:
    op.drop_index(old_name, table_name=table)
    op.create_index(new_name, table, [column])


def upgrade() -> None:
    connection = _require_online()
    if connection.dialect.name == "postgresql":
        # Keep the validation and data snapshot consistent with the DDL/backfill.
        connection.execute(
            sa.text(
                "LOCK TABLE auth_user, auth_identity, auth_password_credential, "
                "auth_resource_owner IN ACCESS EXCLUSIVE MODE"
            )
        )
    _check_legacy_ownership(connection)
    users = (
        connection.execute(
            sa.text("SELECT id, tenant_id, display_name, created_at FROM auth_user")
        )
        .mappings()
        .all()
    )

    op.rename_table("auth_user", "user")
    op.rename_table("auth_identity", "user_identity")
    op.rename_table("auth_password_credential", "password_credential")
    op.rename_table("auth_resource_owner", "resource_owner")
    _rename_unique(
        "user_identity",
        "uq_auth_identity_provider_subject",
        "uq_user_identity_provider_subject",
        ["provider", "subject"],
    )
    _rename_unique(
        "password_credential",
        "uq_auth_password_username",
        "uq_password_credential_username",
        ["username"],
    )
    _rename_index(
        "user_identity",
        "ix_auth_identity_user_id",
        "ix_user_identity_user_id",
        "user_id",
    )
    _rename_index(
        "resource_owner",
        "ix_auth_resource_owner_user_id",
        "ix_resource_owner_user_id",
        "user_id",
    )
    op.create_table(
        "_account_legacy_scope",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
    )
    op.create_table(
        "account",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255)),
        sa.Column(
            "structure", sa.String(20), server_default="personal", nullable=False
        ),
        sa.Column(
            "personal_user_id",
            sa.String(36),
            sa.ForeignKey("user.id", ondelete="RESTRICT"),
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "structure IN ('personal', 'workspace')", name="ck_account_structure"
        ),
        sa.CheckConstraint(
            "(structure = 'personal' AND personal_user_id IS NOT NULL) OR "
            "(structure = 'workspace' AND personal_user_id IS NULL)",
            name="ck_account_personal_user",
        ),
        sa.UniqueConstraint("personal_user_id", name="uq_account_personal_user_id"),
    )
    op.create_table(
        "account_member",
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("account.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(20), server_default="member", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name="ck_account_member_role"
        ),
    )
    op.create_index("ix_account_member_user_id", "account_member", ["user_id"])
    op.add_column("resource_owner", sa.Column("account_id", sa.String(36)))
    for user in users:
        account_id = str(uuid4())
        connection.execute(
            sa.text(
                "INSERT INTO _account_legacy_scope (user_id, tenant_id) "
                "VALUES (:user_id, :tenant_id)"
            ),
            {"user_id": user["id"], "tenant_id": user["tenant_id"]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO account "
                "(id, name, structure, personal_user_id, is_active, created_at) "
                "VALUES (:id, :name, 'personal', :user_id, true, :created_at)"
            ),
            {
                "id": account_id,
                "name": user["display_name"],
                "user_id": user["id"],
                "created_at": user["created_at"],
            },
        )
        connection.execute(
            sa.text(
                "INSERT INTO account_member (account_id, user_id, role, created_at) "
                "VALUES (:account_id, :user_id, 'owner', :created_at)"
            ),
            {
                "account_id": account_id,
                "user_id": user["id"],
                "created_at": user["created_at"],
            },
        )
        connection.execute(
            sa.text(
                "UPDATE resource_owner SET account_id = :account_id "
                "WHERE user_id = :user_id AND tenant_id = :tenant_id"
            ),
            {
                "account_id": account_id,
                "user_id": user["id"],
                "tenant_id": user["tenant_id"],
            },
        )
    with op.batch_alter_table("resource_owner") as batch:
        batch.drop_index("ix_auth_resource_owner_tenant_id")
        batch.drop_column("tenant_id")
        batch.alter_column("account_id", existing_type=sa.String(36), nullable=False)
        batch.create_foreign_key(
            "fk_resource_owner_account_id",
            "account",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_resource_owner_account_id", ["account_id"])
    with op.batch_alter_table("user") as batch:
        batch.drop_index("ix_auth_user_tenant_id")
        batch.drop_column("tenant_id")
    connection.execute(sa.text('UPDATE "user" SET auth_version = auth_version + 1'))


def downgrade() -> None:
    connection = _require_online()
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                'LOCK TABLE "user", account, account_member, resource_owner, '
                "user_identity, password_credential IN ACCESS EXCLUSIVE MODE"
            )
        )
    _check_personal_only(connection)
    users = (
        connection.execute(
            sa.text(
                "SELECT person.id, COALESCE(legacy.tenant_id, account.id) AS tenant_id "
                'FROM "user" AS person '
                "JOIN account ON account.personal_user_id = person.id "
                "LEFT JOIN _account_legacy_scope AS legacy ON legacy.user_id = person.id"
            )
        )
        .mappings()
        .all()
    )
    op.add_column("user", sa.Column("tenant_id", sa.String(128)))
    op.add_column("resource_owner", sa.Column("tenant_id", sa.String(128)))
    for user in users:
        values = {"user_id": user["id"], "tenant_id": user["tenant_id"]}
        connection.execute(
            sa.text('UPDATE "user" SET tenant_id = :tenant_id WHERE id = :user_id'),
            values,
        )
        connection.execute(
            sa.text(
                "UPDATE resource_owner SET tenant_id = :tenant_id "
                "WHERE user_id = :user_id"
            ),
            values,
        )
    with op.batch_alter_table("resource_owner") as batch:
        batch.drop_constraint("fk_resource_owner_account_id", type_="foreignkey")
        batch.drop_index("ix_resource_owner_account_id")
        batch.drop_column("account_id")
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_index("ix_auth_resource_owner_tenant_id", ["tenant_id"])
    op.drop_table("account_member")
    op.drop_table("account")
    op.drop_table("_account_legacy_scope")
    with op.batch_alter_table("user") as batch:
        batch.alter_column("tenant_id", existing_type=sa.String(128), nullable=False)
        batch.create_index("ix_auth_user_tenant_id", ["tenant_id"])
    connection.execute(sa.text('UPDATE "user" SET auth_version = auth_version + 1'))
    _rename_index(
        "user_identity",
        "ix_user_identity_user_id",
        "ix_auth_identity_user_id",
        "user_id",
    )
    _rename_index(
        "resource_owner",
        "ix_resource_owner_user_id",
        "ix_auth_resource_owner_user_id",
        "user_id",
    )
    _rename_unique(
        "user_identity",
        "uq_user_identity_provider_subject",
        "uq_auth_identity_provider_subject",
        ["provider", "subject"],
    )
    _rename_unique(
        "password_credential",
        "uq_password_credential_username",
        "uq_auth_password_username",
        ["username"],
    )
    op.rename_table("resource_owner", "auth_resource_owner")
    op.rename_table("password_credential", "auth_password_credential")
    op.rename_table("user_identity", "auth_identity")
    op.rename_table("user", "auth_user")
