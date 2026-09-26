"""Add workspace automatic strict verification policy.

Revision ID: 20260926_0018
Revises: 20260926_0017
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260926_0018"
down_revision = "20260926_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tenants" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("tenants")
    }
    if "auto_strict_enabled" not in columns:
        op.add_column(
            "tenants",
            sa.Column("auto_strict_enabled", sa.Boolean(), nullable=True),
        )
    if "auto_strict_min_confidence" not in columns:
        op.add_column(
            "tenants",
            sa.Column(
                "auto_strict_min_confidence",
                sa.Numeric(precision=5, scale=4),
                nullable=True,
            ),
        )
    if "auto_strict_max_probes_per_run" not in columns:
        op.add_column(
            "tenants",
            sa.Column(
                "auto_strict_max_probes_per_run",
                sa.Integer(),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "tenants" not in inspector.get_table_names():
        return
    columns = {
        column["name"] for column in inspector.get_columns("tenants")
    }
    if "auto_strict_max_probes_per_run" in columns:
        op.drop_column("tenants", "auto_strict_max_probes_per_run")
    if "auto_strict_min_confidence" in columns:
        op.drop_column("tenants", "auto_strict_min_confidence")
    if "auto_strict_enabled" in columns:
        op.drop_column("tenants", "auto_strict_enabled")
