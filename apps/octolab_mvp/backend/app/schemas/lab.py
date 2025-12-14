"""Lab Pydantic schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer
from app.config import settings


# Lab status values matching LabStatus enum
LabStatusStr = Literal[
    "requested",
    "provisioning",
    "ready",
    "ending",
    "finished",
    "failed",
]

# Evidence state values matching EvidenceState enum
EvidenceStateStr = Literal[
    "collecting",
    "ready",
    "partial",
    "unavailable",
]

# Runtime type values matching RuntimeType enum
RuntimeTypeStr = Literal[
    "compose",
    "firecracker",
]


class LabIntent(BaseModel):
    """Structured intent schema for lab creation."""

    software: str | None = None
    version: str | None = None
    exploit_family: str | None = None
    app_domain: str | None = None
    notes: str | None = None


class LabCreate(BaseModel):
    """Schema for creating a new lab."""

    recipe_id: UUID | None = None  # Optional, may be selected by LLM
    intent: LabIntent | None = None  # Structured intent from user


class RuntimeMetaResponse(BaseModel):
    """Runtime metadata (safe subset for API response).

    SECURITY: Only contains non-sensitive data - no full paths or secrets.
    """

    vm_id: str | None = None  # Firecracker VM ID (UUID suffix)
    state_dir: str | None = None  # State directory basename (not full path)
    firecracker_pid: int | None = None  # VM process ID (for admin visibility)

    model_config = ConfigDict(extra="ignore")  # Ignore unknown fields


class LabResponse(BaseModel):
    """Schema for lab API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    recipe_id: UUID
    status: LabStatusStr
    requested_intent: dict[str, Any] | None
    connection_url: str | None = None
    hackvm_project: str | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None
    # Evidence lifecycle state (safe for non-admin users)
    evidence_state: EvidenceStateStr | None = None
    evidence_finalized_at: datetime | None = None
    # Runtime type (server-owned, never from client input)
    runtime: RuntimeTypeStr = "compose"
    # Runtime metadata (server-owned, safe subset)
    runtime_meta: dict[str, Any] | None = None



class LabUpdate(BaseModel):
    """Schema for updating lab status (internal/admin use)."""

    status: LabStatusStr | None = None
    finished_at: datetime | None = None


class LabList(LabResponse):
    """Schema for lab list responses (reuses LabResponse)."""

    pass


class LabConnectResponse(BaseModel):
    """Response schema for lab connection endpoint."""

    redirect_url: str


class ArtifactStatus(BaseModel):
    """Status of a single artifact type."""

    present: bool
    files: list[str] | None = None
    bytes: int = 0
    reason: str | None = None


class EvidenceArtifacts(BaseModel):
    """Structured evidence artifact statuses."""

    terminal_logs: ArtifactStatus
    pcap: ArtifactStatus
    guac_recordings: ArtifactStatus


class EvidenceStatusResponse(BaseModel):
    """Response schema for evidence status endpoint.

    Single source of truth for artifact presence/readability.
    Uses presence-based detection, not flags.
    """

    lab_id: UUID
    generated_at: datetime
    artifacts: EvidenceArtifacts
    notes: list[str] = []

