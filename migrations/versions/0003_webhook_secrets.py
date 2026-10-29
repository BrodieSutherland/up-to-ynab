"""Add webhook_secrets: the signing secret of each webhook this app created.

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_secrets",
        sa.Column("webhook_id", sa.String(length=64), nullable=False),
        sa.Column("secret_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("webhook_id"),
    )


def downgrade() -> None:
    op.drop_table("webhook_secrets")
