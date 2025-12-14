"""add evidence state lifecycle fields

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2025-12-07 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Evidence lifecycle state (server-managed)
    op.add_column(
        "labs",
        sa.Column(
            "evidence_state",
            sa.String(20),
            nullable=True,
            server_default="collecting",
        ),
    )
    op.add_column(
        "labs",
        sa.Column(
            "evidence_finalized_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "labs",
        sa.Column(
            "evidence_purged_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Backfill: Set existing terminal labs (FINISHED, FAILED) to 'unavailable'
    # until next finalize can determine actual state.
    # Labs in active states (PROVISIONING, READY, ENDING) stay as 'collecting'.
    op.execute("""
        UPDATE labs
        SET evidence_state = 'unavailable'
        WHERE status IN ('finished', 'failed')
    """)


def downgrade() -> None:
    op.drop_column("labs", "evidence_purged_at")
    op.drop_column("labs", "evidence_finalized_at")
    op.drop_column("labs", "evidence_state")
