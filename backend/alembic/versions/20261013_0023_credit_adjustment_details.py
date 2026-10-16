"""Store operator, reason and request parameters for manual credit adjustments."""

import sqlalchemy as sa
from alembic import op

revision = "20261013_0023"
down_revision = "20261008_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("credit_ledger_entries")}
    if "details" not in columns:
        op.add_column("credit_ledger_entries", sa.Column("details", sa.JSON(), nullable=True))


def downgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("credit_ledger_entries")}
    if "details" in columns:
        op.drop_column("credit_ledger_entries", "details")
