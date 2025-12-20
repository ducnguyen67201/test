"""add evidence seal fields

Revision ID: a1b2c3d4e5f6
Revises: 9f0a3d8e4b6c
Create Date: 2025-12-01 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "9f0a3d8e4b6c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Evidence volume names (deterministic from lab_id)
    op.add_column(
        "labs",
        sa.Column("evidence_auth_volume", sa.String(255), nullable=True),
    )
    op.add_column(
        "labs",
        sa.Column("evidence_user_volume", sa.String(255), nullable=True),
    )

    # Evidence sealing status and metadata
    op.add_column(
        "labs",
        sa.Column("evidence_seal_status", sa.String(20), nullable=True, server_default="none"),
    )
    op.add_column(
        "labs",
        sa.Column("evidence_sealed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "labs",
        sa.Column("evidence_manifest_sha256", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("labs", "evidence_manifest_sha256")
    op.drop_column("labs", "evidence_sealed_at")
    op.drop_column("labs", "evidence_seal_status")
    op.drop_column("labs", "evidence_user_volume")
    op.drop_column("labs", "evidence_auth_volume")
