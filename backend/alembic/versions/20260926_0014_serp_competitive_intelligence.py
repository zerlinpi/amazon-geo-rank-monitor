"""Add SERP competitive observations.

Revision ID: 20260926_0014
Revises: 20260925_0013
Create Date: 2026-09-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260926_0014"
down_revision = "20260925_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "serp_competitive_observations" in tables:
        return

    op.create_table(
        "serp_competitive_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rank_run_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("geo_profile_id", sa.String(length=128), nullable=False),
        sa.Column("asin", sa.String(length=32), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("organic_position", sa.Integer(), nullable=True),
        sa.Column("sponsored_position", sa.Integer(), nullable=True),
        sa.Column("absolute_position", sa.Integer(), nullable=True),
        sa.Column(
            "probe_source",
            sa.String(length=16),
            nullable=False,
            server_default="upstream",
        ),
        sa.Column("cache_age_seconds", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rank_run_id"],
            ["rank_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "rank_run_id",
            "geo_profile_id",
            "asin",
            name="uq_serp_competitive_run_geo_asin",
        ),
    )
    op.create_index(
        "ix_serp_competitive_observations_rank_run_id",
        "serp_competitive_observations",
        ["rank_run_id"],
    )
    op.create_index(
        "ix_serp_competitive_observations_owner_id",
        "serp_competitive_observations",
        ["owner_id"],
    )
    op.create_index(
        "ix_serp_competitive_observations_geo_profile_id",
        "serp_competitive_observations",
        ["geo_profile_id"],
    )
    op.create_index(
        "ix_serp_competitive_observations_asin",
        "serp_competitive_observations",
        ["asin"],
    )
    op.create_index(
        "ix_serp_competitive_observations_observed_at",
        "serp_competitive_observations",
        ["observed_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "serp_competitive_observations" not in tables:
        return
    for name in (
        "ix_serp_competitive_observations_observed_at",
        "ix_serp_competitive_observations_asin",
        "ix_serp_competitive_observations_geo_profile_id",
        "ix_serp_competitive_observations_owner_id",
        "ix_serp_competitive_observations_rank_run_id",
    ):
        op.drop_index(name, table_name="serp_competitive_observations")
    op.drop_table("serp_competitive_observations")
