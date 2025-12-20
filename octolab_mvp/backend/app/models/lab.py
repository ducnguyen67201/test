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
    DEGRADED = "degraded"  # OctoBox works but target crashed (user can still connect)
    ENDING = "ending"  # Teardown requested / in progress
    FINISHED = "finished"  # Teardown completed
    FAILED = "failed"


class RuntimeType(str, enum.Enum):
    """Lab runtime type enumeration.

    SECURITY: This is server-owned and never from client input.
    """

    COMPOSE = "compose"
    FIRECRACKER = "firecracker"


class EvidenceSealStatus(str, enum.Enum):
    """Evidence seal status enumeration."""

    NONE = "none"  # Not sealed yet
    SEALED = "sealed"  # Successfully sealed with HMAC signature
    FAILED = "failed"  # Sealing failed (partial evidence may exist)


class EvidenceState(str, enum.Enum):
    """Evidence lifecycle state enumeration.

    SECURITY: This is the server-managed state exposed to clients.
    Non-admin users see only this state, not file lists or paths.
    """

    COLLECTING = "collecting"  # Lab is running, evidence being collected
    READY = "ready"  # All key artifacts present (terminal logs + pcap)
    PARTIAL = "partial"  # Some artifacts present, some missing
    UNAVAILABLE = "unavailable"  # No evidence artifacts found or evidence purged


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
        default=LabStatus.PROVISIONING,
        nullable=False,
    )
    requested_intent: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when lab teardown completed.",
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        doc="Timestamp when lab expires (TTL). After this, connect denied and lab auto-terminates.",
    )
    connection_url: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    hackvm_project: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    evidence_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp after which evidence is no longer downloadable.",
    )
    evidence_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when evidence storage (e.g. Docker volume) was purged.",
    )
    novnc_host_port: Mapped[int | None] = mapped_column(
        # Host port for noVNC access, allocated dynamically to prevent collisions
        nullable=True,
    )

    # Evidence volume names (per-lab, deterministic from lab_id)
    evidence_auth_volume: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Authoritative evidence volume name (written by gateway/backend only).",
    )
    evidence_user_volume: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="User evidence volume name (written by OctoBox).",
    )

    # Evidence sealing status and metadata
    evidence_seal_status: Mapped[str | None] = mapped_column(
        String(20),
        default=EvidenceSealStatus.NONE.value,
        nullable=True,
        doc="Seal status: none, sealed, or failed.",
    )
    evidence_sealed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when evidence was sealed.",
    )
    evidence_manifest_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        doc="SHA256 hash of the canonical manifest JSON.",
    )

    # Evidence lifecycle state (server-managed)
    evidence_state: Mapped[str | None] = mapped_column(
        String(20),
        default=EvidenceState.COLLECTING.value,
        nullable=True,
        doc="Evidence state: collecting, ready, partial, unavailable.",
    )
    evidence_finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when evidence state was finalized (on lab stop/teardown).",
    )
    evidence_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when evidence was purged by retention job.",
    )

    # Apache Guacamole integration fields
    guac_connection_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Guacamole connection ID (datasource-prefixed identifier).",
    )
    guac_username: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        doc="Per-lab Guacamole username (e.g., lab_<short_id>).",
    )
    guac_password_enc: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        doc="Fernet-encrypted Guacamole password for this lab user.",
    )
    guac_connected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Timestamp when Guacamole connection was established.",
    )

    # Runtime type (server-owned, never from client)
    # SECURITY: Default is firecracker for production-safe multi-tenant isolation
    runtime: Mapped[str] = mapped_column(
        String(20),
        default=RuntimeType.FIRECRACKER.value,
        nullable=False,
        doc="Lab runtime type: firecracker (default, production) or compose (dev only). Server-owned.",
    )

    # Runtime metadata (server-owned, safe subset exposed to client)
    # Stores VM-specific info like vm_id, firecracker_pid, state_dir basename (no secrets)
    # SECURITY: Never store full paths, passwords, or API tokens here
    runtime_meta: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        doc="Runtime metadata (safe subset): vm_id, state_dir basename. No secrets.",
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
    port_reservations: Mapped[list["PortReservation"]] = relationship(
        "PortReservation",
        back_populates="lab",
        cascade="all, delete-orphan",
    )

    # Index for tenant isolation queries
    __table_args__ = (
        Index("ix_labs_owner_id", "owner_id"),
    )

