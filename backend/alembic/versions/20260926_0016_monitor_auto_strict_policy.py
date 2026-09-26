"""Add monitor-level automatic strict verification policy.

Revision ID: 20260926_0016
Revises: 20260926_0015
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260926_0016"
down_revision = "20260926_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "monitor_targets" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("monitor_targets")
    }
    if "auto_strict_enabled" not in columns:
        op.add_column(
            "monitor_targets",
            sa.Column("auto_strict_enabled", sa.Boolean(), nullable=True),
        )
    if "auto_strict_min_confidence" not in columns:
        op.add_column(
            "monitor_targets",
            sa.Column(
                "auto_strict_min_confidence",
                sa.Numeric(precision=5, scale=4),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "monitor_targets" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("monitor_targets")
    }
    if "auto_strict_min_confidence" in columns:
        op.drop_column("monitor_targets", "auto_strict_min_confidence")
    if "auto_strict_enabled" in columns:
        op.drop_column("monitor_targets", "auto_strict_enabled")
