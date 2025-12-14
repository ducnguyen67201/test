"""Health and version response schemas."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Health check response."""

    status: str


class VersionResponse(BaseModel):
    """Version information response."""

    name: str
    version: str


class DbHealthResponse(BaseModel):
    """Database schema health response."""

    db_revision: str | None
    code_revision: str | None
    in_sync: bool
    reason: str


class FirecrackerCheckResult(BaseModel):
    """Individual firecracker doctor check result."""

    name: str
    status: str  # "OK", "WARN", "FAIL", "SKIP"
    message: str
    severity: str  # "fatal", "warning", "info"
    hint: str | None = None


class FirecrackerHealthResponse(BaseModel):
    """Firecracker runtime health response.

    SECURITY: Only expose check names, status, and hints.
    Full paths and internal details are redacted.
    """

    is_ok: bool
    summary: dict[str, int]  # {"ok": N, "warn": N, "fatal": N}
    checks: list[FirecrackerCheckResult]
    runtime: str  # Current runtime setting

