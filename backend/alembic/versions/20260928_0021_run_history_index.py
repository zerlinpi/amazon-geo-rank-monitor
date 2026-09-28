"""Index tenant-scoped run history pagination.

Revision ID: 20260928_0021
Revises: 20260927_0020
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op

revision = "20260928_0021"
down_revision = "20260927_0020"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_rank_runs_owner_started_id"


def upgrade() -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes("rank_runs")
    if not any(index["name"] == INDEX_NAME for index in indexes):
        op.create_index(INDEX_NAME, "rank_runs", ["owner_id", "started_at", "id"])


def downgrade() -> None:
    indexes = sa.inspect(op.get_bind()).get_indexes("rank_runs")
    if any(index["name"] == INDEX_NAME for index in indexes):
        op.drop_index(INDEX_NAME, table_name="rank_runs")
