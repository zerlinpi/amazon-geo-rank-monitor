"""Add workspace SCIM provisioning.

Revision ID: 20260925_0010
Revises: 20260925_0009
Create Date: 2026-09-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260925_0010"
down_revision = "20260925_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    membership_columns = {
        column["name"]
        for column in inspector.get_columns("workspace_memberships")
    }
    with op.batch_alter_table("workspace_memberships") as batch:
        if "suspended_at" not in membership_columns:
            batch.add_column(
                sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True)
            )
        if "scim_managed" not in membership_columns:
            batch.add_column(
                sa.Column(
                    "scim_managed",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.false(),
                )
            )
        if "scim_external_id" not in membership_columns:
            batch.add_column(
                sa.Column("scim_external_id", sa.String(length=512), nullable=True)
            )
        if "updated_at" not in membership_columns:
            batch.add_column(
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    nullable=False,
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                )
            )

    existing_constraints = {
        item.get("name")
        for item in sa.inspect(bind).get_unique_constraints("workspace_memberships")
    }
    if "uq_workspace_scim_external_id" not in existing_constraints:
        with op.batch_alter_table("workspace_memberships") as batch:
            batch.create_unique_constraint(
                "uq_workspace_scim_external_id",
                ["owner_id", "scim_external_id"],
            )

    if "workspace_scim_configs" not in tables:
        op.create_table(
            "workspace_scim_configs",
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("token_prefix", sa.String(length=32), nullable=True),
            sa.Column("token_hash", sa.String(length=64), nullable=True),
            sa.Column(
                "enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column(
                "default_role",
                sa.String(length=32),
                nullable=False,
                server_default="viewer",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["owner_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("owner_id"),
            sa.UniqueConstraint("token_prefix"),
            sa.UniqueConstraint("token_hash"),
        )
        op.create_index(
            "ix_workspace_scim_configs_token_prefix",
            "workspace_scim_configs",
            ["token_prefix"],
            unique=True,
        )

    if "scim_groups" not in tables:
        op.create_table(
            "scim_groups",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("external_id", sa.String(length=512), nullable=True),
            sa.Column("display_name", sa.String(length=200), nullable=False),
            sa.Column("mapped_role", sa.String(length=32), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["owner_id"],
                ["tenants.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "owner_id",
                "external_id",
                name="uq_scim_group_external_id",
            ),
        )
        op.create_index(
            "ix_scim_groups_owner_id",
            "scim_groups",
            ["owner_id"],
        )

    if "scim_group_members" not in tables:
        op.create_table(
            "scim_group_members",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("group_id", sa.String(length=36), nullable=False),
            sa.Column("membership_id", sa.String(length=36), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["group_id"],
                ["scim_groups.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["membership_id"],
                ["workspace_memberships.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "group_id",
                "membership_id",
                name="uq_scim_group_membership",
            ),
        )
        op.create_index(
            "ix_scim_group_members_group_id",
            "scim_group_members",
            ["group_id"],
        )
        op.create_index(
            "ix_scim_group_members_membership_id",
            "scim_group_members",
            ["membership_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "scim_group_members" in tables:
        op.drop_index(
            "ix_scim_group_members_membership_id",
            table_name="scim_group_members",
        )
        op.drop_index(
            "ix_scim_group_members_group_id",
            table_name="scim_group_members",
        )
        op.drop_table("scim_group_members")

    if "scim_groups" in tables:
        op.drop_index("ix_scim_groups_owner_id", table_name="scim_groups")
        op.drop_table("scim_groups")

    if "workspace_scim_configs" in tables:
        op.drop_index(
            "ix_workspace_scim_configs_token_prefix",
            table_name="workspace_scim_configs",
        )
        op.drop_table("workspace_scim_configs")

    membership_constraints = {
        item.get("name")
        for item in sa.inspect(bind).get_unique_constraints("workspace_memberships")
    }
    membership_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("workspace_memberships")
    }
    with op.batch_alter_table("workspace_memberships") as batch:
        if "uq_workspace_scim_external_id" in membership_constraints:
            batch.drop_constraint(
                "uq_workspace_scim_external_id",
                type_="unique",
            )
        for column_name in (
            "updated_at",
            "scim_external_id",
            "scim_managed",
            "suspended_at",
        ):
            if column_name in membership_columns:
                batch.drop_column(column_name)
