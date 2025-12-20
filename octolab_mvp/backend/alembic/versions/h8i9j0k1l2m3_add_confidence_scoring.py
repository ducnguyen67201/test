"""Add confidence scoring columns to CVE registry and review queue.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add confidence_score and confidence_reason to cve_dockerfiles table
    op.add_column(
        'cve_dockerfiles',
        sa.Column(
            'confidence_score',
            sa.Integer(),
            nullable=True,
            comment='LLM confidence score (0-100) for this Dockerfile',
        )
    )
    op.add_column(
        'cve_dockerfiles',
        sa.Column(
            'confidence_reason',
            sa.Text(),
            nullable=True,
            comment='LLM explanation for the confidence score',
        )
    )

    # Add confidence_score and confidence_reason to dockerfile_review_queue table
    op.add_column(
        'dockerfile_review_queue',
        sa.Column(
            'confidence_score',
            sa.Integer(),
            nullable=True,
            comment='LLM confidence score (0-100) at time of failure',
        )
    )
    op.add_column(
        'dockerfile_review_queue',
        sa.Column(
            'confidence_reason',
            sa.Text(),
            nullable=True,
            comment='LLM explanation for the confidence score',
        )
    )


def downgrade() -> None:
    op.drop_column('dockerfile_review_queue', 'confidence_reason')
    op.drop_column('dockerfile_review_queue', 'confidence_score')
    op.drop_column('cve_dockerfiles', 'confidence_reason')
    op.drop_column('cve_dockerfiles', 'confidence_score')
