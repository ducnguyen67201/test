"""Add novnc_host_port column to labs table with unique constraint for active ports.

Revision ID: 9f0a3d8e4b6c
Revises: 8f5b8c4d9e5f
Create Date: 2025-01-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9f0a3d8e4b6c"
down_revision: Union[str, None] = "8f5b8c4d9e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add novnc_host_port column as nullable integer
    op.add_column("labs", sa.Column("novnc_host_port", sa.Integer(), nullable=True))

    # Create a unique index on novnc_host_port that allows multiple NULLs but only one value per non-null port
    # This ensures only one lab can have a specific port assigned at any given time
    op.create_index(
        "ix_labs_novnc_host_port_unique",
        "labs",
        ["novnc_host_port"],
        unique=True,
        postgresql_where=sa.text("novnc_host_port IS NOT NULL")
    )


def downgrade() -> None:
    # Drop the unique index
    op.drop_index("ix_labs_novnc_host_port_unique", table_name="labs")
    
    # Drop the column
    op.drop_column("labs", "novnc_host_port")