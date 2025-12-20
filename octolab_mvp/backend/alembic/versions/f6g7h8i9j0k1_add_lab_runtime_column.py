"""Add lab runtime column.

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2024-01-15 10:00:00.000000

SECURITY: This column is server-owned and never from client input.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f6g7h8i9j0k1"
down_revision = "e5f6g7h8i9j0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add runtime column to labs table."""
    op.add_column(
        "labs",
        sa.Column(
            "runtime",
            sa.String(20),
            nullable=False,
            server_default="compose",
        ),
    )


def downgrade() -> None:
    """Remove runtime column from labs table."""
    op.drop_column("labs", "runtime")
