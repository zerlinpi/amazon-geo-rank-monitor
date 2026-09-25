"""Add email verification, recovery tokens and login security events.

Revision ID: 20260925_0007
Revises: 20260925_0006
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260925_0007"
down_revision = "20260925_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    user_columns = {
        column["name"] for column in inspector.get_columns("users")
    }

    with op.batch_alter_table("users") as batch:
        if "email_verified_at" not in user_columns:
            batch.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True)))
        if "failed_login_count" not in user_columns:
            batch.add_column(
                sa.Column(
                    "failed_login_count",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
        if "locked_until" not in user_columns:
            batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True)))
        if "last_login_at" not in user_columns:
            batch.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True)))
        if "last_login_ip" not in user_columns:
            batch.add_column(sa.Column("last_login_ip", sa.String(length=64)))

    op.execute(
        sa.text(
            "UPDATE users "
            "SET email_verified_at = created_at "
            "WHERE email_verified_at IS NULL"
        )
    )

    if "account_tokens" not in tables:
        op.create_table(
            "account_tokens",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("token_type", sa.String(length=32), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index("ix_account_tokens_user_id", "account_tokens", ["user_id"])
        op.create_index(
            "ix_account_tokens_token_type",
            "account_tokens",
            ["token_type"],
        )
        op.create_index(
            "ix_account_tokens_token_hash",
            "account_tokens",
            ["token_hash"],
            unique=True,
        )

    if "auth_events" not in tables:
        op.create_table(
            "auth_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("success", sa.Boolean(), nullable=False),
            sa.Column("client_ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_auth_events_user_id", "auth_events", ["user_id"])
        op.create_index("ix_auth_events_email", "auth_events", ["email"])
        op.create_index("ix_auth_events_event_type", "auth_events", ["event_type"])
        op.create_index("ix_auth_events_created_at", "auth_events", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "auth_events" in tables:
        op.drop_index("ix_auth_events_created_at", table_name="auth_events")
        op.drop_index("ix_auth_events_event_type", table_name="auth_events")
        op.drop_index("ix_auth_events_email", table_name="auth_events")
        op.drop_index("ix_auth_events_user_id", table_name="auth_events")
        op.drop_table("auth_events")

    if "account_tokens" in tables:
        op.drop_index("ix_account_tokens_token_hash", table_name="account_tokens")
        op.drop_index("ix_account_tokens_token_type", table_name="account_tokens")
        op.drop_index("ix_account_tokens_user_id", table_name="account_tokens")
        op.drop_table("account_tokens")

    user_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("users")
    }
    with op.batch_alter_table("users") as batch:
        for name in (
            "last_login_ip",
            "last_login_at",
            "locked_until",
            "failed_login_count",
            "email_verified_at",
        ):
            if name in user_columns:
                batch.drop_column(name)
