"""Add TOTP MFA, trusted devices and workspace MFA policy.

Revision ID: 20260925_0008
Revises: 20260925_0007
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260925_0008"
down_revision = "20260925_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    tenant_columns = {
        column["name"] for column in inspector.get_columns("tenants")
    }
    with op.batch_alter_table("tenants") as batch:
        if "require_mfa" not in tenant_columns:
            batch.add_column(
                sa.Column(
                    "require_mfa",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )

    user_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("users")
    }
    with op.batch_alter_table("users") as batch:
        if "mfa_secret_encrypted" not in user_columns:
            batch.add_column(sa.Column("mfa_secret_encrypted", sa.Text()))
        if "mfa_enabled_at" not in user_columns:
            batch.add_column(sa.Column("mfa_enabled_at", sa.DateTime(timezone=True)))
        if "mfa_last_verified_at" not in user_columns:
            batch.add_column(
                sa.Column("mfa_last_verified_at", sa.DateTime(timezone=True))
            )

    token_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("account_tokens")
    }
    with op.batch_alter_table("account_tokens") as batch:
        if "details" not in token_columns:
            batch.add_column(sa.Column("details", sa.JSON(), nullable=True))

    session_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("user_sessions")
    }
    with op.batch_alter_table("user_sessions") as batch:
        if "mfa_authenticated_at" not in session_columns:
            batch.add_column(
                sa.Column("mfa_authenticated_at", sa.DateTime(timezone=True))
            )

    if "mfa_recovery_codes" not in tables:
        op.create_table(
            "mfa_recovery_codes",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("code_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code_hash"),
        )
        op.create_index(
            "ix_mfa_recovery_codes_user_id",
            "mfa_recovery_codes",
            ["user_id"],
        )
        op.create_index(
            "ix_mfa_recovery_codes_code_hash",
            "mfa_recovery_codes",
            ["code_hash"],
            unique=True,
        )

    if "trusted_devices" not in tables:
        op.create_table(
            "trusted_devices",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index(
            "ix_trusted_devices_user_id",
            "trusted_devices",
            ["user_id"],
        )
        op.create_index(
            "ix_trusted_devices_token_hash",
            "trusted_devices",
            ["token_hash"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "trusted_devices" in tables:
        op.drop_index("ix_trusted_devices_token_hash", table_name="trusted_devices")
        op.drop_index("ix_trusted_devices_user_id", table_name="trusted_devices")
        op.drop_table("trusted_devices")

    if "mfa_recovery_codes" in tables:
        op.drop_index(
            "ix_mfa_recovery_codes_code_hash",
            table_name="mfa_recovery_codes",
        )
        op.drop_index(
            "ix_mfa_recovery_codes_user_id",
            table_name="mfa_recovery_codes",
        )
        op.drop_table("mfa_recovery_codes")

    session_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("user_sessions")
    }
    with op.batch_alter_table("user_sessions") as batch:
        if "mfa_authenticated_at" in session_columns:
            batch.drop_column("mfa_authenticated_at")

    token_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("account_tokens")
    }
    with op.batch_alter_table("account_tokens") as batch:
        if "details" in token_columns:
            batch.drop_column("details")

    user_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("users")
    }
    with op.batch_alter_table("users") as batch:
        for name in (
            "mfa_last_verified_at",
            "mfa_enabled_at",
            "mfa_secret_encrypted",
        ):
            if name in user_columns:
                batch.drop_column(name)

    tenant_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("tenants")
    }
    with op.batch_alter_table("tenants") as batch:
        if "require_mfa" in tenant_columns:
            batch.drop_column("require_mfa")
