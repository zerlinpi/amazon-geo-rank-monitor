"""Add tenant-scoped SERP probe cache and cache provenance.

Revision ID: 20260925_0013
Revises: 20260925_0012
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260925_0013"
down_revision = "20260925_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    run_columns = {
        column["name"] for column in inspector.get_columns("rank_runs")
    }
    with op.batch_alter_table("rank_runs") as batch:
        if "cache_hit_count" not in run_columns:
            batch.add_column(
                sa.Column(
                    "cache_hit_count",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )

    observation_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("rank_observations")
    }
    with op.batch_alter_table("rank_observations") as batch:
        if "probe_source" not in observation_columns:
            batch.add_column(
                sa.Column(
                    "probe_source",
                    sa.String(length=16),
                    nullable=False,
                    server_default="upstream",
                )
            )
        if "cache_age_seconds" not in observation_columns:
            batch.add_column(
                sa.Column("cache_age_seconds", sa.Integer(), nullable=True)
            )

    if "serp_probe_cache" not in tables:
        op.create_table(
            "serp_probe_cache",
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("cache_key", sa.String(length=64), nullable=False),
            sa.Column("provider_mode", sa.String(length=16), nullable=False),
            sa.Column("provider_name", sa.String(length=64), nullable=False),
            sa.Column("verification_level", sa.String(length=32), nullable=False),
            sa.Column("marketplace", sa.String(length=128), nullable=False),
            sa.Column("keyword", sa.String(length=512), nullable=False),
            sa.Column("geo_profile_id", sa.String(length=128), nullable=False),
            sa.Column("device", sa.String(length=16), nullable=False),
            sa.Column("search_depth", sa.Integer(), nullable=False),
            sa.Column("identity_payload", sa.JSON(), nullable=False),
            sa.Column("result_payload", sa.JSON(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
            sa.ForeignKeyConstraint(
                ["owner_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("owner_id", "cache_key"),
        )
        op.create_index(
            "ix_serp_probe_cache_expires_at",
            "serp_probe_cache",
            ["expires_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "serp_probe_cache" in tables:
        op.drop_index(
            "ix_serp_probe_cache_expires_at",
            table_name="serp_probe_cache",
        )
        op.drop_table("serp_probe_cache")

    observation_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("rank_observations")
    }
    with op.batch_alter_table("rank_observations") as batch:
        if "cache_age_seconds" in observation_columns:
            batch.drop_column("cache_age_seconds")
        if "probe_source" in observation_columns:
            batch.drop_column("probe_source")

    run_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("rank_runs")
    }
    with op.batch_alter_table("rank_runs") as batch:
        if "cache_hit_count" in run_columns:
            batch.drop_column("cache_hit_count")
