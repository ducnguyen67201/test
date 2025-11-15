"""Lab model."""

import enum
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin


class LabStatus(str, enum.Enum):
    """Lab status enumeration."""

    REQUESTED = "requested"
    PROVISIONING = "provisioning"
    READY = "ready"
    ENDING = "ending"
    FINISHED = "finished"
    FAILED = "failed"


class Lab(Base, TimestampMixin):
    """Lab model representing a rehearsal environment."""

    __tablename__ = "labs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=None,
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    recipe_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recipes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[LabStatus] = mapped_column(
        String(50),
        default=LabStatus.REQUESTED,
        nullable=False,
    )
    requested_intent: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    owner: Mapped["User"] = relationship(
        "User",
        back_populates="labs",
    )
    recipe: Mapped["Recipe"] = relationship(
        "Recipe",
        back_populates="labs",
    )

    # Index for tenant isolation queries
    __table_args__ = (
        Index("ix_labs_owner_id", "owner_id"),
    )

