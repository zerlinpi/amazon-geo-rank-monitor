"""Add scheduled analytics reports and delivery history.

Revision ID: 20260925_0012
Revises: 20260925_0011
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260925_0012"
down_revision = "20260925_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "report_schedules" not in tables:
        op.create_table(
            "report_schedules",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("monitor_target_ids", sa.JSON(), nullable=False),
            sa.Column("recipients_encrypted", sa.Text(), nullable=False),
            sa.Column("schedule", sa.String(length=128), nullable=False),
            sa.Column(
                "lookback_hours",
                sa.Integer(),
                nullable=False,
                server_default="168",
            ),
            sa.Column(
                "include_csv",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
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
            "ix_report_schedules_owner_id",
            "report_schedules",
            ["owner_id"],
        )

    if "report_deliveries" not in tables:
        op.create_table(
            "report_deliveries",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("schedule_id", sa.String(length=36), nullable=False),
            sa.Column(
                "scheduled_for",
                sa.DateTime(timezone=True),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=24), nullable=False),
            sa.Column(
                "recipient_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "sent_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("subject", sa.String(length=300), nullable=False),
            sa.Column("summary", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(
                ["schedule_id"],
                ["report_schedules.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "schedule_id",
                "scheduled_for",
                name="uq_report_schedule_delivery_slot",
            ),
        )
        op.create_index(
            "ix_report_deliveries_owner_id",
            "report_deliveries",
            ["owner_id"],
        )
        op.create_index(
            "ix_report_deliveries_schedule_id",
            "report_deliveries",
            ["schedule_id"],
        )
        op.create_index(
            "ix_report_deliveries_scheduled_for",
            "report_deliveries",
            ["scheduled_for"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())

    if "report_deliveries" in tables:
        op.drop_index(
            "ix_report_deliveries_scheduled_for",
            table_name="report_deliveries",
        )
        op.drop_index(
            "ix_report_deliveries_schedule_id",
            table_name="report_deliveries",
        )
        op.drop_index(
            "ix_report_deliveries_owner_id",
            table_name="report_deliveries",
        )
        op.drop_table("report_deliveries")

    if "report_schedules" in tables:
        op.drop_index(
            "ix_report_schedules_owner_id",
            table_name="report_schedules",
        )
        op.drop_table("report_schedules")
