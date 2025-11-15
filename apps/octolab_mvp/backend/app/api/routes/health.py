"""Health and version endpoints."""

from fastapi import APIRouter

from app.config import settings
from app.schemas.health import HealthResponse, VersionResponse

router = APIRouter(prefix="", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """
    Health check endpoint.

    Returns:
        HealthResponse: Status of the application
    """
    return HealthResponse(status="healthy")


@router.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    """
    Version information endpoint.

    Returns:
        VersionResponse: Application name and version
    """
    return VersionResponse(name=settings.app_name, version=settings.app_version)

