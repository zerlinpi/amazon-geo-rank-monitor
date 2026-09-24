"""Add leased retries and dead-letter fields to rank jobs.

Revision ID: 20260924_0003
Revises: 20260924_0002
Create Date: 2026-09-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260924_0003"
down_revision = "20260924_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("rank_jobs")}
    indexes = {index["name"] for index in inspector.get_indexes("rank_jobs")}

    with op.batch_alter_table("rank_jobs") as batch:
        if "available_at" not in columns:
            batch.add_column(
                sa.Column(
                    "available_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                )
            )
        if "claimed_by" not in columns:
            batch.add_column(sa.Column("claimed_by", sa.String(length=128)))
        if "lease_expires_at" not in columns:
            batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        if "max_attempts" not in columns:
            batch.add_column(
                sa.Column(
                    "max_attempts",
                    sa.Integer(),
                    nullable=False,
                    server_default="3",
                )
            )
        if "ix_rank_jobs_available_at" not in indexes:
            batch.create_index("ix_rank_jobs_available_at", ["available_at"])
        if "ix_rank_jobs_lease_expires_at" not in indexes:
            batch.create_index("ix_rank_jobs_lease_expires_at", ["lease_expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("rank_jobs")}
    indexes = {index["name"] for index in inspector.get_indexes("rank_jobs")}

    with op.batch_alter_table("rank_jobs") as batch:
        if "ix_rank_jobs_lease_expires_at" in indexes:
            batch.drop_index("ix_rank_jobs_lease_expires_at")
        if "ix_rank_jobs_available_at" in indexes:
            batch.drop_index("ix_rank_jobs_available_at")
        if "max_attempts" in columns:
            batch.drop_column("max_attempts")
        if "lease_expires_at" in columns:
            batch.drop_column("lease_expires_at")
        if "claimed_by" in columns:
            batch.drop_column("claimed_by")
        if "available_at" in columns:
            batch.drop_column("available_at")
