"""Add API key usage statistics and audit events.

Revision ID: 20260924_0004
Revises: 20260924_0003
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260924_0004"
down_revision = "20260924_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    api_key_columns = {
        column["name"] for column in inspector.get_columns("api_keys")
    }

    with op.batch_alter_table("api_keys") as batch:
        if "last_used_ip" not in api_key_columns:
            batch.add_column(sa.Column("last_used_ip", sa.String(length=64)))
        if "usage_count" not in api_key_columns:
            batch.add_column(
                sa.Column(
                    "usage_count",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )

    if "audit_events" not in tables:
        op.create_table(
            "audit_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("api_key_id", sa.String(length=36), nullable=True),
            sa.Column("request_id", sa.String(length=128), nullable=False),
            sa.Column("method", sa.String(length=16), nullable=False),
            sa.Column("path", sa.String(length=512), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("client_ip", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_audit_events_owner_id", "audit_events", ["owner_id"])
        op.create_index("ix_audit_events_api_key_id", "audit_events", ["api_key_id"])
        op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])
        op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "audit_events" in tables:
        op.drop_index("ix_audit_events_created_at", table_name="audit_events")
        op.drop_index("ix_audit_events_request_id", table_name="audit_events")
        op.drop_index("ix_audit_events_api_key_id", table_name="audit_events")
        op.drop_index("ix_audit_events_owner_id", table_name="audit_events")
        op.drop_table("audit_events")

    api_key_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("api_keys")
    }
    with op.batch_alter_table("api_keys") as batch:
        if "usage_count" in api_key_columns:
            batch.drop_column("usage_count")
        if "last_used_ip" in api_key_columns:
            batch.drop_column("last_used_ip")
