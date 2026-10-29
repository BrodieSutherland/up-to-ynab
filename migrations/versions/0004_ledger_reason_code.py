"""Add ledger_entries.reason_code: a stable code for each skip reason.

Existing rows keep NULL, which is treated as final (never retried).

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ledger_entries",
        sa.Column("reason_code", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("ledger_entries") as batch:
        batch.drop_column("reason_code")
