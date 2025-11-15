"""Lab Pydantic schemas."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# Lab status values matching LabStatus enum
LabStatusStr = Literal[
    "requested",
    "provisioning",
    "ready",
    "ending",
    "finished",
    "failed",
]


class LabCreate(BaseModel):
    """Schema for creating a new lab."""

    recipe_id: UUID | None = None  # Optional, may be selected by LLM
    requested_intent: dict[str, Any] | None = None  # Raw intent from user


class LabResponse(BaseModel):
    """Schema for lab API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    recipe_id: UUID
    status: LabStatusStr
    requested_intent: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class LabUpdate(BaseModel):
    """Schema for updating lab status (internal/admin use)."""

    status: LabStatusStr | None = None
    finished_at: datetime | None = None


class LabList(LabResponse):
    """Schema for lab list responses (reuses LabResponse)."""

    pass

