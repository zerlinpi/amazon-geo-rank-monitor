"""Add workspace OIDC SSO configuration and identity bindings.

Revision ID: 20260925_0009
Revises: 20260925_0008
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260925_0009"
down_revision = "20260925_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    session_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("user_sessions")
    }
    with op.batch_alter_table("user_sessions") as batch:
        if "auth_method" not in session_columns:
            batch.add_column(
                sa.Column(
                    "auth_method",
                    sa.String(length=32),
                    nullable=False,
                    server_default="local",
                )
            )
        if "sso_owner_id" not in session_columns:
            batch.add_column(sa.Column("sso_owner_id", sa.String(length=36)))

    if "workspace_sso_configs" not in tables:
        op.create_table(
            "workspace_sso_configs",
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column(
                "provider_type",
                sa.String(length=32),
                nullable=False,
                server_default="oidc",
            ),
            sa.Column(
                "display_name",
                sa.String(length=200),
                nullable=False,
                server_default="Enterprise SSO",
            ),
            sa.Column("issuer_url", sa.String(length=512), nullable=False),
            sa.Column("client_id", sa.String(length=512), nullable=False),
            sa.Column("client_secret_encrypted", sa.Text(), nullable=False),
            sa.Column("email_domains", sa.JSON(), nullable=False),
            sa.Column(
                "auto_join",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "enforce_sso",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["owner_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("owner_id"),
        )

    if "sso_login_transactions" not in tables:
        op.create_table(
            "sso_login_transactions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("state_hash", sa.String(length=64), nullable=False),
            sa.Column("nonce_hash", sa.String(length=64), nullable=False),
            sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
            sa.Column("email_hint", sa.String(length=320), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["owner_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("state_hash"),
        )
        op.create_index(
            "ix_sso_login_transactions_owner_id",
            "sso_login_transactions",
            ["owner_id"],
        )
        op.create_index(
            "ix_sso_login_transactions_state_hash",
            "sso_login_transactions",
            ["state_hash"],
            unique=True,
        )

    if "sso_identities" not in tables:
        op.create_table(
            "sso_identities",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("issuer", sa.String(length=512), nullable=False),
            sa.Column("subject", sa.String(length=512), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["owner_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "owner_id",
                "issuer",
                "subject",
                name="uq_sso_identity_subject",
            ),
            sa.UniqueConstraint(
                "owner_id",
                "user_id",
                name="uq_sso_identity_workspace_user",
            ),
        )
        op.create_index("ix_sso_identities_owner_id", "sso_identities", ["owner_id"])
        op.create_index("ix_sso_identities_user_id", "sso_identities", ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "sso_identities" in tables:
        op.drop_index("ix_sso_identities_user_id", table_name="sso_identities")
        op.drop_index("ix_sso_identities_owner_id", table_name="sso_identities")
        op.drop_table("sso_identities")

    if "sso_login_transactions" in tables:
        op.drop_index(
            "ix_sso_login_transactions_state_hash",
            table_name="sso_login_transactions",
        )
        op.drop_index(
            "ix_sso_login_transactions_owner_id",
            table_name="sso_login_transactions",
        )
        op.drop_table("sso_login_transactions")

    if "workspace_sso_configs" in tables:
        op.drop_table("workspace_sso_configs")

    session_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("user_sessions")
    }
    with op.batch_alter_table("user_sessions") as batch:
        if "sso_owner_id" in session_columns:
            batch.drop_column("sso_owner_id")
        if "auth_method" in session_columns:
            batch.drop_column("auth_method")
