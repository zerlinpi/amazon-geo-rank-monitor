"""Add API key scopes and worker heartbeat state.

Revision ID: 20260924_0002
Revises: 20260924_0001
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260924_0002"
down_revision = "20260924_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    api_key_columns = {
        column["name"] for column in inspector.get_columns("api_keys")
    }
    if "scopes" not in api_key_columns:
        op.add_column(
            "api_keys",
            sa.Column(
                "scopes",
                sa.JSON(),
                nullable=False,
                server_default='["*"]',
            ),
        )

    if "worker_heartbeats" not in tables:
        op.create_table(
            "worker_heartbeats",
            sa.Column("worker_id", sa.String(length=128), nullable=False),
            sa.Column("worker_type", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("last_job_id", sa.String(length=36), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("processed_jobs", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("worker_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "worker_heartbeats" in tables:
        op.drop_table("worker_heartbeats")

    api_key_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("api_keys")
    }
    if "scopes" in api_key_columns:
        op.drop_column("api_keys", "scopes")
