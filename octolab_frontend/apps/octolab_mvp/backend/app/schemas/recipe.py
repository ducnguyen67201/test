"""Recipe Pydantic schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RecipeCreate(BaseModel):
    """Schema for creating a new recipe."""

    name: str
    description: str | None = None
    software: str
    version_constraint: str | None = None
    exploit_family: str | None = None
    is_active: bool = True


class RecipeResponse(BaseModel):
    """Schema for recipe API responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    software: str
    version_constraint: str | None
    exploit_family: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RecipeList(RecipeResponse):
    """Schema for recipe list responses (reuses RecipeResponse)."""

    pass

