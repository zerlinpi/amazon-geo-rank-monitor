"""Index the complete alert-baseline job history lookup.

Revision ID: 20261008_0022
Revises: 20260928_0021
Create Date: 2026-10-08
"""

import sqlalchemy as sa
from alembic import op

revision = "20261008_0022"
down_revision = "20260928_0021"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_rank_jobs_owner_monitor_status_run"


def upgrade() -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes("rank_jobs")
    if not any(index["name"] == INDEX_NAME for index in indexes):
        op.create_index(
            INDEX_NAME,
            "rank_jobs",
            ["owner_id", "monitor_target_id", "status", "run_id"],
        )


def downgrade() -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes("rank_jobs")
    if any(index["name"] == INDEX_NAME for index in indexes):
        op.drop_index(INDEX_NAME, table_name="rank_jobs")
