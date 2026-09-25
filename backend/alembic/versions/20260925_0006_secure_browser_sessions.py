"""Add CSRF and device metadata to user sessions.

Revision ID: 20260925_0006
Revises: 20260924_0005
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260925_0006"
down_revision = "20260924_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("user_sessions")
    }
    with op.batch_alter_table("user_sessions") as batch:
        if "csrf_hash" not in columns:
            batch.add_column(
                sa.Column(
                    "csrf_hash",
                    sa.String(length=64),
                    nullable=False,
                    server_default="",
                )
            )
        if "created_ip" not in columns:
            batch.add_column(sa.Column("created_ip", sa.String(length=64)))
        if "last_seen_ip" not in columns:
            batch.add_column(sa.Column("last_seen_ip", sa.String(length=64)))
        if "user_agent" not in columns:
            batch.add_column(sa.Column("user_agent", sa.String(length=512)))


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("user_sessions")
    }
    with op.batch_alter_table("user_sessions") as batch:
        for name in ("user_agent", "last_seen_ip", "created_ip", "csrf_hash"):
            if name in columns:
                batch.drop_column(name)
