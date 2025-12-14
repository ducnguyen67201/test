"""Add runtime_meta column to labs table.

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add runtime_meta column (nullable JSONB for storing VM metadata)
    # SECURITY: This stores safe subset only - no secrets/paths
    op.add_column(
        'labs',
        sa.Column(
            'runtime_meta',
            JSONB,
            nullable=True,
            comment='Runtime metadata (safe subset): vm_id, state_dir basename. No secrets.',
        )
    )


def downgrade() -> None:
    op.drop_column('labs', 'runtime_meta')
