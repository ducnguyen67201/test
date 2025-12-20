"""Evidence model for storing Falco events."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.base import TimestampMixin


class Evidence(Base, TimestampMixin):
    """Evidence model for storing collected events from Falco.

    Links to Lab via lab_id (extracted from container name pattern lab-{uuid}-{role}).
    Events are JSON payloads containing command, network, or file_read data.
    """

    __tablename__ = "evidence"

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
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Event type: command, network, file_read",
    )
    container_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Container name that generated the event (lab-{uuid}-{role})",
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        doc="Event timestamp from Falco",
    )
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        doc="Full event payload from Falco (command, network, or file_read data)",
    )
    event_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        doc="SHA256 hash for deduplication (hash of lab_id + timestamp + payload)",
    )

    # Relationship to Lab
    lab: Mapped["Lab"] = relationship(
        "Lab",
        backref="evidence_events",
    )

    __table_args__ = (
        Index("ix_evidence_lab_id_timestamp", "lab_id", "timestamp"),
        Index("ix_evidence_lab_id_event_type", "lab_id", "event_type"),
    )
