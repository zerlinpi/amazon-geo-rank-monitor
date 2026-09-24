"""Add human accounts, workspace memberships, sessions and invitations.

Revision ID: 20260924_0005
Revises: 20260924_0004
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260924_0005"
down_revision = "20260924_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("password_hash", sa.String(length=512), nullable=False),
            sa.Column("display_name", sa.String(length=200), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "workspace_memberships" not in tables:
        op.create_table(
            "workspace_memberships",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["owner_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "owner_id",
                "user_id",
                name="uq_workspace_membership",
            ),
        )
        op.create_index(
            "ix_workspace_memberships_owner_id",
            "workspace_memberships",
            ["owner_id"],
        )
        op.create_index(
            "ix_workspace_memberships_user_id",
            "workspace_memberships",
            ["user_id"],
        )

    if "user_sessions" not in tables:
        op.create_table(
            "user_sessions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["owner_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
        op.create_index("ix_user_sessions_owner_id", "user_sessions", ["owner_id"])
        op.create_index(
            "ix_user_sessions_token_hash",
            "user_sessions",
            ["token_hash"],
            unique=True,
        )

    if "workspace_invitations" not in tables:
        op.create_table(
            "workspace_invitations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["owner_id"], ["tenants.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["created_by_user_id"],
                ["users.id"],
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index(
            "ix_workspace_invitations_owner_id",
            "workspace_invitations",
            ["owner_id"],
        )
        op.create_index(
            "ix_workspace_invitations_email",
            "workspace_invitations",
            ["email"],
        )
        op.create_index(
            "ix_workspace_invitations_token_hash",
            "workspace_invitations",
            ["token_hash"],
            unique=True,
        )

    audit_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("audit_events")
    }
    with op.batch_alter_table("audit_events") as batch:
        if "user_id" not in audit_columns:
            batch.add_column(sa.Column("user_id", sa.String(length=36)))
            batch.create_index("ix_audit_events_user_id", ["user_id"])
        if "actor_type" not in audit_columns:
            batch.add_column(
                sa.Column(
                    "actor_type",
                    sa.String(length=24),
                    nullable=False,
                    server_default="api_key",
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    audit_columns = {
        column["name"] for column in inspector.get_columns("audit_events")
    }

    with op.batch_alter_table("audit_events") as batch:
        if "user_id" in audit_columns:
            batch.drop_index("ix_audit_events_user_id")
            batch.drop_column("user_id")
        if "actor_type" in audit_columns:
            batch.drop_column("actor_type")

    for table in (
        "workspace_invitations",
        "user_sessions",
        "workspace_memberships",
        "users",
    ):
        if table in tables:
            op.drop_table(table)
