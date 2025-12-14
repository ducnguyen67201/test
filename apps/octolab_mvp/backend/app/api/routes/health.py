"""Health and version endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.schemas.health import (
    DbHealthResponse,
    FirecrackerCheckResult,
    FirecrackerHealthResponse,
    HealthResponse,
    VersionResponse,
)
from app.services.db_schema_guard import check_schema_in_sync

router = APIRouter(prefix="", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """
    Health check endpoint.

    Returns:
        HealthResponse: Status of the application
    """
    return HealthResponse(status="healthy")


@router.get("/health/db", response_model=DbHealthResponse)
async def health_db(db: AsyncSession = Depends(get_db)) -> DbHealthResponse:
    """
    Database schema health check endpoint.

    Returns the current database revision, code revision, and whether
    they are in sync. No authentication required.

    SECURITY: Only reveals revision hashes, not connection details.

    Returns:
        DbHealthResponse: Schema synchronization status
    """
    status = await check_schema_in_sync(db)
    return DbHealthResponse(**status)


@router.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    """
    Version information endpoint.

    Returns:
        VersionResponse: Application name and version
    """
    return VersionResponse(name=settings.app_name, version=settings.app_version)


@router.get("/health/firecracker", response_model=FirecrackerHealthResponse)
async def health_firecracker() -> FirecrackerHealthResponse:
    """
    Firecracker runtime health check endpoint.

    Runs microVM doctor checks and returns status. No authentication required
    since this only exposes operational status, not secrets.

    SECURITY: Only reveals check names, status, and hints.
    Full paths and internal details are redacted.

    Returns:
        FirecrackerHealthResponse: Firecracker runtime health status
    """
    from app.services.microvm_doctor import run_checks

    # Run doctor checks (debug=False for redacted output)
    result = run_checks(debug=False)

    # Convert checks to response format with redaction
    checks = []
    for check in result["checks"]:
        checks.append(
            FirecrackerCheckResult(
                name=check["name"],
                status=check["status"],
                message=check.get("message", "")[:200],  # Truncate long messages
                severity=check.get("severity", "info"),
                hint=check.get("hint", "")[:200] if check.get("hint") else None,
            )
        )

    return FirecrackerHealthResponse(
        is_ok=result["is_ok"],
        summary=result["summary"],
        checks=checks,
        runtime=settings.octolab_runtime,
    )

