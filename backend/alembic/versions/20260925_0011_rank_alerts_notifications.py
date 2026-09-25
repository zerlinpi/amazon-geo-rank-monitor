"""Add rank alert rules, events and deliveries.

Revision ID: 20260925_0011
Revises: 20260925_0010
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260925_0011"
down_revision = "20260925_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "rank_alert_rules" not in tables:
        op.create_table(
            "rank_alert_rules",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("monitor_target_id", sa.String(length=36), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("rule_type", sa.String(length=32), nullable=False),
            sa.Column("threshold", sa.Numeric(12, 2), nullable=True),
            sa.Column("asin", sa.String(length=32), nullable=True),
            sa.Column("geo_profile_id", sa.String(length=128), nullable=True),
            sa.Column("channels_encrypted", sa.Text(), nullable=False),
            sa.Column(
                "cooldown_minutes",
                sa.Integer(),
                nullable=False,
                server_default="60",
            ),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["owner_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_rank_alert_rules_owner_id",
            "rank_alert_rules",
            ["owner_id"],
        )
        op.create_index(
            "ix_rank_alert_rules_monitor_target_id",
            "rank_alert_rules",
            ["monitor_target_id"],
        )

    if "rank_alert_events" not in tables:
        op.create_table(
            "rank_alert_events",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("rule_id", sa.String(length=36), nullable=False),
            sa.Column("monitor_target_id", sa.String(length=36), nullable=False),
            sa.Column("run_id", sa.String(length=36), nullable=False),
            sa.Column("asin", sa.String(length=32), nullable=False),
            sa.Column("geo_profile_id", sa.String(length=128), nullable=True),
            sa.Column("event_type", sa.String(length=32), nullable=False),
            sa.Column("fingerprint", sa.String(length=128), nullable=False),
            sa.Column("previous_value", sa.Numeric(12, 2), nullable=True),
            sa.Column("current_value", sa.Numeric(12, 2), nullable=True),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["rule_id"],
                ["rank_alert_rules.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "rule_id",
                "fingerprint",
                name="uq_rank_alert_fingerprint",
            ),
        )
        op.create_index(
            "ix_rank_alert_events_owner_id",
            "rank_alert_events",
            ["owner_id"],
        )
        op.create_index(
            "ix_rank_alert_events_rule_id",
            "rank_alert_events",
            ["rule_id"],
        )
        op.create_index(
            "ix_rank_alert_events_monitor_target_id",
            "rank_alert_events",
            ["monitor_target_id"],
        )
        op.create_index(
            "ix_rank_alert_events_run_id",
            "rank_alert_events",
            ["run_id"],
        )
        op.create_index(
            "ix_rank_alert_events_created_at",
            "rank_alert_events",
            ["created_at"],
        )

    if "rank_alert_deliveries" not in tables:
        op.create_table(
            "rank_alert_deliveries",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("event_id", sa.String(length=36), nullable=False),
            sa.Column("channel_type", sa.String(length=24), nullable=False),
            sa.Column("destination", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["event_id"],
                ["rank_alert_events.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_rank_alert_deliveries_event_id",
            "rank_alert_deliveries",
            ["event_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "rank_alert_deliveries" in tables:
        op.drop_index(
            "ix_rank_alert_deliveries_event_id",
            table_name="rank_alert_deliveries",
        )
        op.drop_table("rank_alert_deliveries")

    if "rank_alert_events" in tables:
        op.drop_index(
            "ix_rank_alert_events_created_at",
            table_name="rank_alert_events",
        )
        op.drop_index(
            "ix_rank_alert_events_run_id",
            table_name="rank_alert_events",
        )
        op.drop_index(
            "ix_rank_alert_events_monitor_target_id",
            table_name="rank_alert_events",
        )
        op.drop_index(
            "ix_rank_alert_events_rule_id",
            table_name="rank_alert_events",
        )
        op.drop_index(
            "ix_rank_alert_events_owner_id",
            table_name="rank_alert_events",
        )
        op.drop_table("rank_alert_events")

    if "rank_alert_rules" in tables:
        op.drop_index(
            "ix_rank_alert_rules_monitor_target_id",
            table_name="rank_alert_rules",
        )
        op.drop_index(
            "ix_rank_alert_rules_owner_id",
            table_name="rank_alert_rules",
        )
        op.drop_table("rank_alert_rules")
