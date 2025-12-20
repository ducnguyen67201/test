"""add evidence retention fields

Revision ID: 7e9c3bfe2f34
Revises: 1f407ee7a0fc
Create Date: 2025-11-19 12:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7e9c3bfe2f34"
down_revision: Union[str, None] = "1f407ee7a0fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "labs",
        sa.Column("evidence_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "labs",
        sa.Column("evidence_deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("labs", "evidence_deleted_at")
    op.drop_column("labs", "evidence_expires_at")

