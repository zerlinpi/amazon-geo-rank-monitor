"""Add workspace daily strict verification credit budget.

Revision ID: 20260927_0019
Revises: 20260926_0018
Create Date: 2026-09-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260927_0019"
down_revision = "20260926_0018"
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
    if "auto_strict_daily_credit_budget" not in columns:
        op.add_column(
            "tenants",
            sa.Column(
                "auto_strict_daily_credit_budget",
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
    if "auto_strict_daily_credit_budget" in columns:
        op.drop_column("tenants", "auto_strict_daily_credit_budget")
