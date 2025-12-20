"""add guacamole fields

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2025-12-01 14:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6g7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Apache Guacamole integration fields
    op.add_column(
        "labs",
        sa.Column("guac_connection_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "labs",
        sa.Column("guac_username", sa.String(100), nullable=True),
    )
    op.add_column(
        "labs",
        sa.Column("guac_password_enc", sa.String(500), nullable=True),
    )
    op.add_column(
        "labs",
        sa.Column("guac_connected_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("labs", "guac_connected_at")
    op.drop_column("labs", "guac_password_enc")
    op.drop_column("labs", "guac_username")
    op.drop_column("labs", "guac_connection_id")
