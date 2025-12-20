"""Port reservation model for dynamic port allocation."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin


class PortReservation(Base, TimestampMixin):
    """Model for tracking port reservations for labs."""

    __tablename__ = "port_reservations"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=None,
    )
    lab_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("labs.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(50),
        default="novnc",
        nullable=False,
    )
    port: Mapped[int] = mapped_column(
        # Port number (e.g., 6080 for noVNC)
        nullable=False,
    )
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when reservation was released",
    )

    # Relationships
    lab: Mapped["Lab"] = relationship(
        "Lab",
        back_populates="port_reservations",
    )

    # Index for efficient querying by lab_id and kind
    __table_args__ = (
        # Partial unique index: only one active reservation per port
        Index(
            "ix_port_reservations_port_active",
            "port",
            unique=True,
            postgresql_where=func.coalesce(released_at, func.now()).is_(None),
        ),
        # Index to quickly find active reservations for a lab+kind
        Index(
            "ix_port_reservations_lab_kind_active",
            "lab_id",
            "kind",
            unique=True,
            postgresql_where=func.coalesce(released_at, func.now()).is_(None),
        ),
    )