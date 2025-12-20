"""CVE Dockerfile Registry API."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.cve_dockerfile import (
    CVEDockerfile,
    CVEDockerfileStatus,
    VerificationStatus,
    VerificationType,
)
from app.api.deps import get_current_user_or_service
from app.services.cve_smoke_test import verify_cve_exploit
from app.services.cve_alias_resolver import resolve_cve_reference, set_aliases

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cve-registry", tags=["CVE Registry"])


class SourceFileSchema(BaseModel):
    filename: str
    content: str


class CVEDockerfileCreate(BaseModel):
    cve_id: str = Field(..., max_length=20)
    dockerfile: str
    source_files: list[SourceFileSchema] = []
    base_image: Optional[str] = None
    exposed_ports: list[int] = []
    exploit_hint: Optional[str] = None
    status: str = "curated"
    confidence_score: Optional[int] = Field(None, ge=0, le=100)
    confidence_reason: Optional[str] = None


class CVEDockerfileResponse(BaseModel):
    id: UUID
    cve_id: str
    dockerfile: str
    source_files: list[dict]
    base_image: Optional[str]
    exposed_ports: list[int]
    exploit_hint: Optional[str]
    status: str
    confidence_score: Optional[int]
    confidence_reason: Optional[str]
    created_by: Optional[str]
    aliases: list[str] = []

    class Config:
        from_attributes = True


@router.get("/{cve_id}", response_model=CVEDockerfileResponse)
async def get_cve_dockerfile(
    cve_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get Dockerfile for a specific CVE."""
    result = await db.execute(
        select(CVEDockerfile).where(CVEDockerfile.cve_id == cve_id.upper())
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Dockerfile found for {cve_id}",
        )

    return CVEDockerfileResponse(
        id=entry.id,
        cve_id=entry.cve_id,
        dockerfile=entry.dockerfile,
        source_files=entry.source_files or [],
        base_image=entry.base_image,
        exposed_ports=entry.exposed_ports or [],
        exploit_hint=entry.exploit_hint,
        status=entry.status.value,
        confidence_score=entry.confidence_score,
        confidence_reason=entry.confidence_reason,
        created_by=entry.created_by,
        aliases=entry.aliases or [],
    )


@router.get("/", response_model=list[dict])
async def list_cve_dockerfiles(
    cve_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List all CVE Dockerfiles in registry."""
    query = select(CVEDockerfile)

    if cve_status:
        try:
            query = query.where(CVEDockerfile.status == CVEDockerfileStatus(cve_status))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {cve_status}",
            )

    query = query.order_by(CVEDockerfile.cve_id).limit(limit)
    result = await db.execute(query)
    entries = result.scalars().all()

    return [
        {
            "cve_id": e.cve_id,
            "status": e.status.value,
            "base_image": e.base_image,
            "confidence_score": e.confidence_score,
            "aliases": e.aliases or [],
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


@router.get("/resolve/{reference}")
async def resolve_cve(
    reference: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Resolve a CVE reference (ID or alias) to a cached Dockerfile.

    Examples:
        /cve-registry/resolve/CVE-2021-44228
        /cve-registry/resolve/log4shell
        /cve-registry/resolve/react2shell
    """
    result = await resolve_cve_reference(reference, db)
    return result


class AliasUpdate(BaseModel):
    """Schema for updating aliases."""
    aliases: list[str] = Field(..., description="List of aliases (one per line)")


@router.patch("/{cve_id}/aliases")
async def update_cve_aliases(
    cve_id: str,
    data: AliasUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_service),
):
    """Update aliases for a CVE entry."""
    success = await set_aliases(cve_id, data.aliases, db)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Dockerfile found for {cve_id}",
        )

    return {"cve_id": cve_id.upper(), "aliases": data.aliases}


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_cve_dockerfile(
    data: CVEDockerfileCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_service),
):
    """Create a new CVE Dockerfile entry."""
    # Check if exists
    result = await db.execute(
        select(CVEDockerfile).where(CVEDockerfile.cve_id == data.cve_id.upper())
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"CVE {data.cve_id} already exists",
        )

    try:
        entry_status = CVEDockerfileStatus(data.status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {data.status}",
        )

    entry = CVEDockerfile(
        cve_id=data.cve_id.upper(),
        dockerfile=data.dockerfile,
        source_files=[sf.model_dump() for sf in data.source_files],
        base_image=data.base_image,
        exposed_ports=data.exposed_ports,
        exploit_hint=data.exploit_hint,
        status=entry_status,
        confidence_score=data.confidence_score,
        confidence_reason=data.confidence_reason,
        created_by=getattr(current_user, "email", "service"),
    )

    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    logger.info(f"Created CVE Dockerfile: {entry.cve_id} by {entry.created_by}")
    return {"id": str(entry.id), "cve_id": entry.cve_id}


@router.delete("/{cve_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cve_dockerfile(
    cve_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_service),
):
    """Delete a CVE Dockerfile entry."""
    result = await db.execute(
        select(CVEDockerfile).where(CVEDockerfile.cve_id == cve_id.upper())
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Dockerfile found for {cve_id}",
        )

    await db.delete(entry)
    await db.commit()
    logger.info(f"Deleted CVE Dockerfile: {cve_id}")


@router.get("/{cve_id}/metadata")
async def get_cve_metadata_endpoint(
    cve_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get CVE metadata from NVD (cached)."""
    from app.services.nvd_client import get_cve_metadata

    data = await get_cve_metadata(cve_id, db)

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CVE {cve_id} not found in NVD",
        )

    return data


class ExploitMetadataUpdate(BaseModel):
    """Schema for updating exploit verification metadata."""

    exploit_command: Optional[str] = None
    exploit_steps: Optional[list[dict]] = None
    expected_output: Optional[str] = None
    verification_type: Optional[str] = None
    exploit_timeout_seconds: Optional[int] = Field(None, ge=5, le=300)


@router.patch("/{cve_id}/exploit-metadata")
async def update_exploit_metadata(
    cve_id: str,
    data: ExploitMetadataUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user_or_service),
):
    """Update exploit verification metadata for a CVE."""
    result = await db.execute(
        select(CVEDockerfile).where(CVEDockerfile.cve_id == cve_id.upper())
    )
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No Dockerfile found for {cve_id}",
        )

    # Update fields if provided
    if data.exploit_command is not None:
        entry.exploit_command = data.exploit_command
    if data.exploit_steps is not None:
        entry.exploit_steps = data.exploit_steps
    if data.expected_output is not None:
        entry.expected_output = data.expected_output
    if data.verification_type is not None:
        try:
            entry.verification_type = VerificationType(data.verification_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid verification_type: {data.verification_type}. "
                f"Valid values: {[v.value for v in VerificationType]}",
            )
    if data.exploit_timeout_seconds is not None:
        entry.exploit_timeout_seconds = data.exploit_timeout_seconds

    # Reset verification status when exploit metadata changes
    entry.verification_status = VerificationStatus.untested

    await db.commit()
    await db.refresh(entry)

    logger.info(f"Updated exploit metadata for {cve_id} by {getattr(current_user, 'email', 'service')}")

    return {
        "cve_id": entry.cve_id,
        "exploit_command": entry.exploit_command,
        "expected_output": entry.expected_output,
        "verification_type": entry.verification_type.value if entry.verification_type else None,
        "verification_status": entry.verification_status.value if entry.verification_status else None,
    }


@router.post("/{cve_id}/verify")
async def trigger_cve_verification(
    cve_id: str,
    current_user=Depends(get_current_user_or_service),
):
    """
    Trigger CVE exploit verification smoke test.

    This spawns a lab, executes the exploit command, and verifies the output.
    The verification status is updated in the database.

    IMPORTANT: This is a long-running operation (may take 2+ minutes).
    """
    logger.info(f"CVE verification triggered for {cve_id} by {getattr(current_user, 'email', 'service')}")

    result = await verify_cve_exploit(cve_id)

    return result.to_dict()
