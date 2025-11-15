"""Health and version response schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health check response."""

    status: str


class VersionResponse(BaseModel):
    """Version information response."""

    name: str
    version: str

