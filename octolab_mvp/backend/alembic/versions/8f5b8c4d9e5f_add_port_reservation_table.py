"""add port reservation table

Revision ID: 8f5b8c4d9e5f
Revises: 7e9c3bfe2f34
Create Date: 2025-11-29 10:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "8f5b8c4d9e5f"
down_revision: Union[str, None] = "7e9c3bfe2f34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the port_reservations table
    op.create_table(
        "port_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lab_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["lab_id"], ["labs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create partial unique index for active port reservations (only one active reservation per port)
    op.create_index(
        "ix_port_reservations_port_active",
        "port_reservations",
        ["port"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )

    # Create partial unique index for active lab+kind reservations (only one active reservation per lab+kind)
    op.create_index(
        "ix_port_reservations_lab_kind_active",
        "port_reservations",
        ["lab_id", "kind"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
    )

    # Create index for efficient querying
    op.create_index("ix_port_reservations_lab_id", "port_reservations", ["lab_id"])


def downgrade() -> None:
    # Drop indexes first
    op.drop_index("ix_port_reservations_lab_id", table_name="port_reservations")
    op.drop_index("ix_port_reservations_lab_kind_active", table_name="port_reservations")
    op.drop_index("ix_port_reservations_port_active", table_name="port_reservations")
    
    # Drop the table
    op.drop_table("port_reservations")

