"""Persist automatic strict verification metadata.

Revision ID: 20260926_0015
Revises: 20260926_0014
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260926_0015"
down_revision = "20260926_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "rank_runs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("rank_runs")}
    if "verification_metadata" in columns:
        return

    op.add_column(
        "rank_runs",
        sa.Column(
            "verification_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "rank_runs" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("rank_runs")}
    if "verification_metadata" not in columns:
        return
    op.drop_column("rank_runs", "verification_metadata")
