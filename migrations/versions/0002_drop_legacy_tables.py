"""Drop the unread 2.x tables payee_category_mappings and processed_transactions.

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payee_category_mappings")
    op.execute("DROP TABLE IF EXISTS processed_transactions")


def downgrade() -> None:
    """No-op: the legacy tables were unread and are not recreated."""
