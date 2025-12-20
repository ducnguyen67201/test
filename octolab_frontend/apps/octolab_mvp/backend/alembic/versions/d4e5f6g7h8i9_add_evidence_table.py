"""add evidence table for Falco events

Revision ID: d4e5f6g7h8i9
Revises: b2c3d4e5f6g7
Create Date: 2025-12-05 12:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "d4e5f6g7h8i9"
down_revision: Union[str, None] = "b2c3d4e5f6g7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evidence",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lab_id", UUID(as_uuid=True), sa.ForeignKey("labs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("container_name", sa.String(255), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("event_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    # Indexes for efficient queries
    op.create_index("ix_evidence_lab_id", "evidence", ["lab_id"])
    op.create_index("ix_evidence_event_type", "evidence", ["event_type"])
    op.create_index("ix_evidence_timestamp", "evidence", ["timestamp"])
    op.create_index("ix_evidence_event_hash", "evidence", ["event_hash"], unique=True)
    op.create_index("ix_evidence_lab_id_timestamp", "evidence", ["lab_id", "timestamp"])
    op.create_index("ix_evidence_lab_id_event_type", "evidence", ["lab_id", "event_type"])


def downgrade() -> None:
    op.drop_index("ix_evidence_lab_id_event_type", table_name="evidence")
    op.drop_index("ix_evidence_lab_id_timestamp", table_name="evidence")
    op.drop_index("ix_evidence_event_hash", table_name="evidence")
    op.drop_index("ix_evidence_timestamp", table_name="evidence")
    op.drop_index("ix_evidence_event_type", table_name="evidence")
    op.drop_index("ix_evidence_lab_id", table_name="evidence")
    op.drop_table("evidence")
