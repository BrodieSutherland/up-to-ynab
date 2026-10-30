"""The 3.0 schema: ledger_entries.

Revision ID: 0001
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ledger_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("up_transaction_id", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("ynab_transaction_id", sa.String(50), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_ledger_entries_up_transaction_id",
        "ledger_entries",
        ["up_transaction_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_ledger_entries_up_transaction_id", table_name="ledger_entries")
    op.drop_table("ledger_entries")
