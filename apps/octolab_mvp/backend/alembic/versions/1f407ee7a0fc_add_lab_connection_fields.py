"""add_lab_connection_fields

Revision ID: 1f407ee7a0fc
Revises: 0148f9b0cd98
Create Date: 2025-11-17 18:53:15.964120

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f407ee7a0fc'
down_revision: Union[str, None] = '0148f9b0cd98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'labs',
        sa.Column('connection_url', sa.String(), nullable=True),
    )
    op.add_column(
        'labs',
        sa.Column('hackvm_project', sa.String(), nullable=True),
    )
    op.add_column(
        'labs',
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('labs', 'expires_at')
    op.drop_column('labs', 'hackvm_project')
    op.drop_column('labs', 'connection_url')

