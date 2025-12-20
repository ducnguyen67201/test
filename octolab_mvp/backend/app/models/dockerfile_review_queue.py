"""Dockerfile Review Queue model.

Stores failed LLM-generated Dockerfiles that need manual review.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import String, Text, Integer, DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.base import TimestampMixin


class DockerfileReviewQueue(Base, TimestampMixin):
    """Queue of Dockerfiles that failed LLM generation and need review."""

    __tablename__ = "dockerfile_review_queue"

    id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    cve_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    recipe_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_dockerfile: Mapped[str | None] = mapped_column(Text, nullable=True)
    errors: Mapped[list] = mapped_column(JSONB, default=list)
    attempts: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending, reviewed, resolved

    # LLM confidence scoring
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    reviewed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
